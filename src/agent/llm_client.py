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


def _strip_markdown_json_fence(text: str) -> str:
    """Remove optional ``` / ```json fences without mangling inner backticks."""
    s = (text or "").strip()
    if not s.startswith("```"):
        return s
    lines = s.splitlines()
    if not lines:
        return s
    lines = lines[1:]
    while lines and lines[-1].strip().startswith("```"):
        lines.pop()
    return "\n".join(lines).strip()


def _parse_gemini_json_object(text: str, *, context: str) -> dict[str, Any]:
    raw = _strip_markdown_json_fence(text)
    if not raw:
        raise LlmClientError(f"Gemini returned empty {context} response")
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        raise LlmClientError(f"Gemini {context} response is not valid JSON: {e}") from e
    if not isinstance(obj, dict):
        raise LlmClientError(f"Gemini {context} JSON must be a JSON object")
    return obj


GEMINI_NO_MATCH_GROUNDED_SYSTEM = """You are PRISM, an Oracle DBA assistant. The deterministic engine returned NO_MATCH.

You must return STRICT JSON only (no markdown fences) with exactly these keys:
  "summary": string (max 700 characters),
  "recommended_command_ids": array of strings.

Rules:
- recommended_command_ids MUST be a subset of allowed_command_refs[].id. If that list is empty, use [].
- Do NOT output shell commands, SQL, or crsctl/alter text in any field; only cite IDs from the allow-list.
- In summary, do not name Oracle error or CRS tokens unless they appear in observed_codes. If observed_codes is empty, avoid specific error codes entirely; write only generic collection/correlation guidance.
- Do not invent hostnames, paths, disk groups, or patch IDs.
"""


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

    cfg_json = genai.GenerationConfig(
        temperature=0.1,
        top_p=0.1,
        top_k=1,
        max_output_tokens=4096,
        response_mime_type="application/json",
    )
    cfg_plain = genai.GenerationConfig(
        temperature=0.1,
        top_p=0.1,
        top_k=1,
        max_output_tokens=4096,
    )

    for mname in model_candidates:
        gm = genai.GenerativeModel(mname)
        for cfg in (cfg_json, cfg_plain):
            try:
                r = gm.generate_content(
                    prompt,
                    generation_config=cfg,
                    request_options={"timeout": timeout_sec},
                )
                t = (getattr(r, "text", None) or "").strip()
                if not t:
                    continue
                resp = r
                used_model = mname
                break
            except Exception as e:  # pragma: no cover
                last_err = e
                continue
        if resp is not None:
            break
    if resp is None:
        raise LlmClientError(f"Gemini request failed across models: {last_err}")

    text = getattr(resp, "text", "") or ""
    text = text.strip()
    if not text:
        raise LlmClientError("Gemini returned empty response")

    parsed = _parse_gemini_json_object(text, context="advisory")

    out = parse_llm_advisory_output(parsed)
    # attach selected runtime model for caller visibility
    setattr(out, "_used_model", used_model)
    return out


def call_gemini_no_match_grounded(
    payload: dict[str, Any],
    *,
    model: str = "gemini-2.0-flash",
    timeout_sec: int = 20,
) -> dict[str, Any]:
    """
    NO_MATCH only: JSON with summary + recommended_command_ids (KB bundle IDs).
    Temperature 0 for repeatable outputs on identical prompts.
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise LlmClientError("GEMINI_API_KEY is not set")

    try:
        import google.generativeai as genai
    except Exception as e:  # pragma: no cover
        raise LlmClientError(f"google-generativeai import failed: {e}") from e

    genai.configure(api_key=api_key)
    requested = (model or "").strip()
    model_candidates: list[str] = []
    for m in (
        requested,
        requested.replace("models/", "") if requested else "",
        f"models/{requested}" if requested and not requested.startswith("models/") else "",
        "gemini-2.0-flash",
        "models/gemini-2.0-flash",
        "gemini-1.5-flash-latest",
        "models/gemini-1.5-flash-latest",
    ):
        if m and m not in model_candidates:
            model_candidates.append(m)
    try:
        for mi in genai.list_models():
            name = getattr(mi, "name", "") or ""
            methods = list(getattr(mi, "supported_generation_methods", []) or [])
            if "generateContent" in methods and name and name not in model_candidates:
                model_candidates.append(name)
    except Exception:
        pass

    prompt = (
        f"{GEMINI_NO_MATCH_GROUNDED_SYSTEM}\n\n"
        f"Input:\n{json.dumps(payload, ensure_ascii=True)}"
    )

    last_err = None
    resp = None
    used_model = None
    cfg_json = genai.GenerationConfig(
        temperature=0.0,
        top_p=1.0,
        top_k=1,
        max_output_tokens=2048,
        response_mime_type="application/json",
    )
    cfg_plain = genai.GenerationConfig(
        temperature=0.0,
        top_p=1.0,
        top_k=1,
        max_output_tokens=2048,
    )
    for mname in model_candidates:
        gm = genai.GenerativeModel(mname)
        for cfg in (cfg_json, cfg_plain):
            try:
                r = gm.generate_content(
                    prompt,
                    generation_config=cfg,
                    request_options={"timeout": timeout_sec},
                )
                t = (getattr(r, "text", None) or "").strip()
                if not t:
                    continue
                resp = r
                used_model = mname
                break
            except Exception as e:  # pragma: no cover
                last_err = e
                continue
        if resp is not None:
            break
    if resp is None:
        raise LlmClientError(f"Gemini request failed across models: {last_err}")

    text = getattr(resp, "text", "") or ""
    text = text.strip()
    if not text:
        raise LlmClientError("Gemini returned empty response")
    return _parse_gemini_json_object(text, context="no_match_grounded")


RAG_REMEDIATION_PICK_SYSTEM = """You are PRISM. Return STRICT JSON with exactly two keys:
  "summary": string (max 480 characters), plain English for a senior Oracle DBA.
  "indices": array of integers.

Input lists a "catalog" of evidence rows. Each row has:
  "i" — 0-based index into the pool,
  "source" — "graph" (knowledge graph runbook text) or "rag" (retrieved log chunk),
  "ora_code" — optional ORA code for graph rows,
  "preview" — truncated text from that pool row.

Task: choose an ordered list of indices that form the best **remediation-oriented reading list** for this incident.
Prefer graph rows whose previews look like actionable operator steps (SQL, crsctl, asmcmd, etc.) when relevant;
include rag rows when they add corroborating incident context.

Rules:
- "indices" must contain only integers that appear as "i" in the catalog, each at most once, at most 12 entries.
- Do not invent indices or paste full commands that are not represented in the catalog previews.
- If nothing is actionable, return an empty indices array and explain in summary.
"""


def call_gemini_rag_remediation_pick(
    *,
    incident_id: str,
    observed_codes: list[str],
    root_pattern: str,
    catalog: list[dict[str, Any]],
    model: str = "gemini-2.0-flash",
    timeout_sec: int = 25,
) -> dict[str, Any]:
    """
    Gemini selects only catalog indices; caller expands to full pool text (no free-form fixes).
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise LlmClientError("GEMINI_API_KEY is not set")

    try:
        import google.generativeai as genai
    except Exception as e:  # pragma: no cover
        raise LlmClientError(f"google-generativeai import failed: {e}") from e

    genai.configure(api_key=api_key)
    requested = (model or "").strip()
    model_candidates: list[str] = []
    for m in (
        requested,
        requested.replace("models/", "") if requested else "",
        f"models/{requested}" if requested and not requested.startswith("models/") else "",
        "gemini-2.0-flash",
        "models/gemini-2.0-flash",
        "gemini-1.5-flash-latest",
        "models/gemini-1.5-flash-latest",
    ):
        if m and m not in model_candidates:
            model_candidates.append(m)

    payload = {
        "incident_id": incident_id,
        "observed_codes": observed_codes,
        "root_pattern": root_pattern,
        "catalog": catalog,
    }
    prompt = f"{RAG_REMEDIATION_PICK_SYSTEM}\n\nInput:\n{json.dumps(payload, ensure_ascii=True)}"

    last_err = None
    resp = None
    cfg_json = genai.GenerationConfig(
        temperature=0.0,
        top_p=1.0,
        top_k=1,
        max_output_tokens=1536,
        response_mime_type="application/json",
    )
    cfg_plain = genai.GenerationConfig(
        temperature=0.0,
        top_p=1.0,
        top_k=1,
        max_output_tokens=1536,
    )
    for mname in model_candidates:
        gm = genai.GenerativeModel(mname)
        for cfg in (cfg_json, cfg_plain):
            try:
                r = gm.generate_content(
                    prompt,
                    generation_config=cfg,
                    request_options={"timeout": timeout_sec},
                )
                t = (getattr(r, "text", None) or "").strip()
                if not t:
                    continue
                resp = r
                break
            except Exception as e:  # pragma: no cover
                last_err = e
                continue
        if resp is not None:
            break
    if resp is None:
        raise LlmClientError(f"Gemini request failed across models: {last_err}")

    text = (getattr(resp, "text", None) or "").strip()
    if not text:
        raise LlmClientError("Gemini returned empty response")
    out = _parse_gemini_json_object(text, context="rag_remediation_pick")
    return out


REMEDIATION_PLAYBOOK_ADVISORY_SYSTEM = """You are PRISM, assisting a senior Oracle DBA.

Return STRICT JSON only (no markdown fences) with exactly one key:
  "markdown": string

The "markdown" value MUST be GitHub-flavored Markdown for a **generic advisory operator playbook** (Option A: not verified for this environment). Audience: production DBAs.

Content requirements:
1) Start with 2–4 sentences: what the observed ORA/layer pattern *typically* indicates (no claim that you verified this cluster).
2) Then sections with ### headings, e.g. "### Oracle Restart / single-instance", "### RAC", "### SQL*Plus / manual ASM (fallback)", "### If disk group will not mount (diagnostics)" — include only sections that plausibly apply to observed_layers and codes; omit irrelevant stacks.
3) Use fenced code blocks: ```bash ... ``` and ```sql ... ``` for commands. Prefer official-style tools: crsctl, srvctl, asmcmd, adrci, sqlplus. No prose inside fences except # comments at line start.
4) Use placeholders for anything not explicitly present in the input excerpt: <GRID_HOME>, <DB_HOME>, <DB_UNIQUE_NAME>, <DISKGROUP>, <NODE>, <ASM_INSTANCE>, <DB_INSTANCE>. Never invent real hostnames, paths, or disk group names as literals unless they appear verbatim in context_excerpt.
5) Add a short "### Safety" subsection: review accompanying alert/trace errors; do not drop or recreate disk groups to "fix" connectivity issues; human review before mutating state.
6) Keep total markdown under 11000 characters. No HTML. No links unless you are certain they are docs.oracle.com error-help URLs (optional, max 3 links).

Do not output any keys other than "markdown"."""


def call_gemini_advisory_remediation_playbook(
    payload: dict[str, Any],
    *,
    model: str = "gemini-2.0-flash",
    timeout_sec: int = 45,
) -> tuple[dict[str, Any], str]:
    """
    Option A: LLM-authored generic remediation playbook (advisory only).
    Returns (parsed_json_dict, used_model_name).
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise LlmClientError("GEMINI_API_KEY is not set")

    try:
        import google.generativeai as genai
    except Exception as e:  # pragma: no cover
        raise LlmClientError(f"google-generativeai import failed: {e}") from e

    genai.configure(api_key=api_key)
    requested = (model or "").strip()
    model_candidates: list[str] = []
    for m in (
        requested,
        requested.replace("models/", "") if requested else "",
        f"models/{requested}" if requested and not requested.startswith("models/") else "",
        "gemini-2.0-flash",
        "models/gemini-2.0-flash",
        "gemini-1.5-flash-latest",
        "models/gemini-1.5-flash-latest",
    ):
        if m and m not in model_candidates:
            model_candidates.append(m)
    try:
        for mi in genai.list_models():
            name = getattr(mi, "name", "") or ""
            methods = list(getattr(mi, "supported_generation_methods", []) or [])
            if "generateContent" in methods and name and name not in model_candidates:
                model_candidates.append(name)
    except Exception:
        pass

    prompt = f"{REMEDIATION_PLAYBOOK_ADVISORY_SYSTEM}\n\nInput:\n{json.dumps(payload, ensure_ascii=True)}"

    last_err = None
    resp = None
    used_model: str | None = None
    cfg_json = genai.GenerationConfig(
        temperature=0.15,
        top_p=0.9,
        top_k=32,
        max_output_tokens=8192,
        response_mime_type="application/json",
    )
    cfg_plain = genai.GenerationConfig(
        temperature=0.15,
        top_p=0.9,
        top_k=32,
        max_output_tokens=8192,
    )
    for mname in model_candidates:
        gm = genai.GenerativeModel(mname)
        for cfg in (cfg_json, cfg_plain):
            try:
                r = gm.generate_content(
                    prompt,
                    generation_config=cfg,
                    request_options={"timeout": timeout_sec},
                )
                t = (getattr(r, "text", None) or "").strip()
                if not t:
                    continue
                resp = r
                used_model = mname
                break
            except Exception as e:  # pragma: no cover
                last_err = e
                continue
        if resp is not None:
            break
    if resp is None:
        raise LlmClientError(f"Gemini request failed across models: {last_err}")

    text = (getattr(resp, "text", None) or "").strip()
    if not text:
        raise LlmClientError("Gemini returned empty response")
    out = _parse_gemini_json_object(text, context="advisory_remediation_playbook")
    return out, (used_model or model or "unknown")


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

