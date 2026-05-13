"""
main.py — FastAPI REST API for PRISM (evidence-first Oracle diagnostics).

Endpoints:
  POST /diagnose          — main diagnostic endpoint
  GET  /health            — service health check
  GET  /stats             — index statistics
  POST /diagnose/file     — upload a log file for diagnosis
  POST /diagnose/zip      — upload an AHF/TFA-style ZIP bundle
"""

from __future__ import annotations
import os
import tempfile
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException, UploadFile, File, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "settings.yaml"

try:
    with open(CONFIG_PATH, "r", encoding="utf-8") as _f:
        _cfg: dict[str, Any] = yaml.safe_load(_f) or {}
except Exception:
    _cfg = {}
_MODEL_NAME = (_cfg.get("embedding") or {}).get("model_name", "unknown")


def _safe_bm25_index_size() -> int | None:
    try:
        from src.retrieval.bm25_search import index_size

        return int(index_size())
    except Exception:
        return None


def _safe_qdrant_count() -> int | None:
    try:
        from src.vectordb.qdrant_client import count_chunks

        return int(count_chunks())
    except Exception:
        return None


from src.agent.agent import get_agent

# ── App init ────────────────────────────────────────────────────
app = FastAPI(
    title="PRISM",
    description=(
        "PRISM — evidence-first Oracle diagnostics: normalized logs → event correlation → report. "
        "Optional LLM advisory is off unless enabled in config."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Pydantic models (request bodies only; responses return full report dicts) ──


class DiagnoseRequest(BaseModel):
    query: str = Field(
        ...,
        description="ORA code, raw log paste, or natural language question",
        example="ORA-27072 on dbhost01",
    )
    ora_code: Optional[str] = Field(None, example="ORA-27072")
    hostname: Optional[str] = Field(None, example="dbhost01")
    timestamp_str: Optional[str] = Field(None, example="2024-03-07T02:44:18")
    platform: Optional[str] = Field(
        None,
        description="LINUX | AIX | SOLARIS | WINDOWS | EXADATA | OCI",
        example="LINUX",
    )
    top_k: Optional[int] = Field(None, ge=1, le=50)


@app.on_event("startup")
async def startup_event():
    """Initialize agent (BM25 load is best-effort inside agent.initialize)."""
    get_agent()


@app.get("/health", tags=["System"])
async def health():
    """Service health check (retrieval backends optional)."""
    bm25_n = _safe_bm25_index_size()
    chunks = _safe_qdrant_count()
    degraded = bm25_n is None or chunks is None
    return {
        "status": "degraded" if degraded else "healthy",
        "qdrant_chunks": chunks,
        "bm25_index_size": bm25_n,
        "model": _MODEL_NAME,
        "llm_used": False,
        "temperature": 0.0,
    }


@app.get("/stats", tags=["System"])
async def stats():
    """Return index statistics when optional backends are available."""
    from src.knowledge_graph.pattern_matcher import _compile_patterns

    bm25_n = _safe_bm25_index_size()
    chunks = _safe_qdrant_count()
    try:
        n_pat = len(_compile_patterns())
    except Exception:
        n_pat = 0
    return {
        "qdrant_collection": chunks,
        "bm25_index": bm25_n,
        "patterns_loaded": n_pat,
        "graph_nodes": "loaded",
    }


@app.post("/diagnose", response_model=None, tags=["Diagnostic"])
async def diagnose(req: DiagnoseRequest) -> dict[str, Any]:
    """
    Run full diagnostic pipeline against a query.

    Returns the full internal report dict (including ``rca_framework``, normalized counts, etc.).
    """
    agent = get_agent()
    try:
        return agent.diagnose(
            query=req.query,
            ora_code=req.ora_code or "",
            hostname=req.hostname or "",
            timestamp_str=req.timestamp_str or "",
            platform=req.platform or "",
            top_k=req.top_k,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/diagnose/text", tags=["Diagnostic"])
async def diagnose_text(
    query: str = Query(..., description="ORA code or log text"),
    hostname: str = Query("", description="Hostname filter"),
    platform: str = Query("", description="Platform filter"),
):
    """GET-friendly diagnostic endpoint for simple queries."""
    agent = get_agent()
    report = agent.diagnose(query=query, hostname=hostname, platform=platform)
    from src.agent.report_builder import format_report_text

    return {
        "report": report,
        "text_format": format_report_text(report),
    }


@app.post("/diagnose/file", tags=["Diagnostic"])
async def diagnose_file(
    file: UploadFile = File(..., description="Log file (alert.log, messages, errpt output)"),
    hostname: str = Query("", description="Override hostname"),
    platform: str = Query("", description="Override platform: LINUX|AIX|SOLARIS|WINDOWS|EXADATA"),
):
    """
    Upload a log file for diagnosis.
    Auto-detects log type and platform from filename and content.
    """
    suffix = os.path.splitext(file.filename)[1] if file.filename else ".log"
    with tempfile.NamedTemporaryFile(mode="wb", suffix=suffix, delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        agent = get_agent()
        return agent.diagnose_log_file(
            filepath=tmp_path,
            hostname=hostname,
            platform=platform,
            original_filename=file.filename or "",
        )
    finally:
        os.unlink(tmp_path)


@app.post("/diagnose/zip", response_model=None, tags=["Diagnostic"])
async def diagnose_zip(
    file: UploadFile = File(..., description="AHF/TFA-style diagnostic ZIP bundle"),
    hostname: str = Query("", description="Override hostname"),
    platform: str = Query("", description="Override platform: LINUX|EXADATA|..."),
    max_files: int = Query(120, ge=1, le=200, description="Max member files to parse from the archive"),
):
    """Upload a ZIP bundle; runs bundle-level normalized extraction and correlation."""
    suffix = ".zip"
    if file.filename and file.filename.lower().endswith(".zip"):
        suffix = ".zip"
    with tempfile.NamedTemporaryFile(mode="wb", suffix=suffix, delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        agent = get_agent()
        return agent.diagnose_ahf_zip(
            zip_path=tmp_path,
            hostname=hostname,
            platform=platform,
            max_files=max_files,
        )
    finally:
        os.unlink(tmp_path)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=False)
