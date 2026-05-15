"""
Option A: LLM-generated generic remediation playbook (advisory only).

Separate from read-only triage next_commands and from RAG index-grounded outlines.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from src.agent.llm_client import LlmClientError, call_gemini_advisory_remediation_playbook
from src.agent.rag_remediation_outline import (
    _oras_from_report_and_events,
    _session_retrieval_query,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config" / "settings.yaml"


def _load_cfg() -> dict[str, Any]:
    try:
        import yaml

        with open(CONFIG_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _clamp_markdown(text: str, max_chars: int) -> str:
    s = (text or "").strip()
    if max_chars <= 0 or len(s) <= max_chars:
        return s
    return s[: max_chars - 20].rstrip() + "\n\n_(truncated)_"


def attach_advisory_remediation_playbook(
    report: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    incident_id: str,
) -> None:
    cfg = _load_cfg()
    llm = cfg.get("llm") or {}
    sub = llm.get("remediation_playbook_advisory") or {}
    if not bool(llm.get("enabled", False)) or not bool(sub.get("enabled", False)):
        report["advisory_remediation_playbook"] = {"used": False, "reason": "disabled"}
        return
    if not os.getenv("GEMINI_API_KEY", "").strip():
        report["advisory_remediation_playbook"] = {"used": False, "reason": "no_gemini_api_key"}
        return

    max_ctx = int(sub.get("max_context_chars") or 8000)
    max_md = int(sub.get("max_markdown_chars") or 14000)
    timeout_sec = int(sub.get("timeout_sec") or llm.get("timeout_sec") or 45)
    if timeout_sec < 20:
        timeout_sec = 20

    ora_codes = _oras_from_report_and_events(report, events)
    observed_layers = sorted(
        {(e.get("layer") or "UNKNOWN").strip().upper() for e in (events or []) if e.get("layer")}
    )
    excerpt = _session_retrieval_query(events, cap=max_ctx)
    if len(excerpt) < 80:
        excerpt = (
            "\n".join(ora_codes[:24])
            + "\n"
            + str((report.get("root_cause") or {}).get("description") or "")
        )[:max_ctx]

    if not ora_codes and len(excerpt.strip()) < 40:
        report["advisory_remediation_playbook"] = {
            "used": False,
            "reason": "insufficient_context",
        }
        return

    payload = {
        "incident_id": incident_id,
        "report_status": str(report.get("status") or ""),
        "observed_codes": ora_codes[:48],
        "observed_layers": observed_layers,
        "root_pattern": str((report.get("root_cause") or {}).get("pattern") or ""),
        "context_excerpt": excerpt,
    }

    try:
        raw, used_model = call_gemini_advisory_remediation_playbook(
            payload,
            model=str(llm.get("model") or "gemini-2.0-flash"),
            timeout_sec=timeout_sec,
        )
    except LlmClientError as e:
        report["advisory_remediation_playbook"] = {
            "used": False,
            "reason": str(e),
        }
        return
    except Exception as e:
        report["advisory_remediation_playbook"] = {
            "used": False,
            "reason": f"playbook_failed:{e}",
        }
        return

    md = str(raw.get("markdown") or "").strip()
    if len(md) < 120:
        report["advisory_remediation_playbook"] = {
            "used": False,
            "reason": "empty_or_short_markdown",
        }
        return

    report["advisory_remediation_playbook"] = {
        "used": True,
        "markdown": _clamp_markdown(md, max_md),
        "model": used_model,
        "kind": "advisory_option_a",
    }
