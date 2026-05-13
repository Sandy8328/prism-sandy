"""
Gemini client wrapper for constrained advisory calls.

No business logic in this module; it only performs model invocation and parsing.
"""

from __future__ import annotations

import json
import os
from typing import Any

from src.agent.llm_schema import LlmAdvisoryInput, parse_llm_advisory_output, LlmAdvisoryOutput
from src.agent.llm_verifier_prompt import GEMINI_ADVISORY_SYSTEM


class LlmClientError(RuntimeError):
    pass


def _to_prompt_payload(advisory_input: LlmAdvisoryInput) -> dict[str, Any]:
    return {
        "incident_id": advisory_input.incident_id,
        "candidates": [
            {
                "pattern_id": c.pattern_id,
                "score": c.score,
                "supporting_codes": c.supporting_codes,
                "contradicting_codes": c.contradicting_codes,
            }
            for c in advisory_input.candidates
        ],
        "observed_codes": advisory_input.observed_codes,
        "observed_layers": advisory_input.observed_layers,
        "constraints": advisory_input.constraints,
    }


def call_gemini_advisory(
    advisory_input: LlmAdvisoryInput,
    *,
    model: str = "gemini-1.5-pro",
    timeout_sec: int = 20,
) -> LlmAdvisoryOutput:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise LlmClientError("GEMINI_API_KEY is not set")

    try:
        import google.generativeai as genai
    except Exception as e:  # pragma: no cover
        raise LlmClientError(f"google-generativeai import failed: {e}") from e

    genai.configure(api_key=api_key)
    requested = (model or "").strip()
    model_candidates = []
    for m in (
        requested,
        requested.replace("models/", "") if requested else "",
        f"models/{requested}" if requested and not requested.startswith("models/") else "",
        "gemini-2.0-flash",
        "models/gemini-2.0-flash",
        "gemini-1.5-flash-latest",
        "models/gemini-1.5-flash-latest",
        "gemini-1.5-pro-latest",
        "models/gemini-1.5-pro-latest",
    ):
        if m and m not in model_candidates:
            model_candidates.append(m)

    # Dynamic fallback: discover any model that supports generateContent.
    try:
        listed = []
        for mi in genai.list_models():
            name = getattr(mi, "name", "") or ""
            methods = list(getattr(mi, "supported_generation_methods", []) or [])
            if "generateContent" in methods and name:
                listed.append(name)
        for name in listed:
            if name not in model_candidates:
                model_candidates.append(name)
    except Exception:
        pass
    payload = _to_prompt_payload(advisory_input)
    prompt = (
        f"{GEMINI_ADVISORY_SYSTEM}\n\n"
        "Return STRICT JSON only with keys: selected_hypothesis, confidence_band, rationale, "
        "rejected_hypotheses, next_commands, needs_more_evidence. No extra keys. No markdown.\n"
        "Choose selected_hypothesis only from candidates[].pattern_id.\n"
        f"Input:\n{json.dumps(payload, ensure_ascii=True)}"
    )

    last_err = None
    resp = None
    used_model = None
    for mname in model_candidates:
        try:
            gm = genai.GenerativeModel(mname)
            resp = gm.generate_content(
                prompt,
                generation_config={
                    "temperature": 0.1,
                    "top_p": 0.1,
                    "top_k": 1,
                },
                request_options={"timeout": timeout_sec},
            )
            used_model = mname
            break
        except Exception as e:  # pragma: no cover
            last_err = e
            continue
    if resp is None:
        raise LlmClientError(f"Gemini request failed across models: {last_err}")

    text = getattr(resp, "text", "") or ""
    text = text.strip()
    if not text:
        raise LlmClientError("Gemini returned empty response")

    # Tolerate fenced output.
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise LlmClientError(f"Gemini response is not valid JSON: {e}") from e

    out = parse_llm_advisory_output(parsed)
    # attach selected runtime model for caller visibility
    setattr(out, "_used_model", used_model)
    return out


def call_gemini_ora_meaning_one_liner(
    ora_code: str,
    *,
    timeout_sec: int | None = None,
) -> str | None:
    """
    Returns one plain sentence (≤220 chars) for UI ORA meaning cells when PDF/runbook
    does not provide text or marks Oracle Support boilerplate. Returns None on failure.
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None

    ora = (ora_code or "").strip().upper()
    if not ora.startswith("ORA-"):
        return None

    try:
        import google.generativeai as genai
    except Exception:
        return None

    to = timeout_sec
    model_name = "gemini-2.0-flash"
    try:
        import yaml
        from pathlib import Path

        cfg_path = Path(__file__).resolve().parents[2] / "config" / "settings.yaml"
        with open(cfg_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        llm = cfg.get("llm") or {}
        if to is None:
            to = int(llm.get("timeout_sec") or 15)
        model_name = (llm.get("model") or model_name).replace("models/", "")
    except Exception:
        if to is None:
            to = 15

    genai.configure(api_key=api_key)
    prompt = (
        "You assist Oracle DBAs. Reply with exactly ONE plain English sentence (max 220 characters), "
        "no quotes or bullets, describing what the Oracle Database error "
        f"{ora} generally indicates and where an operator would look first (alert log, trace, etc.). "
        "Do not invent bug numbers, patch IDs, or undocumented internals. "
        "If you are unsure, say it is an Oracle-program exception and to collect ADR traces and check My Oracle Support."
    )

    model_candidates: list[str] = []
    for m in (
        model_name,
        f"models/{model_name}" if not model_name.startswith("models/") else model_name,
        "gemini-2.0-flash",
        "models/gemini-2.0-flash",
        "gemini-1.5-flash-latest",
        "models/gemini-1.5-flash-latest",
    ):
        if m and m not in model_candidates:
            model_candidates.append(m)

    resp = None
    for mname in model_candidates:
        try:
            gm = genai.GenerativeModel(mname)
            resp = gm.generate_content(
                prompt,
                generation_config={
                    "temperature": 0.1,
                    "top_p": 0.2,
                    "top_k": 8,
                    "max_output_tokens": 128,
                },
                request_options={"timeout": to},
            )
            break
        except Exception:
            continue
    if resp is None:
        return None
    text = (getattr(resp, "text", None) or "").strip()
    if not text:
        return None
    text = " ".join(text.split())
    if len(text) > 280:
        text = text[:277].rstrip() + "…"
    return text

