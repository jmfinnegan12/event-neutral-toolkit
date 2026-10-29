"""Reading exchange responses. The fixtures copy each exchange's field layout with made-up values."""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import eventneutral as en  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class Kalshi(unittest.TestCase):
    def test_book_turns_bids_into_asks_for_each_side(self):
        with mock.patch.object(en, "get", return_value=fixture("kalshi_orderbook.json")):
            book = en.kalshi_book("KXTEST-26DEC31-T50")
        self.assertEqual(book["yes"], [(0.25, 30.0)])  # the 0.70 No bid has no size
        self.assertEqual(book["no"], [(0.8, 100.0), (0.82, 50.0)])

    def test_row_treats_empty_sides_as_no_quote(self):
        row = en.kalshi_row(fixture("kalshi_market.json")["market"])
        self.assertIsNone(row["bid"])  # Kalshi sends 0 for no bid
        self.assertIsNone(row["ask"])  # and 1 for no ask
        self.assertEqual(row["volume"], 1250.0)
        self.assertEqual(row["title"], "Test snowfall: Above 50 inches")


class Polymarket(unittest.TestCase):
    def test_book_is_sorted_best_first(self):
        with mock.patch.object(en, "get", return_value=fixture("polymarket_book.json")):
            book = en.pm_book("123")
        self.assertEqual(book["asks"], [(0.46, 500.0), (0.5, 200.0)])
        self.assertEqual(book["bids"], [(0.45, 300.0), (0.4, 100.0)])

    def test_tokens_and_outcomes_come_from_json_strings(self):
        tokens, outcomes = en.pm_tokens(fixture("polymarket_market.json"))
        self.assertEqual(tokens, {"yes": "111", "no": "222"})
        self.assertEqual(outcomes, ["Yes", "No"])


if __name__ == "__main__":
    unittest.main()
