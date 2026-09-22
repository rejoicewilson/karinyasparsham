from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.import_members import table_rows


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
