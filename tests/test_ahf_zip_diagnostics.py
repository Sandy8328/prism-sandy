import os
import tempfile
import zipfile

from src.agent.agent import OracleDiagnosticAgent


def _mk_zip(path: str) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("a/alert.log", "ORA-27072: File I/O error\n")
        zf.writestr("a/messages", "Mar 16 07:30:12 host kernel: blk_update_request: I/O error\n")
        zf.writestr("a/report.html", "<html><body>ORA-00353</body></html>")
        zf.writestr("a/core_1.bin", b"\x00\x01\x02\x03")


def test_diagnose_ahf_zip_includes_zip_diagnostics_on_non_success():
    td = tempfile.mkdtemp()
    try:
        zpath = os.path.join(td, "bundle.zip")
        _mk_zip(zpath)

        agent = OracleDiagnosticAgent()
        agent.initialize = lambda: None
        agent.diagnose_log_file = lambda **kwargs: {
            "status": "NO_MATCH",
            "confidence": {"score": 0, "label": "NO_MATCH", "breakdown": {}},
        }

        report = agent.diagnose_ahf_zip(zpath, max_files=50)
        assert report.get("status") in {"NO_MATCH", "PROVISIONAL"}
        assert "zip_normalized_events" in report
        assert "zip_ingest_diagnostics" in report
        assert isinstance(report.get("zip_normalized_events"), list)
        di = report.get("zip_ingest_diagnostics") or {}
        assert "parsed_files" in di and "skipped" in di
        bs = report.get("bundle_summary") or {}
        assert bs.get("total_extracted_files", 0) >= 1
        assert "llm_advisory" in report
        sf = report.get("secondary_findings") or []
        if sf:
            assert "kb_pattern_hits" in sf[0]
            assert "kb_ora_hits" in sf[0]
            assert "kb_all_hits" in sf[0]
            assert "kb_hit_count" in sf[0]
    finally:
        for root, _, files in os.walk(td, topdown=False):
            for f in files:
                os.unlink(os.path.join(root, f))
            os.rmdir(root)
