# PRISM - Evidence-First Oracle DBA Diagnostics

PRISM is an Oracle incident diagnostics tool for DBAs.

It analyzes pasted logs, uploaded log files, and AHF/TFA-style ZIP bundles, then builds an evidence-first diagnosis across DB + OS + storage signals.

## What This Project Does

- Correlates Oracle and OS/storage evidence into a structured root-cause view.
- Separates observed ORA codes from non-ORA signals (patterns/events).
- Supports session-based iterative diagnosis (add evidence, re-run same incident).
- Resolves ORA meanings from Oracle PDF extract with safe fallback behavior.
- Provides:
  - Streamlit UI (`ui/app.py`)
  - FastAPI service (`api/main.py`)

## Requirements

- Python 3.11 / 3.12 / 3.13 recommended
- `pip`
- (Optional) Gemini API key for advisory LLM output

> Note: `requirements.txt` explicitly warns that Python 3.14 is not recommended for grpc-related compatibility.

## Installation

From project root:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Run Streamlit UI

```bash
streamlit run ui/app.py --server.port 8501
```

Then open: `http://localhost:8501`

## Run FastAPI Service (Optional)

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

API docs:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## How To Use (UI)

1. Paste incident logs in the main input area **or** upload file/ZIP.
2. Run diagnosis.
3. Use **Add more evidence (same session)** repeatedly until satisfied.
4. PRISM re-runs diagnosis on full session evidence (with structured memory + pinned signals when caps are reached).
5. Use **Start new incident** only when closing current case.

## Configuration

Main config file: `config/settings.yaml`

Common sections:

- `prism_session`: turn/session/zip limits
- `zip_evidence`: nested `.zip`, `.tar`, `.tar.gz`, `.tar.xz` expansion and per-member size limits (large sosreport bundles)
- `llm`: advisory model settings
- `ora_meanings`: JSON path for ORA meaning lookup
- `retrieval`, `scoring`, `thresholds`: correlation/retrieval behavior

## ORA Meaning Data

PRISM can build ORA meaning mappings from Oracle PDF:

```bash
python scripts/build_ora_meanings_from_pdf.py
```

Input PDF (default): `data/runbooks/database-error-messages.pdf`  
Output JSON (default): `data/runbooks/ora_meanings.json`

## Run Tests

```bash
pytest tests -q
```

## Optional LLM Setup

Set Gemini key only if you want advisory/model-assisted parts:

```bash
export GEMINI_API_KEY="your_key_here"
```

Current project logic uses low-temperature settings (0.1) for stable outputs where enabled.

## Project Structure (High Level)

- `ui/` - Streamlit app and session helpers
- `api/` - FastAPI endpoints
- `src/agent/` - core orchestration, correlation, reporting
- `src/parsers/` - log parsers/normalizers
- `data/runbooks/` - PDF and generated ORA meaning JSON
- `tests/` - regression and unit tests

## Git Push Checklist

Before pushing:

1. `pytest tests -q`
2. Confirm Streamlit app starts: `streamlit run ui/app.py --server.port 8501`
3. Review changed files:

```bash
git status
```

