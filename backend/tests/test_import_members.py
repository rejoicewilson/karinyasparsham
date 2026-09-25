from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.import_members import parse_phone_overrides, table_records, table_rows


def test_numbered_member_table_preserves_source_order():
    source = (
        "| No. | Taluk | ARD No. | Name | Phone No. |\n"
        "| --: | --- | ---: | --- | --- |\n"
        "| 1 | KANNUR | 2366009 | SAREENA SUDEEPAN | 9895645189 |\n"
        "| 2 | KANNUR | 2366009 | SUDEEPAN M K | 7025507813 |\n"
    )
    with patch.object(Path, "read_text", return_value=source):
        rows = table_rows(Path("members.md"))
    assert rows == [
        ("KANNUR", "2366009", "SAREENA SUDEEPAN", "9895645189"),
        ("KANNUR", "2366009", "SUDEEPAN M K", "7025507813"),
    ]


def test_numbered_member_table_rejects_missing_sequence():
    source = "| 1 | KANNUR | 2366009 | First | 9895645189 |\n| 3 | KANNUR | 2366010 | Third | 7025507813 |\n"
    with patch.object(Path, "read_text", return_value=source):
        with pytest.raises(SystemExit, match="consecutive"):
            table_rows(Path("members.md"))


def test_numbered_member_table_exposes_source_numbers():
    source = "| 1 | TIRUR | 2054009 | First | 9895645189 |\n| 2 | TIRUR | 2054010 | Second | 7025507813 |\n"
    with patch.object(Path, "read_text", return_value=source):
        records = table_records(Path("members.md"))
    assert [record["source_number"] for record in records] == [1, 2]


def test_parse_phone_overrides():
    assert parse_phone_overrides(["29=9745094702", "44=9846556298"]) == {
        29: "9745094702",
        44: "9846556298",
    }


@pytest.mark.parametrize("value", ["29", "row=9745094702", "29=123"])
def test_parse_phone_overrides_rejects_invalid_values(value):
    with pytest.raises(SystemExit):
        parse_phone_overrides([value])
