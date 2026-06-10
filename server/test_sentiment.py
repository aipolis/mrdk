import unittest
from datetime import datetime
from unittest.mock import patch

from fetcher import build_yesterday_sentiment, fetch_ref_volume_at_same_time, fetch_ref_volume_prev_label
from intraday import build_intraday_items
from app import _strip_removed_indicators
from sentiment import (
    _score_auction_block,
    calc_sentiment,
    score_high_board_promote,
    score_intraday_block,
)


def complete_metrics(**overrides):
    metrics = {
        "max_board": 5,
        "limit_up_count": 80,
        "seal_rate": 75,
        "promote_rate": 25,
        "limit_down_count": 8,
        "break_rate": 25,
        "one_word_count": 4,
        "volume_raw": 28000,
        "advance_count": 2800,
        "decline_count": 2200,
        "multi_board_count": 16,
        "high_board_promote_continued": 2,
        "high_board_promote_total": 4,
    }
    metrics.update(overrides)
    return metrics


class SentimentV2Test(unittest.TestCase):
    def test_high_board_small_sample_shrinks_toward_neutral(self):
        self.assertLess(score_high_board_promote(1, 1), 90)
        self.assertGreater(score_high_board_promote(0, 1), 20)
        self.assertGreater(score_high_board_promote(3, 3), score_high_board_promote(1, 3))

    def test_seal_and_break_are_combined_for_weighting(self):
        result = calc_sentiment(complete_metrics())
        subs = result["subScores"]
        self.assertIn("sealQuality", subs["yesterday"])
        self.assertIn("sealQuality", subs["contributions"])
        self.assertNotIn("seal", subs["contributions"])
        self.assertNotIn("break", subs["contributions"])

    def test_high_board_zero_of_three_triggers_warning_gate(self):
        result = calc_sentiment(
            complete_metrics(
                high_board_promote_continued=0,
                high_board_promote_total=3,
                limit_up_count=130,
                seal_rate=85,
                break_rate=15,
            )
        )
        self.assertEqual(result["riskLevel"], "warning")
        self.assertFalse(result["emptyWarning"])
        self.assertTrue(any("高位板晋级仅0/3" in reason for reason in result["emptyReasons"]))

    def test_optional_missing_data_is_reported(self):
        result = calc_sentiment(complete_metrics())
        quality = result["subScores"]["dataQuality"]
        self.assertIn("top10AvgChg", quality["missing"])
        self.assertGreater(quality["completeness"], 0.7)
        self.assertLess(quality["completeness"], 1.0)

    def test_missing_live_and_auction_fields_do_not_become_neutral_scores(self):
        live = score_intraday_block({"limit_up": 20, "limit_down": 3})
        self.assertEqual(set(live), {"limitUpLive", "limitDownLive"})

        auction = _score_auction_block(
            [{"key": "recentMulti", "value": "-1.50%"}],
            {},
        )
        self.assertEqual(set(auction), {"recentMulti"})

    def test_high_board_live_feedback_is_scored_as_leading_signal(self):
        weak = score_intraday_block({"limit_up": 20, "limit_down": 3, "high_board_chg_live": -5})
        strong = score_intraday_block({"limit_up": 20, "limit_down": 3, "high_board_chg_live": 9})
        self.assertEqual(weak["highBoardChgLive"], 20)
        self.assertEqual(strong["highBoardChgLive"], 90)

    def test_intraday_items_follow_longkong_priority_order(self):
        items = build_intraday_items({"high_board_chg_live": 6.8, "prev_max_board": 5})
        self.assertEqual(len(items), 9)
        self.assertEqual(
            [item["key"] for item in items],
            [
                "highBoardChgLive",
                "promoteLive",
                "breakLive",
                "limitDownLive",
                "sseIndex",
                "top10AvgChgLive",
                "limitUpLive",
                "upRatio",
                "marketVolumeLive",
            ],
        )
        self.assertEqual(items[0]["value"], "+6.80%")
        self.assertEqual(items[0]["yesterday"], "5板")

    @patch("fetcher._fetch_market_amount_through_time_baostock")
    @patch("fetcher._lookup_volume_snapshot")
    def test_lunch_volume_comparison_freezes_at_1130(self, lookup, baostock):
        lookup.return_value = 5234.0
        now = datetime(2026, 6, 10, 12, 15)

        same = fetch_ref_volume_at_same_time("20260609", now)
        label, raw = fetch_ref_volume_prev_label({"volume_raw": 12345}, "20260609", now)

        self.assertEqual(same, 5234.0)
        self.assertEqual((label, raw), ("5234亿", 5234.0))
        lookup.assert_called_with("20260609", "1130")
        baostock.assert_not_called()

    @patch("fetcher._fetch_market_amount_through_time_baostock", return_value=None)
    @patch("fetcher._lookup_volume_snapshot", return_value=None)
    def test_lunch_volume_never_falls_back_to_full_day(self, lookup, baostock):
        label, raw = fetch_ref_volume_prev_label(
            {"volume_raw": 12345},
            "20260609",
            datetime(2026, 6, 10, 12, 15),
        )

        self.assertEqual((label, raw), ("--", None))
        lookup.assert_called_with("20260609", "1130")
        baostock.assert_called_with("20260609", 11, 30)

    def test_overview_keeps_top10_cell_when_archive_value_is_missing(self):
        items = build_yesterday_sentiment(complete_metrics(), complete_metrics())
        top10 = next(item for item in items if item["key"] == "top10AvgChg")

        self.assertEqual(top10["value"], "--")
        self.assertEqual(top10["yesterday"], "--")

    def test_old_archived_overview_gets_missing_top10_placeholder(self):
        data = {
            "grid9": [{"key": "continuationDepth", "value": "7.7%"}],
            "indicatorSections": [
                {
                    "id": "yesterday",
                    "items": [{"key": "continuationDepth", "value": "7.7%"}],
                },
            ],
        }

        patched = _strip_removed_indicators(data)

        self.assertEqual(patched["grid9"][-1]["key"], "top10AvgChg")
        self.assertEqual(patched["grid9"][-1]["value"], "--")
        self.assertEqual(patched["indicatorSections"][0]["items"][-1]["key"], "top10AvgChg")


if __name__ == "__main__":
    unittest.main()
