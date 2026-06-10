import unittest
from datetime import datetime
from unittest.mock import patch

import pandas as pd

from fetcher import (
    _cache,
    _cache_set,
    build_longkong_risk_items,
    build_yesterday_sentiment,
    fetch_ref_volume_at_same_time,
    fetch_ref_volume_prev_label,
    get_market_auction_volume_yi,
    fetch_intraday_board_stats,
    invalidate_auction_day_cache,
)
from intraday import _live_blend_weight, build_intraday_items, build_intraday_payload, fetch_intraday_snapshot
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
    def test_intraday_snapshot_backfills_live_counts_when_breadth_source_drops(self):
        _cache.pop("intraday_breadth_last_valid_20260610", None)
        valid = {"advance": 3000, "decline": 2000, "limit_up": 0, "limit_down": 0}
        empty = {"advance": 0, "decline": 0, "limit_up": 0, "limit_down": 0}
        board = {
            "high_board_chg_live": None,
            "prev_max_board": None,
            "top10_avg_live": None,
            "prev_top10_avg": None,
            "promote_live": None,
            "prev_promote": None,
            "break_live": None,
            "prev_break": None,
        }
        with (
            patch("intraday.bj_now", return_value=datetime(2026, 6, 10, 10, 30)),
            patch("intraday._legu_live_counts", side_effect=[valid, empty]),
            patch("intraday._fetch_market_breadth_live", return_value=(0, 0, "")),
            patch("intraday.fetch_limit_up", return_value=pd.DataFrame({"code": range(54)})),
            patch("intraday.fetch_limit_down", return_value=pd.DataFrame({"code": range(9)})),
            patch("intraday.fetch_prev_zt_avg_chg", return_value=None),
            patch("intraday._spot_market_amount_yi", return_value=("--", 0)),
            patch("intraday.fetch_market_activity", return_value={}),
            patch("intraday.fetch_ref_volume_prev_label", return_value=("--", None)),
            patch("intraday._resolve_prev_sse", return_value=None),
            patch("intraday.fetch_intraday_board_stats", return_value=board),
        ):
            fresh = fetch_intraday_snapshot()
            fallback = fetch_intraday_snapshot()

        self.assertEqual((fresh["limit_up"], fresh["limit_down"]), (54, 9))
        self.assertEqual(fallback["up_ratio"], 60.0)
        self.assertEqual((fallback["advance"], fallback["decline"]), (3000, 2000))

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

    @patch("app.historical_top10_avg_chg", return_value=-2.59)
    def test_old_archived_overview_backfills_top10_average(self, historical_avg):
        data = {
            "tradeDate": "20260609",
            "metrics": {
                "date": "2026-06-09",
                "top10_codes": ["000001", "000002", "000003", "000004", "000005", "000006"],
                "top10_avg_chg": None,
            },
            "grid9": [{"key": "top10AvgChg", "value": "--"}],
            "indicatorSections": [
                {"id": "yesterday", "items": [{"key": "top10AvgChg", "value": "--"}]},
            ],
        }

        patched = _strip_removed_indicators(data)

        self.assertEqual(patched["grid9"][0]["value"], "-2.59%")
        self.assertEqual(patched["indicatorSections"][0]["items"][0]["value"], "-2.59%")
        self.assertEqual(patched["metrics"]["top10_avg_chg"], -2.59)
        historical_avg.assert_called_once()

    @patch("fetcher._compute_market_auction_volume_yi", return_value=None)
    @patch("fetcher.date_str", return_value="20260610")
    def test_auction_volume_reuses_last_valid_same_day_value(self, date_str_mock, compute):
        _cache.pop("auction_vol_yi_20260610", None)
        _cache_set("auction_vol_yi_last_valid_20260610", 412.0)

        self.assertEqual(get_market_auction_volume_yi("20260610"), 412.0)

    def test_auction_freeze_invalidation_preserves_captured_total_volume(self):
        _cache_set("auction_vol_yi_20260610", 412.0)
        _cache_set("auction_one_word_20260610", 4)

        invalidate_auction_day_cache("20260610", preserve_volume=True)

        self.assertEqual(_cache.get("auction_vol_yi_20260610", {}).get("data"), 412.0)
        self.assertNotIn("auction_one_word_20260610", _cache)

    @patch("history_store.fetch_intraday_snapshot_at_or_before")
    @patch("intraday.intraday_session_phase", return_value="live")
    @patch("intraday.is_lunch_break", return_value=True)
    @patch("intraday.bj_now", return_value=datetime(2026, 6, 10, 12, 15))
    def test_lunch_intraday_payload_uses_last_1130_snapshot(
        self, now, lunch, phase, fetch_frozen
    ):
        fetch_frozen.return_value = {
            "items": [{"key": "upRatio", "value": "54.0%"}],
            "intradayScore": 61,
            "intradaySubScores": {"live": {"upRatio": 63}},
            "snap": {"up_ratio": 54.0},
            "updatedAt": "11:30",
        }

        payload = build_intraday_payload({}, ref_d="20260609")

        self.assertEqual(payload["phase"], "lunch")
        self.assertEqual(payload["updatedAt"], "11:30")
        self.assertEqual(payload["items"][0]["value"], "54.0%")
        fetch_frozen.assert_called_once_with("20260610", "11:30")

    @patch("intraday.is_lunch_break", return_value=True)
    def test_lunch_display_score_weight_freezes_at_1130(self, lunch):
        lunch_weight = _live_blend_weight(datetime(2026, 6, 10, 12, 15))
        close_weight = _live_blend_weight(datetime(2026, 6, 10, 11, 30))
        self.assertEqual(lunch_weight, close_weight)

    @patch("fetcher._break_rate", return_value=20.0)
    @patch("fetcher._promote_rate", return_value=25.0)
    @patch("fetcher._resolve_prev_top10_avg", return_value=None)
    @patch("fetcher._load_top10_codes_for_date", return_value=[])
    @patch("fetcher._fetch_sina_quotes_df")
    @patch("fetcher.fetch_limit_up")
    @patch("fetcher._fetch_em_top_amount_spot_df")
    @patch("fetcher.ak.stock_zh_a_spot_em", side_effect=RuntimeError("full market unavailable"))
    def test_high_board_live_feedback_uses_targeted_sina_quotes(
        self, em_spot, top_amount, fetch_up, sina_quotes, load_top10, prev_top10, promote, break_rate
    ):
        import pandas as pd

        top_amount.return_value = pd.DataFrame([{"代码": "000001", "涨跌幅": 1.0}])
        fetch_up.return_value = pd.DataFrame([
            {"代码": "002354", "连板数": 6},
            {"代码": "002254", "连板数": 6},
            {"代码": "000001", "连板数": 1},
        ])
        sina_quotes.return_value = pd.DataFrame([
            {"代码": "002354", "涨跌幅": 2.0},
            {"代码": "002254", "涨跌幅": -1.0},
        ])
        _cache.pop("intraday_board_stats_v2", None)

        stats = fetch_intraday_board_stats("20260609", {"max_board": 6}, live=True)

        self.assertEqual(stats["high_board_chg_live"], 0.5)
        sina_quotes.assert_called_once_with(["002354", "002254"])

    @patch("fetcher._prev_longkong_risk_value", return_value="48")
    @patch("fetcher._fetch_em_big_drop_count", return_value=None)
    @patch("fetcher._fetch_em_a_share_snapshot", return_value={"rows": 0, "big_drop_count": None})
    @patch("fetcher.ak.stock_zh_a_spot_em", side_effect=RuntimeError("upstream unavailable"))
    @patch("fetcher.fetch_limit_down")
    @patch("fetcher.fetch_broken_board")
    @patch("fetcher.fetch_limit_up")
    def test_big_loss_reuses_last_valid_same_day_value(
        self, fetch_up, fetch_broken, fetch_down, spot, snapshot, big_drop, prev_value
    ):
        import pandas as pd

        fetch_up.return_value = pd.DataFrame()
        fetch_broken.return_value = pd.DataFrame()
        fetch_down.return_value = pd.DataFrame()
        _cache_set("big_drop_count_last_valid_20260610", 23)

        items = build_longkong_risk_items(
            "20260609",
            "20260608",
            complete_metrics(),
            complete_metrics(),
            advice_d="20260610",
        )

        big_loss = next(item for item in items if item["key"] == "bigLossCount")
        self.assertEqual(big_loss["value"], "23")


if __name__ == "__main__":
    unittest.main()
