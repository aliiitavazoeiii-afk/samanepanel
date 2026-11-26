"""Regression tests for read-only unified sister sales summaries."""
import unittest
from unittest.mock import patch

from daily_sales_service.sister_sales_overview_v1 import sales_overview


def line(day, source, gross, fee, cost, packs=1, units=1, identifier="1"):
    return {"sale_date": day, "source": source, "gross": gross, "fees": fee,
            "net": gross - fee, "cogs": cost, "packs": packs, "units": units,
            "sale_id": identifier}


class UnifiedSalesSummaryTests(unittest.TestCase):
    def test_sums_channels_and_days_without_double_counting(self):
        entries = [
            line("2026-11-26", "digikala", 360000, 90000, 178000, 2, 2, "dk"),
            line("2026-11-26", "site", 200000, 0, 120000, 1, 2, "site"),
            line("2026-11-25", "mold", 500000, 0, 350000, 1, 1, "invoice"),
        ]
        with patch("daily_sales_service.sister_sales_overview_v1.sale_lines", return_value=entries) as mocked:
            result = sales_overview(None, "2026-11-25", "2026-11-26")
        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(result["total"]["gross"], 1060000)
        self.assertEqual(result["total"]["fees"], 90000)
        self.assertEqual(result["total"]["cogs_known"], 648000)
        self.assertEqual(result["total"]["profit"], 322000)
        self.assertEqual(result["total"]["orders"], 3)
        self.assertEqual(result["total"]["packs"], 4)
        self.assertEqual(result["total"]["units"], 5)
        self.assertEqual(len(result["channels"]), 3)
        self.assertEqual(len(result["days"]), 2)
        self.assertEqual(len(result["day_channels"]), 3)

    def test_unknown_cost_does_not_show_fake_zero_profit(self):
        entries = [line("2026-11-26", "digikala", 100000, 25000, None)]
        with patch("daily_sales_service.sister_sales_overview_v1.sale_lines", return_value=entries):
            result = sales_overview(None, "2026-11-26", "2026-11-26")
        self.assertIsNone(result["total"]["profit"])
        self.assertEqual(result["total"]["unknown_cost_lines"], 1)
        self.assertIsNone(result["channels"][0]["profit"])
        self.assertIsNone(result["days"][0]["profit"])

    def test_zero_sales_channel_filter(self):
        with patch("daily_sales_service.sister_sales_overview_v1.sale_lines", return_value=[]) as mocked:
            result = sales_overview(None, "2026-11-26", "2026-11-26", "basalam")
        self.assertEqual(mocked.call_args.kwargs["channel"], "basalam")
        self.assertEqual(result["total"]["gross"], 0)
        self.assertEqual(result["total"]["profit"], 0)
        self.assertEqual(result["day_channels"], [])


if __name__ == "__main__":
    unittest.main()
