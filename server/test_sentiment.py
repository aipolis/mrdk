import unittest

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


if __name__ == "__main__":
    unittest.main()
