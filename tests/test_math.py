"""Order-book, fee, hedge and range math, checked against numbers worked out by hand."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import eventneutral as en  # noqa: E402

ASKS = [(0.20, 100.0), (0.25, 200.0)]


class BookWalk(unittest.TestCase):
    def test_walk_takes_the_cheapest_levels_first(self):
        self.assertEqual(en.walk(ASKS, 150), [(0.20, 100.0), (0.25, 50.0)])

    def test_average_and_last_price(self):
        r = en.fill_summary(ASKS, 150, 0.0, "polymarket")
        self.assertAlmostEqual(r["cost"], 32.50)  # 100 x 0.20 + 50 x 0.25
        self.assertAlmostEqual(r["average_price"], 32.50 / 150)
        self.assertEqual(r["last_price"], 0.25)

    def test_thin_book_fills_only_what_is_on_offer(self):
        r = en.fill_summary(ASKS, 1000, 0.0, "polymarket")
        self.assertEqual(r["filled"], 300)
        self.assertEqual(r["on_offer"], 300)


class Fees(unittest.TestCase):
    # 0.07 x 100 x 0.20 x 0.80 = 1.12 and 0.07 x 50 x 0.25 x 0.75 = 0.65625
    def test_kalshi_rounds_the_fee_up_to_the_cent(self):
        self.assertEqual(en.fill_summary(ASKS, 150, 0.07, "kalshi")["fee"], 1.78)
        # 0.07 x 10 x 0.20 x 0.80 = 0.112, which rounds up to 0.12, not to the nearest cent
        self.assertEqual(en.fill_summary([(0.20, 10.0)], 10, 0.07, "kalshi")["fee"], 0.12)

    # 0.05 x 100 x 0.20 x 0.80 = 0.80 and 0.05 x 50 x 0.25 x 0.75 = 0.46875
    def test_polymarket_fee_is_not_rounded(self):
        self.assertAlmostEqual(en.fill_summary(ASKS, 150, 0.05, "polymarket")["fee"], 1.26875)


class Hedge(unittest.TestCase):
    def test_full_cover_costs_the_same_whatever_happens(self):
        r = en.hedge(10_000, 1.0, [], 0.0, "polymarket", price=0.30)
        self.assertEqual(r["wanted"], 10_000)
        self.assertAlmostEqual(r["total_cost"], 3_000)
        self.assertAlmostEqual(r["if_event"], -3_000)  # -10,000 loss + 10,000 payout - 3,000 cost
        self.assertAlmostEqual(r["if_not"], -3_000)

    def test_half_cover(self):
        r = en.hedge(10_000, 0.5, [], 0.0, "polymarket", price=0.30)
        self.assertEqual(r["wanted"], 5_000)
        self.assertAlmostEqual(r["if_event"], -6_500)  # -10,000 + 5,000 - 1,500
        self.assertAlmostEqual(r["if_not"], -1_500)

    def test_thin_book_covers_less(self):
        r = en.hedge(5_000, 1.0, [(0.40, 1_000.0)], 0.0, "kalshi")
        self.assertEqual(r["covered"], 1_000)
        self.assertAlmostEqual(r["if_event"], -4_400)  # -5,000 + 1,000 - 400


def quoted(bid, ask, **extra):
    return {"title": extra.pop("title", ""), "bid": bid, "ask": ask, "last": None, **extra}


class Ranges(unittest.TestCase):
    def test_above_ladder_is_differenced_into_ranges(self):
        ladder = [quoted(0.79, 0.81, strike_type="greater", floor_strike=50),
                  quoted(0.29, 0.31, strike_type="greater", floor_strike=60)]
        got = {r["outcome"]: round(r["probability"], 6) for r in en.ranges(ladder)}
        self.assertEqual(got, {"50 or less": 0.2, "50 to 60": 0.5, "above 60": 0.3})

    def test_multi_outcome_prices_are_scaled_to_sum_to_one(self):
        outcomes = [quoted(0.29, 0.31, title="A"), quoted(0.29, 0.31, title="B"), quoted(0.59, 0.61, title="C")]
        got = [round(r["probability"], 6) for r in en.ranges(outcomes)]
        self.assertEqual(got, [0.25, 0.25, 0.5])

    def test_wide_or_one_sided_quotes_are_left_out(self):
        markets = [quoted(0.10, 0.50, title="wide"), quoted(None, 0.40, title="one-sided"), quoted(0.29, 0.31, title="ok")]
        self.assertEqual(en.ranges(markets), [])


class Text(unittest.TestCase):
    def test_terms_match_from_the_start_of_a_word(self):
        self.assertEqual(en.matches(["snow"], "Seasonal snowfall at Stowe"), 1)
        self.assertEqual(en.matches(["rain"], "Ukraine ceasefire"), 0)

    def test_rule_flags_find_tie_wording(self):
        flags = en.rule_flags("If the game ends in a tie, the market resolves to No.")
        self.assertEqual([f["flag"] for f in flags], ["tie"])
        self.assertEqual(en.rule_flags("Resolves Yes if it snows."), [])

    def test_ids_need_a_venue(self):
        self.assertEqual(en.parse_id("kalshi:KXFED-26DEC-T4.50"), ("kalshi", "KXFED-26DEC-T4.50"))
        with self.assertRaises(en.Fail):
            en.parse_id("KXFED-26DEC-T4.50")


if __name__ == "__main__":
    unittest.main()
