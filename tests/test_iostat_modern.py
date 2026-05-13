"""Modern iostat -x layout (r_await / w_await / aqu-sz / %util, no svctm)."""

from src.parsers.iostat_parser import parse_iostat_text


def test_modern_iostat_extended_columns():
    text = """
Device            r/s     w/s     rkB/s     wkB/s   rrqm/s   wrqm/s  %rrqm  %wrqm r_await w_await aqu-sz %util
sda               10.00    2.00     40.00      8.00     0.00     0.00    0.00    0.00    5.00   10.00    1.50   96.00
""".strip()
    rows = parse_iostat_text(text)
    assert len(rows) == 1
    assert rows[0]["device"] == "sda"
    assert rows[0]["util_pct"] == 96.0
    assert rows[0]["r_await"] == 5.0
    assert rows[0]["w_await"] == 10.0
