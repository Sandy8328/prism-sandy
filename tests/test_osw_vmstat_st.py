"""OSWatcher vmstat rows with optional steal (`st`) column."""

from src.parsers.osw_parser import parse_osw_text


def test_vmstat_row_with_st_column():
    text = (
        "zzz ***Mon Mar 16 07:30:12 IST 2024\n"
        " r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st\n"
        " 2  0      0 1234567  12345 789012    0    0     1     2  123  456  5  2 93  0  0\n"
    )
    r = parse_osw_text(text)
    assert not r.get("parse_error")
    assert r.get("sample_count", 0) >= 1
