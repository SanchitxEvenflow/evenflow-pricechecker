"""Self-check for resume-after-crash row splitting. Run: python test_resume.py"""

from utils.google_sheets import GoogleSheetsClient

HEADER = ["ASIN", "Price", "Rating", "Rating Count", "Rating Breakdown", "Parent Node",
          "Parent Node Rank", "Child Node", "Child Node Rank", "Status", "Checked At"]


class _FakeSheets:
    """Stands in for the Google Sheets values().get() chain."""

    def __init__(self, values):
        self._values = values

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, spreadsheetId, range):
        return self

    def execute(self, num_retries=0):
        return {"values": self._values}


def _split(values):
    client = GoogleSheetsClient.__new__(GoogleSheetsClient)
    client.service = _FakeSheets(values)
    return client.get_pending_rows("sheet", "Run_2026-07-30_00-20")


def demo():
    # Mirrors the 2026-07-30 crash: some rows written, the rest bare ASINs.
    pending, filled = _split([
        HEADER,
        ["B0F19FT161", "1629.00", "3.4", "228", "5*:38%", "Outdoor Living", "804",
         "Garden Hoses", "7", "available", "2026-07-30T01:39:38+05:30"],
        ["B08VNKXBDW"],
        ["B08H8R5K8W", "", "", ""],           # trailing blanks are not progress
        ["  B07KDHSW47  "],                   # whitespace-padded ASIN
        [""],                                 # blank row, ignored entirely
        ["B0GJ4724L4"],
    ])

    # Rows are 1-indexed with the header at row 1.
    assert [r["row"] for r in pending] == [3, 4, 5, 7], pending
    assert [r["asin"] for r in pending] == ["B08VNKXBDW", "B08H8R5K8W", "B07KDHSW47", "B0GJ4724L4"], pending

    assert len(filled) == 1, filled
    # [asin] + 10 value columns — same shape the scrape loop appends to Historical.
    assert len(filled[0]) == 11, filled[0]
    assert filled[0][0] == "B0F19FT161"
    assert filled[0][-1] == "2026-07-30T01:39:38+05:30"

    # A short filled row still pads out to 10 value columns.
    _, short = _split([HEADER, ["B01ABCDEFG", "999.00"]])
    assert short == [["B01ABCDEFG", "999.00"] + [""] * 9], short

    # A fully finished tab has nothing left to do.
    done_pending, done_filled = _split([HEADER, ["B0F19FT161"] + ["x"] * 10])
    assert done_pending == [], done_pending
    assert len(done_filled) == 1

    # Header-only tab (crash right after create_tab).
    assert _split([HEADER]) == ([], [])

    print("ok")


if __name__ == "__main__":
    demo()
