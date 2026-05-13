"""Unit tests for structured PRISM session memory extraction."""

from src.agent.agent import _collect_structured_session_memory


def test_collect_structured_session_memory_picks_codes_layers_and_devices():
    events = [
        {
            "code": "ORA-27072",
            "code_type": "ORA",
            "layer": "DB",
            "hostname": "db01",
            "device": "/dev/sdb",
            "diskgroup": "DATA",
            "pattern_id": "SCSI_DISK_TIMEOUT",
        },
        {
            "code": "FLASH_IO_TIMEOUT",
            "code_type": "PATTERN",
            "layer": "STORAGE",
            "host": "cell01",
            "raw": "Errors include ORA-00353: log corruption near block",
            "pattern_id": "EXA_FLASH_FAIL",
        },
    ]
    mem = _collect_structured_session_memory(events)
    assert "ORA-27072" in mem["ora_codes"]
    assert "ORA-00353" in mem["ora_codes"]
    assert "DB" in mem["layers"] and "STORAGE" in mem["layers"]
    assert "/dev/sdb" in mem["devices"]
    assert "DATA" in mem["diskgroups"]
    assert "db01" in mem["hosts"] and "cell01" in mem["hosts"]

