"""iostat -x with rareq-sz / wareq-sz / svctm columns before %util."""

from src.parsers.iostat_parser import parse_iostat_text


def test_iostat_modern_with_extra_columns_before_util():
    text = """
Device r/s w/s rkB/s wkB/s rrqm/s wrqm/s %rrqm %wrqm r_await w_await aqu-sz rareq-sz wareq-sz svctm %util
sda 10.00 2.00 40.00 8.00 0.00 0.00 0.00 0.00 5.00 10.00 1.50 8.00 9.00 0.50 96.00
""".strip()
    rows = parse_iostat_text(text)
    assert len(rows) == 1
    assert rows[0]["device"] == "sda"
    assert rows[0]["util_pct"] == 96.0
