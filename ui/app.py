"""
app.py — Streamlit UI for PRISM (evidence-first Oracle diagnostics).

Run: streamlit run ui/app.py
"""

from __future__ import annotations
import os
import sys
import time
import json
import zipfile
import shutil
import uuid
from pathlib import Path
from collections import Counter
from datetime import datetime

# Project root (absolute; do not chdir — avoids breaking paths in multi-process runs)
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import streamlit as st
import yaml

# Load config for defaults
_ROOT_CFG = os.path.join(_ROOT, "config", "settings.yaml")
try:
    with open(_ROOT_CFG) as _cf:
        _cfg = yaml.safe_load(_cf)
    _DEFAULT_TOP_K    = _cfg.get("retrieval", {}).get("top_k", 10)
    _MODEL_NAME       = _cfg.get("embedding", {}).get("model_name", "all-MiniLM-L6-v2")
except Exception:
    _DEFAULT_TOP_K = 10
    _MODEL_NAME    = "all-MiniLM-L6-v2"

# ── Page config ─────────────────────────────────────────────────
st.set_page_config(
    page_title="PRISM",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ──────────────────────────────────────────────────────────
st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

  html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

  /* Light enterprise shell — cool gray page, white surfaces */
  .main { background: #f1f5f9; }
  .stApp { background: #f1f5f9; color: #0f172a; }

  /* Title bar — navy strip reads “official” without dark chrome */
  .title-bar {
    background: linear-gradient(135deg, #1e40af 0%, #1e3a8a 100%);
    border: 1px solid #1d4ed8;
    border-radius: 12px;
    padding: 20px 28px;
    margin-bottom: 24px;
    box-shadow: 0 2px 8px rgba(30, 64, 175, 0.12);
  }
  .title-bar h1 { font-size: 24px; font-weight: 700; color: #ffffff; margin: 0; }
  .title-bar p  { font-size: 13px; color: #bfdbfe; margin: 4px 0 0; }

  /* Confidence badge — soft fills on light UI */
  .badge-high   { background:#ecfdf5; color:#047857; border:1px solid #6ee7b7;
                  border-radius:6px; padding:3px 10px; font-size:13px; font-weight:600; }
  .badge-medium { background:#fefce8; color:#a16207; border:1px solid #fde047;
                  border-radius:6px; padding:3px 10px; font-size:13px; font-weight:600; }
  .badge-low    { background:#fff7ed; color:#c2410c; border:1px solid #fdba74;
                  border-radius:6px; padding:3px 10px; font-size:13px; font-weight:600; }
  .badge-nomatch{ background:#f8fafc; color:#64748b; border:1px solid #e2e8f0;
                  border-radius:6px; padding:3px 10px; font-size:13px; font-weight:600; }

  /* Cards */
  .card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 16px 20px;
    margin-bottom: 14px;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  }
  .card-title { font-size:13px; font-weight:600; color:#64748b; text-transform:uppercase;
                letter-spacing:0.5px; margin-bottom:10px; }

  /* Chain item */
  .chain-item { background:#f8fafc; border-left:3px solid #2563eb;
                border-radius:0 6px 6px 0; padding:6px 12px;
                margin:4px 0; font-size:13px; font-family:monospace; color:#334155; }
  .chain-root { border-left-color:#b91c1c; }
  .chain-db   { border-left-color:#ea580c; }

  /* Fix command */
  .fix-cmd { background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px;
             padding:8px 12px; font-family:monospace; font-size:12px;
             color:#1e40af; margin:4px 0; }

  /* Evidence box */
  .evidence-box { background:#f8fafc; border:1px solid #e2e8f0;
                  border-radius:6px; padding:10px 14px; margin:6px 0;
                  font-family:monospace; font-size:11px; color:#475569;
                  max-height:120px; overflow-y:auto; }

  /* Cascade banner */
  .cascade-banner {
    background: linear-gradient(135deg, #fffbeb 0%, #fef3c7 100%);
    border: 1px solid #f59e0b;
    border-radius: 8px;
    padding: 12px 16px;
    margin-bottom: 14px;
    color: #78350f;
  }

  /* Metric row */
  .metric-row { display:flex; gap:16px; flex-wrap:wrap; margin-bottom:14px; }
  .metric-box { background:#ffffff; border:1px solid #e2e8f0; border-radius:8px;
                padding:12px 16px; flex:1; min-width:120px;
                box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04); }
  .metric-val { font-size:22px; font-weight:700; color:#1e40af; }
  .metric-lbl { font-size:11px; color:#64748b; margin-top:2px; }

  /* Sidebar */
  section[data-testid="stSidebar"] {
    background: #ffffff;
    border-right: 1px solid #e2e8f0;
  }
</style>
""", unsafe_allow_html=True)


# ── Agent init (cached) ──────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def load_agent():
    from src.agent.agent import get_agent
    return get_agent()


def _prism_cache_dir() -> Path:
    sid = str(st.session_state.get("prism_session_id") or "default")
    return Path(_ROOT) / ".prism_session_cache" / sid


def _prism_init_session_state() -> None:
    if "prism_session_id" not in st.session_state:
        st.session_state["prism_session_id"] = str(uuid.uuid4())[:12]
    if "prism_session_turns" not in st.session_state:
        st.session_state["prism_session_turns"] = []
    if "prism_confirm_reset" not in st.session_state:
        st.session_state["prism_confirm_reset"] = False


def _prism_hard_reset() -> None:
    sid = st.session_state.get("prism_session_id")
    if sid:
        d = Path(_ROOT) / ".prism_session_cache" / str(sid)
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
    st.session_state["prism_session_turns"] = []
    st.session_state["prism_session_id"] = str(uuid.uuid4())[:12]
    st.session_state["last_report"] = None
    st.session_state["incident_context_text"] = ""
    st.session_state["incident_history"] = []
    st.session_state["prism_confirm_reset"] = False


# ── Helpers ──────────────────────────────────────────────────────
def _badge(label: str) -> str:
    cls = {
        "HIGH": "badge-high",
        "MEDIUM": "badge-medium",
        "LOW": "badge-low",
    }.get(label, "badge-nomatch")
    return f'<span class="{cls}">{label}</span>'


def _render_causal_chain(chain: list[str]):
    for step in chain:
        cls = "chain-root" if step.startswith("ROOT") else "chain-db" if step.startswith("DB") else ""
        st.markdown(f'<div class="chain-item {cls}">{step}</div>', unsafe_allow_html=True)


def _render_fix(fix: dict, idx: int):
    risk_color = {"LOW":"#15803d","MEDIUM":"#a16207","HIGH":"#c2410c","CRITICAL":"#b91c1c"}.get(fix["risk"],"#64748b")
    dt = "⚠️ Downtime required" if fix.get("downtime_required") else ""
    cat = fix.get("command_category") or "REMEDIATION"
    cat_badge = f'<span style="color:#64748b;font-size:11px">[{cat}]</span>'
    st.markdown(
        f'<div class="card">'
        f'<div class="card-title">Fix {fix["priority"]} — {fix["fix_id"]} '
        f'<span style="color:{risk_color}">●</span> {fix["risk"]} risk '
        f'<span style="color:#64748b;font-size:11px">requires: {fix["requires"]}</span>'
        f" {cat_badge}"
        f'{" &nbsp;&nbsp; " + dt if dt else ""}</div>',
        unsafe_allow_html=True
    )
    for cmd in fix["commands"]:
        st.markdown(f'<div class="fix-cmd">$ {cmd}</div>', unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


def _append_incident_history(report: dict | None) -> None:
    """Record one row per completed diagnosis (not on every Streamlit rerun)."""
    if not report:
        return
    st.session_state["incident_history"].append({
        "time": time.strftime("%H:%M:%S"),
        "status": report.get("status"),
        "ora": (report.get("ora_code") or {}).get("code", ""),
        "pattern": (report.get("root_cause") or {}).get("pattern", ""),
    })


def _append_zip_bundle_to_incident_context(tag: str, filename: str, report: dict | None) -> None:
    """
    Persist a short text summary of ZIP bundle analysis so paste/file follow-up
    can correlate with the prior bundle (raw archive bytes are not kept in session).
    """
    if not report:
        return
    lines = [f"\n[{tag}] {filename}"]
    bs = report.get("bundle_summary") or {}
    if bs:
        parts = []
        if bs.get("analyzed_files") is not None:
            parts.append(f"analyzed_files={bs['analyzed_files']}")
        if bs.get("primary_file"):
            parts.append(f"primary_file={bs['primary_file']}")
        if bs.get("platform_inferred"):
            parts.append(f"platform={bs['platform_inferred']}")
        if parts:
            lines.append("bundle_summary: " + ", ".join(parts))
    rep_status = report.get("status")
    lines.append(f"status={rep_status}")
    if rep_status == "SUCCESS":
        ora = (report.get("ora_code") or {}).get("code", "")
        rc = (report.get("root_cause") or {}).get("pattern", "")
        if ora or rc:
            lines.append(f"finding: ora={ora} pattern={rc}")
    else:
        nmr = (report.get("no_match_reason") or "")[:800]
        if nmr:
            lines.append(f"no_match_reason: {nmr}")
    for row in (report.get("secondary_findings") or [])[:6]:
        lines.append(
            f"secondary: file={row.get('file')} st={row.get('status')} "
            f"ora={row.get('ora_code')} pat={row.get('pattern')}"
        )
    st.session_state["incident_context_text"] += "\n" + "\n".join(lines)


def _parse_ts(ts: str) -> datetime | None:
    if not ts:
        return None
    # Keep parser local to avoid startup penalty when not needed.
    from dateutil import parser as dp
    try:
        return dp.parse(ts)
    except Exception:
        return None


def _evaluate_followup_relevance(
    incoming_text: str,
    last_report: dict | None,
    override_hostname: str,
    override_platform: str,
) -> tuple[bool, list[str]]:
    """
    Validate whether follow-up evidence appears related to the same incident.
    Uses ORA, hostname, platform, and timestamp proximity as guardrails.
    """
    from src.agent.input_parser import parse_input

    parsed = parse_input(incoming_text)
    reasons: list[str] = []

    base_ora = ((last_report or {}).get("ora_code") or {}).get("code", "")
    base_family = set(
        [x for x in [base_ora] + ((last_report or {}).get("related_errors") or []) if x]
    )
    new_family = set(parsed.get("all_ora_codes") or ([parsed.get("primary_ora")] if parsed.get("primary_ora") else []))
    # Accept follow-ups when there is ORA family overlap, even if primary ORA changed
    # (e.g. ORA-27072 -> ORA-15080 -> ORA-00353 in the same storage incident).
    if base_family and new_family and not (base_family & new_family):
        reasons.append(
            f"ORA mismatch: existing family `{', '.join(sorted(base_family))}` "
            f"vs follow-up `{', '.join(sorted(new_family))}`."
        )

    base_host = override_hostname or ((last_report or {}).get("hostname") or "")
    new_host = parsed.get("hostname", "")
    if base_host and new_host and base_host.lower() != new_host.lower():
        reasons.append(f"Hostname mismatch: existing `{base_host}` vs follow-up `{new_host}`.")

    base_platform = override_platform if override_platform and override_platform != "(auto-detect)" else ((last_report or {}).get("platform") or "")
    new_platform = parsed.get("platform", "")
    if (
        base_platform
        and new_platform
        and base_platform.upper() != "UNKNOWN"
        and new_platform.upper() != "UNKNOWN"
        and base_platform.upper() != new_platform.upper()
    ):
        reasons.append(f"Platform mismatch: existing `{base_platform}` vs follow-up `{new_platform}`.")

    base_ts = _parse_ts((last_report or {}).get("timestamp_str", ""))
    new_ts = _parse_ts(parsed.get("timestamp_str", ""))
    if base_ts and new_ts:
        if abs((new_ts - base_ts).total_seconds()) > (6 * 3600):
            reasons.append("Timestamp appears outside 6-hour incident window.")

    return (len(reasons) == 0), reasons


def _followup_ack(report: dict, prefix: str) -> str:
    conf = report.get("confidence") or {}
    score = conf.get("score", 0)
    reason = report.get("no_match_reason") or "Evidence accepted for correlation."
    bd = conf.get("breakdown") or {}
    why = (
        f"keyword={bd.get('keyword',0)}, bm25={bd.get('bm25',0)}, "
        f"semantic={bd.get('dense',0)}, temporal={bd.get('temporal',0)}"
    )
    return (
        f"{prefix} — **{report.get('status')}** "
        f"(confidence: **{score}%**, level: **{conf.get('label', 'N/A')}**). "
        f"Reason: {reason} "
        f"[score breakdown: {why}]"
    )


def _set_followup_notice(level: str, message: str) -> None:
    st.session_state["followup_ack"] = {"level": level, "message": message}


def _report_relation_mismatches(base_report: dict | None, new_report: dict | None) -> list[str]:
    reasons: list[str] = []
    if not base_report or not new_report:
        return reasons
    b_ora = ((base_report.get("ora_code") or {}).get("code") or "").upper()
    n_ora = ((new_report.get("ora_code") or {}).get("code") or "").upper()
    if b_ora and n_ora and b_ora != n_ora:
        reasons.append(f"ORA mismatch: current incident `{b_ora}` vs uploaded bundle `{n_ora}`.")
    b_host = (base_report.get("hostname") or "").lower()
    n_host = (new_report.get("hostname") or "").lower()
    if b_host and n_host and b_host != n_host:
        reasons.append(f"Hostname mismatch: `{base_report.get('hostname')}` vs `{new_report.get('hostname')}`.")
    b_platform = (base_report.get("platform") or "").upper()
    n_platform = (new_report.get("platform") or "").upper()
    if b_platform and n_platform and b_platform != "UNKNOWN" and n_platform != "UNKNOWN" and b_platform != n_platform:
        reasons.append(f"Platform mismatch: `{b_platform}` vs `{n_platform}`.")
    return reasons


# ── Sidebar ───────────────────────────────────────────────────────
with st.sidebar:
    _prism_init_session_state()
    st.markdown("### ⚙️ Query Options")
    override_hostname = st.text_input("Hostname filter", placeholder="dbhost01")
    override_platform = st.selectbox(
        "Platform",
        ["(auto-detect)", "LINUX", "AIX", "SOLARIS", "WINDOWS", "EXADATA", "OCI"]
    )
    override_ora = st.text_input("ORA code override", placeholder="ORA-27072")
    override_ts  = st.text_input("Timestamp", placeholder="2024-03-07T02:44:18")
    top_k        = st.slider("Top K chunks", min_value=3, max_value=20, value=_DEFAULT_TOP_K)

    st.markdown("---")
    st.markdown("### Incident session")
    st.caption(
        f"Session `{st.session_state['prism_session_id']}` · "
        f"**{len(st.session_state['prism_session_turns'])}** evidence turn(s). "
        "Every run analyzes the **full** session (merged text + all ZIPs in this session)."
    )
    if st.button("Start new incident", use_container_width=True):
        st.session_state["prism_confirm_reset"] = True
    if st.session_state.get("prism_confirm_reset"):
        st.warning(
            "**Clear this session?** All pasted and uploaded log text in memory, ZIP copies saved for "
            "this session, the on-screen report, and incident history will be removed. "
            "The next session has **no link** to this one unless you add that evidence again."
        )
        c1, c2 = st.columns(2)
        if c1.button("Cancel", key="prism_sess_cancel"):
            st.session_state["prism_confirm_reset"] = False
            st.rerun()
        if c2.button("Yes, clear everything", type="primary", key="prism_sess_confirm"):
            _prism_hard_reset()
            st.rerun()

    st.markdown("---")
    st.markdown("### 📊 Index Status")
    try:
        from src.retrieval.bm25_search import index_size
        from src.vectordb.qdrant_client import count_chunks
        st.metric("Qdrant chunks", count_chunks())
        st.metric("BM25 index",    index_size())
    except Exception:
        st.info("Index not yet initialized")

    st.markdown("---")
    try:
        from src.knowledge_graph.pattern_matcher import _compile_patterns
        _n_patterns = len(_compile_patterns())
    except Exception:
        _n_patterns = 0
    st.markdown(
        '<div style="font-size:11px;color:#64748b;">'
        f'Optional Gemini advisory · temperature **0.1**<br>'
        f'{_n_patterns} regex patterns · Model: {_MODEL_NAME}'
        '</div>',
        unsafe_allow_html=True
    )

# ── Main layout ──────────────────────────────────────────────────
st.markdown(
    '<div class="title-bar">'
    '<h1>PRISM</h1>'
    '<p>Evidence-first Oracle diagnostics · Deterministic RCA · Offline-first · Multi-platform</p>'
    '</div>',
    unsafe_allow_html=True
)

_ack = st.session_state.pop("followup_ack", None)

# Session memory for multi-upload incident investigation
if "incident_history" not in st.session_state:
    st.session_state["incident_history"] = []
if "last_report" not in st.session_state:
    st.session_state["last_report"] = None
if "incident_context_text" not in st.session_state:
    st.session_state["incident_context_text"] = ""

_prism_init_session_state()

st.markdown('<div id="prism-main-input"></div>', unsafe_allow_html=True)
# Input tabs
tab_query, tab_file, tab_zip, tab_lab = st.tabs(["📝 Query / Log Paste", "📁 Upload Log File", "🗜️ Upload AHF ZIP", "🔬 PRISM Forensic Lab"])

with tab_query:
    query_input = st.text_area(
        "Enter ORA code, raw log paste, or natural language question",
        height=160,
        placeholder=(
            "Examples:\n"
            "  ORA-27072 on dbhost01\n"
            "  Apr 21 02:44:18 dbhost01 kernel: oracle invoked oom-killer ...\n"
            "  Why does ORA-00257 happen when the archive filesystem is full?"
        ),
    )
    st.caption("Each click **adds a turn** to this incident. PRISM re-runs the full pipeline on **all** turns (merged text + every ZIP in the session).")
    run_btn = st.button("🔍 Diagnose", type="primary", use_container_width=True)

with tab_file:
    uploaded = st.file_uploader(
        "Upload alert.log, /var/log/messages, errpt output, dmesg, iostat...",
        type=["log", "txt", "out", "csv", "trc", "dat", "html", "xml"],
    )
    if uploaded:
        st.success(f"✅ File ready: **{uploaded.name}** ({len(uploaded.getvalue()):,} bytes) — click Diagnose File below.")
    file_btn = st.button("🔍 Diagnose File", type="primary", use_container_width=True)

with tab_zip:
    uploaded_zip = st.file_uploader(
        "Upload AHF ZIP bundle (adrci/ahf/tfactl collection)",
        type=["zip"],
    )
    if uploaded_zip:
        st.success(f"✅ Bundle ready: **{uploaded_zip.name}** ({len(uploaded_zip.getvalue()):,} bytes) — click Analyze Bundle below.")
    zip_btn = st.button("🧠 Analyze Bundle", type="primary", use_container_width=True)

with tab_lab:
    st.markdown("### 🧪 Simulation Sandbox")
    st.markdown('<div style="font-size:12px;color:#64748b;margin-bottom:10px;">Paste logs from multiple layers to simulate a complex Exadata failure.</div>', unsafe_allow_html=True)
    
    col_l1, col_l2 = st.columns(2)
    with col_l1:
        lab_db_log = st.text_area("Database Alert Log", height=150, placeholder="ORA-15130: diskgroup failure...")
        lab_os_log = st.text_area("OS Syslog / dmesg", height=150, placeholder="InfiniBand link is DOWN")
    with col_l2:
        lab_cell_log = st.text_area("Exadata Cell Alert Log", height=150, placeholder="CELLSRV: Cell Server stopped")
        lab_trace_log = st.text_area("Trace File Snippet", height=150, placeholder="Call Stack: kgh_alloc <- ...")
    
    lab_btn = st.button("🔬 Execute Multi-Log Analysis", type="primary", use_container_width=True)

# ── Run diagnosis (Option C: merged session raw + all session ZIPs; full pipeline each run) ──
report = None

platform_val = override_platform if override_platform != "(auto-detect)" else ""

from ui.prism_session import (
    load_prism_limits,
    merge_turns_to_raw,
    turn_append_paste,
    turn_append_file,
    turn_append_zip,
    turn_append_lab,
    collect_zip_paths,
    build_lab_merged_text,
)

mm, mt, mzb, mzf = load_prism_limits(_ROOT_CFG)
_p_cache = _prism_cache_dir()


def _prism_execute_diagnosis(
    turns_list: list,
    *,
    hostname: str | None = None,
    platform: str | None = None,
) -> dict:
    """Run full session diagnosis for current `turns_list` (merged raw + all ZIP paths)."""
    merged = merge_turns_to_raw(turns_list, mm)
    zips = collect_zip_paths(turns_list, _p_cache)
    if not merged.strip() and not zips:
        raise ValueError("Nothing to analyze in this session.")
    hn = override_hostname or "" if hostname is None else hostname
    plat = platform_val if platform is None else platform
    agent = load_agent()
    return agent.diagnose_prism_session(
        merged_text=merged,
        zip_paths=zips,
        hostname=hn,
        platform=plat,
        ora_code=override_ora or "",
        timestamp_str=override_ts or "",
        top_k=top_k,
        session_incident_id=st.session_state["prism_session_id"],
        max_zip_files=mzf,
    )


if run_btn:
    turns0 = list(st.session_state["prism_session_turns"])
    turns1 = turn_append_paste(turns0, query_input, mt)
    if turns1 == turns0:
        st.warning("Paste log text or a question first, then click Diagnose.")
    else:
        st.session_state["prism_session_turns"] = turns1
        with st.spinner("Running full PRISM diagnostic on entire session (merged evidence)..."):
            try:
                report = _prism_execute_diagnosis(turns1)
                merged = merge_turns_to_raw(turns1, mm)
                st.session_state["last_report"] = report
                st.session_state["incident_context_text"] = merged
                _append_incident_history(report)
            except ValueError as e:
                st.warning(str(e))
            except Exception as e:
                st.error(f"Error: {e}")

if lab_btn:
    lab_txt = build_lab_merged_text(lab_db_log, lab_os_log, lab_cell_log, lab_trace_log)
    turns0 = list(st.session_state["prism_session_turns"])
    turns1 = turn_append_lab(turns0, lab_txt, mt)
    if turns1 == turns0:
        st.warning("Enter log text in at least one lab field, then run.")
    else:
        st.session_state["prism_session_turns"] = turns1
        with st.spinner("Running full PRISM diagnostic on entire session (lab + prior turns)..."):
            try:
                report = _prism_execute_diagnosis(
                    turns1,
                    hostname="exadata-lab",
                    platform=platform_val or "EXADATA",
                )
                merged = merge_turns_to_raw(turns1, mm)
                st.session_state["last_report"] = report
                st.session_state["incident_context_text"] = merged
                _append_incident_history(report)
            except ValueError as e:
                st.warning(str(e))
            except Exception as e:
                st.error(f"Lab Simulation Error: {e}")
                st.exception(e)

if file_btn and uploaded:
    fb = uploaded.getvalue()
    text = fb.decode("utf-8", errors="replace")
    turns0 = list(st.session_state["prism_session_turns"])
    turns1 = turn_append_file(turns0, uploaded.name, text, mt)
    st.session_state["prism_session_turns"] = turns1
    with st.spinner(f"Parsing '{uploaded.name}' — full session diagnostic..."):
        try:
            report = _prism_execute_diagnosis(turns1)
            merged = merge_turns_to_raw(turns1, mm)
            st.session_state["last_report"] = report
            st.session_state["incident_context_text"] = merged
            _append_incident_history(report)
        except ValueError as e:
            st.warning(str(e))
        except Exception as e:
            st.error(f"Error: {e}")
            st.exception(e)
elif file_btn and not uploaded:
    st.warning("⚠️ Please upload a log file first, then click Diagnose File.")

if zip_btn and uploaded_zip:
    zb = uploaded_zip.getvalue()
    try:
        turns0 = list(st.session_state["prism_session_turns"])
        turns1 = turn_append_zip(turns0, _p_cache, uploaded_zip.name, zb, mzb)
        st.session_state["prism_session_turns"] = turns1
    except ValueError as e:
        st.error(str(e))
    else:
        merged = merge_turns_to_raw(turns1, mm)
        zips = collect_zip_paths(turns1, _p_cache)
        if not zips:
            st.error("ZIP was not saved to session cache.")
        else:
            with st.spinner(f"Analyzing entire session including '{uploaded_zip.name}'..."):
                try:
                    report = _prism_execute_diagnosis(turns1)
                    merged = merge_turns_to_raw(turns1, mm)
                    st.session_state["last_report"] = report
                    st.session_state["incident_context_text"] = merged
                    _append_zip_bundle_to_incident_context("ZIP_SESSION", uploaded_zip.name, report)
                    _append_incident_history(report)
                except ValueError as e:
                    st.warning(str(e))
                except Exception as e:
                    st.error(f"Bundle analysis error: {e}")
                    st.exception(e)
elif zip_btn and not uploaded_zip:
    st.warning("⚠️ Please upload a ZIP bundle first, then click Analyze Bundle.")

# ── Render report ─────────────────────────────────────────────────
if report is None:
    report = st.session_state.get("last_report")

if report:
    if _ack:
        if isinstance(_ack, dict):
            level = _ack.get("level", "success")
            msg = _ack.get("message", "")
        else:
            level = "success"
            msg = str(_ack)
        if msg:
            if level == "warning":
                st.warning(msg)
            elif level == "error":
                st.error(msg)
            else:
                st.success(msg)

    status = report.get("status", "NO_MATCH")
    conf   = report.get("confidence", {})
    score  = conf.get("score", 0)
    label  = conf.get("label", "NO_MATCH")
    bd     = conf.get("breakdown", {})

    # ── Top metrics row ──────────────────────────────────────────
    st.markdown(
        f'<div class="metric-row">'
        f'<div class="metric-box"><div class="metric-val">{_badge(label)}</div>'
        f'<div class="metric-lbl">Confidence Level</div></div>'
        f'<div class="metric-box"><div class="metric-val" style="color:#1e40af">{score}%</div>'
        f'<div class="metric-lbl">Confidence Score</div></div>'
        f'<div class="metric-box"><div class="metric-val" style="color:#64748b">'
        f'{report.get("platform","")}</div><div class="metric-lbl">Platform</div></div>'
        f'<div class="metric-box"><div class="metric-val" style="color:#64748b">'
        f'{report.get("processing_ms",0):.0f}ms</div><div class="metric-lbl">Processing Time</div></div>'
        f'</div>',
        unsafe_allow_html=True
    )
    ps = report.get("prism_session") or {}
    if ps:
        st.caption(
            f"**Incident session:** `{ps.get('session_incident_id', '')}` · merged text **{ps.get('merged_text_chars', 0)}** chars · "
            f"ZIPs in this run: **{ps.get('zip_files_used', 0)}** · turns in UI session: **{len(st.session_state.get('prism_session_turns', []))}**"
        )
        if ps.get("merged_text_capped"):
            st.warning(
                "Session text cap reached. PRISM keeps processing using pinned high-signal lines and "
                "structured memory (ORA/layer/device/diskgroup) across all turns."
            )
        sm = ps.get("structured_memory") or {}
        sm_oras = sm.get("ora_codes") or []
        sm_layers = sm.get("layers") or []
        if sm_oras or sm_layers:
            st.caption(
                f"Structured memory: ORA signals **{len(sm_oras)}**, layers **{', '.join(sm_layers[:6]) or 'n/a'}**."
            )

    if "prism_append_nonce" not in st.session_state:
        st.session_state["prism_append_nonce"] = 0
    bump_key = f"prism_append_paste_{st.session_state['prism_append_nonce']}"
    st.markdown(
        '<div id="prism-session-composer" style="border:1px solid #e2e8f0;border-radius:10px;padding:14px 18px;background:#ffffff;margin:14px 0 10px 0;box-shadow:0 1px 2px rgba(15,23,42,0.04);">'
        "<span style=\"font-size:15px;font-weight:600;color:#0f172a;\">Add more evidence (same session)</span></div>",
        unsafe_allow_html=True,
    )
    st.caption(
        "Paste **additional** errors or log lines — or **upload a log file / ZIP** below. "
        "You can also use the [main input tabs](#prism-main-input). Each action adds one **turn**; PRISM re-runs on **all** session evidence."
    )
    bump_text = st.text_area(
        "Additional log paste or new error",
        height=120,
        key=bump_key,
        placeholder="Paste new alert / trace / syslog lines, then click “Append & re-diagnose”…",
        label_visibility="visible",
    )
    if st.button("Append & re-diagnose", type="primary", key="prism_append_from_report_btn"):
        if not (bump_text or "").strip():
            st.warning("Paste additional log text first.")
        else:
            turns0 = list(st.session_state["prism_session_turns"])
            turns1 = turn_append_paste(turns0, bump_text, mt)
            if turns1 == turns0:
                st.warning("Nothing new to append.")
            else:
                st.session_state["prism_session_turns"] = turns1
                with st.spinner("Re-running full PRISM diagnosis on entire session…"):
                    try:
                        r = _prism_execute_diagnosis(turns1)
                        merged = merge_turns_to_raw(turns1, mm)
                        st.session_state["last_report"] = r
                        st.session_state["incident_context_text"] = merged
                        _append_incident_history(r)
                        st.session_state["prism_append_nonce"] = int(st.session_state["prism_append_nonce"]) + 1
                        st.rerun()
                    except ValueError as e:
                        st.warning(str(e))
                    except Exception as e:
                        st.error(str(e))

    st.markdown('<div style="margin-top:12px;"></div>', unsafe_allow_html=True)
    fc1, fc2 = st.columns(2)
    with fc1:
        comp_file = st.file_uploader(
            "Upload a single log file (adds one turn)",
            type=["log", "txt", "out", "csv", "trc", "dat", "html", "xml"],
            key="prism_composer_file_up",
        )
        if st.button("Add log file & re-diagnose", type="secondary", use_container_width=True, key="prism_composer_file_btn"):
            if comp_file is None:
                st.warning("Choose a log file first.")
            else:
                fb = comp_file.getvalue()
                text = fb.decode("utf-8", errors="replace")
                turns0 = list(st.session_state["prism_session_turns"])
                turns1 = turn_append_file(turns0, comp_file.name, text, mt)
                st.session_state["prism_session_turns"] = turns1
                with st.spinner("Adding file and re-running full session diagnosis…"):
                    try:
                        r = _prism_execute_diagnosis(turns1)
                        merged = merge_turns_to_raw(turns1, mm)
                        st.session_state["last_report"] = r
                        st.session_state["incident_context_text"] = merged
                        _append_incident_history(r)
                        st.session_state["prism_append_nonce"] = int(st.session_state["prism_append_nonce"]) + 1
                        st.rerun()
                    except ValueError as e:
                        st.warning(str(e))
                    except Exception as e:
                        st.error(str(e))
    with fc2:
        comp_zip = st.file_uploader(
            "Upload an AHF-style ZIP (adds one turn)",
            type=["zip"],
            key="prism_composer_zip_up",
        )
        if st.button("Add ZIP & re-diagnose", type="secondary", use_container_width=True, key="prism_composer_zip_btn"):
            if comp_zip is None:
                st.warning("Choose a ZIP bundle first.")
            else:
                zb = comp_zip.getvalue()
                try:
                    turns0 = list(st.session_state["prism_session_turns"])
                    turns1 = turn_append_zip(turns0, _p_cache, comp_zip.name, zb, mzb)
                    st.session_state["prism_session_turns"] = turns1
                except ValueError as e:
                    st.error(str(e))
                else:
                    zpaths = collect_zip_paths(turns1, _p_cache)
                    if not zpaths:
                        st.error("ZIP could not be saved to session cache.")
                    else:
                        with st.spinner("Adding ZIP and re-running full session diagnosis…"):
                            try:
                                r = _prism_execute_diagnosis(turns1)
                                merged = merge_turns_to_raw(turns1, mm)
                                st.session_state["last_report"] = r
                                st.session_state["incident_context_text"] = merged
                                _append_zip_bundle_to_incident_context("ZIP_SESSION", comp_zip.name, r)
                                _append_incident_history(r)
                                st.session_state["prism_append_nonce"] = int(st.session_state["prism_append_nonce"]) + 1
                                st.rerun()
                            except ValueError as e:
                                st.warning(str(e))
                            except Exception as e:
                                st.error(str(e))

    if status == "NO_MATCH":
        ora = report.get("ora_code", {}) or {}
        if ora.get("code"):
            st.markdown(
                f'<div class="card"><div class="card-title">Known ORA Context</div>'
                f'<div style="font-size:20px;font-weight:700;color:#c2410c">{ora.get("code")}'
                f' <span style="font-size:12px;color:#64748b">({ora.get("layer","UNKNOWN")})</span></div>'
                f'<div style="margin-top:6px;color:#475569">{ora.get("description","")}</div></div>',
                unsafe_allow_html=True
            )
            st.info(
                "This is the general meaning of the ORA code. "
                "Incident root cause is still unconfirmed until correlated DB + OS/infra evidence is provided."
            )
            pfixes = report.get("fixes", []) or []
            if pfixes and pfixes[0].get("commands"):
                with st.expander("📘 Provisional Runbook Guidance (requires more evidence)", expanded=True):
                    first = pfixes[0]
                    for cmd in first.get("commands", []):
                        st.markdown(f"- {cmd}")

        reason = report.get("no_match_reason", "No matching pattern found.")
        raw_in = (report.get("query") or query_input or "").lower()
        if any(x in raw_in for x in ["none found", "health check passed", "completed successfully"]):
            reason = "This looks like an informational health-check log, not an active incident."
        st.warning(f"⚠️ {reason}")
        follow_up = report.get("follow_up_question") or (
            "I could not map this to a known Oracle DB/OS incident pattern. "
            "Please upload related Oracle and host logs from the same window "
            "(alert.log, /var/log/messages, trace, CRS/OSWatcher) so I can correlate."
        )
        st.info(follow_up)
        missing = report.get("missing_evidence") or []
        if missing:
            with st.expander("🧩 Why This Is Not Final Yet", expanded=True):
                st.markdown(
                    "Confidence is below final threshold or evidence is generic. "
                    "Please provide:"
                )
                for item in missing:
                    st.markdown(f"- {item}")

        st.markdown("### More evidence")
        st.info(
            "Use the **Add more evidence** box **above** (same session), or the [main input tabs](#prism-main-input). "
            "Use **Start new incident** in the sidebar only when this case is finished."
        )
    elif status == "PROVISIONAL":
        st.info(
            "Provisional bundle-level decision: strong parser evidence was found, "
            "but final RCA confirmation is pending additional validation."
        )
    else:
        # Layout: 2 columns
        col1, col2 = st.columns([3, 2])

        with col1:
            # ORA Code
            ora = report.get("ora_code", {})
            if ora.get("code"):
                st.markdown(
                    f'<div class="card"><div class="card-title">ORA Code</div>'
                    f'<b style="color:#c2410c;font-size:16px">{ora["code"]}</b>'
                    f'<span style="color:#64748b;font-size:12px"> [{ora.get("layer","")}]</span><br>'
                    f'<span style="font-size:13px">{ora.get("description","")}</span></div>',
                    unsafe_allow_html=True
                )

            # Guided Diagnostic Solicitation
            solicit = report.get("solicitation", [])
            if solicit:
                st.markdown(
                    f'<div class="card" style="border: 1px solid #fdba74; background: rgba(251, 146, 60, 0.08);">'
                    f'<div style="color:#c2410c; font-weight:bold; margin-bottom:8px; font-size:14px;">🧠 Guided Diagnostic</div>'
                    f'<div style="font-size:12px; color:#475569; margin-bottom:10px;">I\'ve detected a potential <b>{report.get("root_cause",{}).get("category","")}</b> layer issue. To confirm the root cause, please upload:</div>',
                    unsafe_allow_html=True
                )
                for s in solicit:
                    st.markdown(f'<div style="font-size:12px; color:#64748b; margin-left:12px;">• <code>{s}</code></div>', unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)

            # Root Cause
            rc = report.get("root_cause", {})
            if rc:
                st.markdown(
                    f'<div class="card"><div class="card-title">Root Cause</div>'
                    f'<b style="color:#b91c1c;font-size:15px">{rc.get("pattern","")}</b>'
                    f'<span style="color:#64748b;font-size:12px"> [{rc.get("category","")} · {rc.get("severity","")}]</span><br>'
                    + (f'<span style="color:#1d4ed8;font-size:12px">Device: {rc["device"]}</span><br>' if rc.get("device") else "")
                    + f'<span style="font-size:13px">{rc.get("description","")}</span></div>',
                    unsafe_allow_html=True
                )

            # Trace Deep Dive (Phase B)
            analysis = report.get("trace_analysis")
            if analysis:
                pinfo = analysis.get("process_info", {})
                pinfo_str = " · ".join([f"<b>{k}:</b> {v}" for k, v in pinfo.items()])
                stack = analysis.get("call_stack", [])
                
                st.markdown(
                    f'<div class="card" style="border-left:3px solid #2563eb;">'
                    f'<div class="card-title">🔬 Trace Deep Dive</div>'
                    f'<div style="font-size:12px;margin-bottom:8px;color:#475569">{pinfo_str}</div>'
                    f'</div>',
                    unsafe_allow_html=True
                )
                if stack:
                    with st.expander("View Call Stack Frames", expanded=True):
                        st.code("\n".join(stack), language="text")

            # Security Correlation (Phase C)
            sec_insights = report.get("security_insights", [])
            if sec_insights:
                st.markdown(
                    f'<div class="card" style="border-left:3px solid #7c3aed;">'
                    f'<div class="card-title">🔒 Security Correlation</div>',
                    unsafe_allow_html=True
                )
                for insight in sec_insights[:3]:
                    color = "#b91c1c" if insight["severity"] in ("CRITICAL", "ERROR") else "#c2410c"
                    st.markdown(
                        f'<div style="font-size:12px;margin-bottom:4px">'
                        f'<span style="color:{color};font-weight:bold">[{insight["event"]}]</span> '
                        f'<span style="color:#64748b">{insight["text"]}</span></div>',
                        unsafe_allow_html=True
                    )
                st.markdown('</div>', unsafe_allow_html=True)

            # Exadata Hardware Health (Phase E)
            hw_health = report.get("hardware_health", [])
            if hw_health:
                st.markdown(
                    f'<div class="card" style="border-left:3px solid #15803d;">'
                    f'<div class="card-title">🛡️ Exadata Hardware Health</div>',
                    unsafe_allow_html=True
                )
                for item in hw_health[:3]:
                    color = "#b91c1c" if item["severity"] in ("CRITICAL", "ERROR") else "#15803d"
                    st.markdown(
                        f'<div style="font-size:12px;margin-bottom:4px">'
                        f'<span style="color:{color};font-weight:bold">[{item["event"]}]</span> '
                        f'<span style="color:#64748b">{item["text"]}</span></div>',
                        unsafe_allow_html=True
                    )
                st.markdown('</div>', unsafe_allow_html=True)

            # Causal chain
            chain = report.get("causal_chain", [])
            if chain:
                st.markdown('<div class="card"><div class="card-title">Causal Chain</div>', unsafe_allow_html=True)
                _render_causal_chain(chain)
                st.markdown('</div>', unsafe_allow_html=True)

            rca = report.get("rca_framework")
            if rca:
                with st.expander("📐 Evidence-first RCA (roles, cascade, correlation)", expanded=False):
                    st.markdown(f"**Executive summary:** {rca.get('executive_summary', '')}")
                    rc = rca.get("root_cause_candidate") or {}
                    if rc:
                        st.markdown(
                            f"**Root candidate:** `{rc.get('root_cause','')}` · "
                            f"layer **{rc.get('layer','')}** · evidence status **{rc.get('status','')}** · "
                            f"RCA correlation score **{rc.get('correlation_score','')}**"
                        )
                        st.caption(rc.get("why_deepest_supported", ""))
                    cmarked = rca.get("cascade_chain_marked") or []
                    if cmarked:
                        st.markdown("**Cascade (marked):**")
                        st.code("\n".join(f"  → {s}" for s in cmarked), language="text")
                    ora_tbl = rca.get("observed_ora_correlation_table") or rca.get("correlated_error_table") or []
                    if ora_tbl:
                        st.markdown("**Observed ORA codes (not LGWR / not patterns):**")
                        st.table(
                            [
                                {
                                    "ORA": r.get("error", ""),
                                    "Role": r.get("role", ""),
                                    "Layer": r.get("layer", ""),
                                    "Meaning": (r.get("meaning", "") or "")[:120],
                                }
                                for r in ora_tbl
                            ]
                        )
                    non_ora = rca.get("non_ora_correlated_events") or []
                    if non_ora:
                        st.markdown("**Non-ORA correlated events / patterns:**")
                        st.caption("These rows are not ORA codes (e.g. LGWR termination, storage signals, regex patterns).")
                        st.table(
                            [
                                {
                                    "Event": r.get("event", ""),
                                    "Role": r.get("role", ""),
                                    "Layer": r.get("layer", ""),
                                    "Meaning": (r.get("meaning", "") or "")[:120],
                                }
                                for r in non_ora
                            ]
                        )
                    evtl = rca.get("evidence_timeline") or []
                    if evtl:
                        st.markdown("**Evidence timeline (extracted):**")
                        st.dataframe(evtl[:25], use_container_width=True, hide_index=True)
                    st.markdown(f"**Correlation confidence note:** {rca.get('confidence_explanation', '')}")
                    rd = rca.get("remediation_direction") or {}
                    if rd:
                        st.markdown("**Remediation direction (by layer):**")
                        for k, v in rd.items():
                            st.markdown(f"- **{k}:** {v}")
                    need = rca.get("additional_evidence_needed") or []
                    if need:
                        st.markdown("**Additional evidence:**")
                        for n in need:
                            st.markdown(f"- {n}")

            # Cascade
            cascade = report.get("cascade")
            if cascade:
                st.markdown(
                    f'<div class="cascade-banner">'
                    f'⚡ <b>CASCADE DETECTED</b> — {cascade["note"]}<br>'
                    f'<span style="font-size:12px;color:#64748b">Sequence: '
                    + " → ".join(f"<code>{s}</code>" for s in cascade.get("sequence",[]))
                    + f'&nbsp;&nbsp;Match: {cascade["match_pct"]}%</span></div>',
                    unsafe_allow_html=True
                )

        with col2:
            # Score breakdown
            st.markdown('<div class="card"><div class="card-title">Score Breakdown</div>', unsafe_allow_html=True)
            conf = report.get("confidence") or {}
            if conf.get("correlation_model_score") is not None:
                st.caption(
                    f"RCA correlation model: **{conf.get('correlation_model_score')}** · "
                    f"Evidence status: **{conf.get('root_cause_evidence_status', 'N/A')}** "
                    f"(separate from retrieval fusion below)."
                )
            if conf.get("retrieval_note"):
                st.caption(conf["retrieval_note"])
            for component, val in bd.items():
                weight_lbl = {"keyword":"Keyword (40%)","bm25":"BM25 (30%)","dense":"Semantic (20%)","temporal":"Temporal (10%)"}.get(component, component)
                st.progress(int(val) if val <= 40 else 40, text=f"{weight_lbl}: {val}")
            st.markdown("</div>", unsafe_allow_html=True)

            # Related errors
            related = report.get("related_errors", [])
            if related:
                st.markdown(
                    '<div class="card"><div class="card-title">Related ORA Codes</div>'
                    + " ".join(f'<code style="background:#e2e8f0;color:#334155;border:1px solid #cbd5e1;padding:2px 6px;border-radius:4px">{r}</code>' for r in related)
                    + "</div>",
                    unsafe_allow_html=True
                )

            # Hostname/Platform
            st.markdown(
                f'<div class="card"><div class="card-title">Context</div>'
                f'Host: <b>{report.get("hostname","unknown")}</b><br>'
                f'Platform: <b>{report.get("platform","")}</b><br>'
                f'Query mode: <b>{report.get("query_mode","")}</b></div>',
                unsafe_allow_html=True
            )

        # ── Fixes ────────────────────────────────────────────────
        fixes = report.get("fixes", [])
        if fixes:
            st.markdown("### 🔧 Remediation commands")
            st.caption("Prefer diagnostics and layered direction until root is confirmed. Check [command_category] on each bundle.")
            for i, fix in enumerate(fixes):
                _render_fix(fix, i)

        # ── Diagnostics ──────────────────────────────────────────
        diags = report.get("diagnostics", [])
        if diags:
            with st.expander("🔎 Diagnostic Commands (run to confirm)", expanded=False):
                for cmd in diags:
                    st.code(cmd, language="bash")

        # ── Phase D: Incident Package ────────────────────────────
        pkg = report.get("package_info")
        if pkg:
            st.markdown("---")
            col_p1, col_p2 = st.columns([0.7, 0.3])
            with col_p1:
                st.markdown(
                    f"### 📦 Incident Evidence Package\n"
                    f"A diagnostic bundle containing trace files and automated findings has been generated.\n\n"
                    f"**File:** `{pkg['filename']}` ({pkg['size_mb']} MB)"
                )
            with col_p2:
                try:
                    with open(pkg["path"], "rb") as f:
                        st.download_button(
                            label="Download ZIP",
                            data=f,
                            file_name=pkg["filename"],
                            mime="application/zip",
                            use_container_width=True
                        )
                except Exception as e:
                    st.error(f"Failed to read package: {e}")

        # ── Evidence ─────────────────────────────────────────────
        evidence = report.get("evidence", [])
        if evidence:
            with st.expander(f"📄 Evidence ({len(evidence)} chunks)", expanded=False):
                for ev in evidence:
                    st.markdown(
                        f'<div class="card" style="margin-bottom:8px">'
                        f'<b style="color:#1e40af">{ev.get("log_source","")}</b>'
                        f'&nbsp;·&nbsp;{ev.get("timestamp","")}'
                        f'&nbsp;·&nbsp;<span style="color:#64748b">{ev.get("hostname","")}</span>'
                        f'&nbsp;·&nbsp;score={ev.get("rrf_score",0)}<br>'
                        f'<div class="evidence-box">{ev.get("raw_text","")}</div></div>',
                        unsafe_allow_html=True
                    )

        # ── JSON view ────────────────────────────────────────────
        with st.expander("🗂 Raw JSON Report", expanded=False):
            st.json(report)

    bundle = report.get("bundle_summary")
    if bundle:
        st.markdown("---")
        st.markdown(
            f"**Bundle analysis:** {bundle.get('analyzed_files', 0)} files scanned"
            + (f" · primary: `{bundle.get('primary_file')}`" if bundle.get("primary_file") else "")
            + (f" · platform: `{bundle.get('platform_inferred')}`" if bundle.get("platform_inferred") else "")
        )
        extra_parts = []
        if bundle.get("total_extracted_files") is not None:
            extra_parts.append(f"extracted: **{bundle.get('total_extracted_files')}**")
        if bundle.get("candidate_files_found") is not None:
            extra_parts.append(f"candidate logs: **{bundle.get('candidate_files_found')}**")
        if bundle.get("max_files_cap") is not None:
            extra_parts.append(f"cap: **{bundle.get('max_files_cap')}**")
        if extra_parts:
            st.caption(" · ".join(extra_parts))
        state_counts = bundle.get("file_state_counts") or {}
        if state_counts:
            st.markdown(
                f"**File states:** MATCH `{state_counts.get('MATCH', 0)}` · "
                f"SIGNAL_ONLY `{state_counts.get('SIGNAL_ONLY', 0)}` · "
                f"NO_MATCH `{state_counts.get('NO_MATCH', 0)}`"
            )

    zip_diags = report.get("zip_ingest_diagnostics") or {}
    zip_events = report.get("zip_normalized_events") or []
    if zip_diags or zip_events:
        parsed_files = zip_diags.get("parsed_files") or []
        skipped_extract = zip_diags.get("skipped_from_extract") or []
        skipped_runtime = zip_diags.get("skipped") or []
        st.markdown(
            f"**ZIP coverage:** parsed `{len(parsed_files)}` files · "
            f"skipped at extract `{len(skipped_extract)}` · skipped at parse `{len(skipped_runtime)}` · "
            f"normalized events `{len(zip_events)}`"
        )
        if skipped_extract or skipped_runtime:
            with st.expander("⚠️ Skipped Files and Reasons", expanded=False):
                if skipped_extract:
                    st.markdown("**Skipped during extract**")
                    st.json(skipped_extract[:50])
                if skipped_runtime:
                    st.markdown("**Skipped during parse**")
                    st.json(skipped_runtime[:50])
        if zip_events:
            layers = Counter((e.get("layer") or "UNKNOWN") for e in zip_events)
            top_codes = Counter((e.get("code") or "NA") for e in zip_events).most_common(12)
            with st.expander("🧾 ZIP Evidence Summary", expanded=False):
                st.markdown(f"**Layers:** `{dict(layers)}`")
                st.markdown(f"**Top codes:** `{top_codes}`")
    secondary = report.get("secondary_findings", [])
    if secondary:
        with st.expander("📚 Other Findings From Bundle", expanded=False):
            match_rows = [r for r in secondary if r.get("match_state") == "MATCH"]
            signal_rows = [r for r in secondary if r.get("match_state") == "SIGNAL_ONLY"]
            no_rows = [r for r in secondary if r.get("match_state") == "NO_MATCH"]
            st.markdown(
                f"**Rows shown:** `{len(secondary)}` · MATCH `{len(match_rows)}` · "
                f"SIGNAL_ONLY `{len(signal_rows)}` · NO_MATCH `{len(no_rows)}`"
            )
            kb_hits_total = sum(int(r.get("kb_hit_count") or 0) for r in secondary)
            kb_ora_total = sum(len(r.get("kb_ora_hits") or []) for r in secondary)
            st.caption(
                f"KB hits across shown rows: {kb_hits_total} "
                f"(including PDF/graph ORA hits: {kb_ora_total})"
            )
            st.json(secondary)

    prism = report.get("prism")
    if prism:
        with st.expander("🧭 PRISM Incident View", expanded=True):
            st.markdown(f"**Signal:** {prism.get('signal', 'N/A')}")
            st.markdown(f"**Correlation:** {prism.get('correlation', 'N/A')}")
            st.markdown(f"**Root Cause:** {prism.get('root_cause', 'N/A')}")
            st.markdown(f"**Action Plan:** {prism.get('action_plan', 'N/A')}")
            st.markdown(f"**Confidence:** {prism.get('confidence', 'N/A')}")

    llm_adv = report.get("llm_advisory") or {}
    if llm_adv:
        with st.expander("🤖 LLM Advisory (Constrained)", expanded=False):
            st.markdown(f"**Used:** `{llm_adv.get('used', False)}` · **Mode:** `{llm_adv.get('mode', 'off')}`")
            if llm_adv.get("model"):
                st.markdown(f"**Model:** `{llm_adv.get('model')}`")
            if llm_adv.get("reason"):
                st.caption(f"Reason: {llm_adv.get('reason')}")
            if llm_adv.get("selected_hypothesis"):
                st.markdown(f"**Selected hypothesis:** `{llm_adv.get('selected_hypothesis')}`")
            if llm_adv.get("confidence_band"):
                st.markdown(f"**Confidence band:** `{llm_adv.get('confidence_band')}`")
            if llm_adv.get("rationale"):
                st.markdown(f"**Rationale:** {llm_adv.get('rationale')}")
            if "policy_passed" in llm_adv:
                st.markdown(f"**Policy passed:** `{llm_adv.get('policy_passed')}`")
            if llm_adv.get("violations"):
                st.warning(f"Policy violations: {llm_adv.get('violations')}")
            next_cmds = llm_adv.get("next_commands") or []
            if next_cmds:
                st.markdown("**Suggested next commands (advisory):**")
                for cmd in next_cmds:
                    st.code(cmd, language="bash")
            need_more = llm_adv.get("needs_more_evidence") or []
            if need_more:
                st.markdown("**Suggested additional evidence:**")
                for item in need_more:
                    st.markdown(f"- {item}")

    st.markdown("---")
    st.markdown(
        '<p style="font-size:13px;color:#64748b;">'
        'Need to paste more? Jump to <a href="#prism-session-composer" style="color:#1d4ed8;">Add more evidence</a> '
        '(under the summary) or <a href="#prism-main-input" style="color:#1d4ed8;">main input tabs</a> at the top.</p>',
        unsafe_allow_html=True,
    )

    if st.session_state["incident_history"]:
        with st.expander("🗂 Incident Session Memory", expanded=False):
            st.json(st.session_state["incident_history"][-10:])
