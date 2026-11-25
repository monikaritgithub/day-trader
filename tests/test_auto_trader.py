import datetime
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from trader.auto_trader import AutoTraderEngine, UNIVERSE_FILE


class TestAutoTrader(unittest.TestCase):
    def setUp(self):
        self.engine = AutoTraderEngine()

    def test_market_times(self):
        times = self.engine.get_market_times()
        self.assertIn("nz_time_str", times)
        self.assertIn("ny_time_str", times)
        self.assertIn("is_market_open", times)
        self.assertIn("is_orb_trading_active", times)
        # timestamp_nzdt must start with YYYY-MM-DD so daily_reporter matches it
        self.assertRegex(times["nz_time_str"], r"^\d{4}-\d{2}-\d{2} ")

    def test_load_universe(self):
        self.assertGreater(len(self.engine.universe_symbols), 10)
        if UNIVERSE_FILE.is_file():
            self.assertGreater(len(self.engine.universe_symbols), 5000)
        self.assertIn("TSLA", self.engine.universe_symbols)
        self.assertIn("NVDA", self.engine.universe_symbols)

    def test_next_universe_batch_rolls_across_full_universe(self):
        self.engine.universe_pointer = 0
        b1 = self.engine.next_universe_batch(batch_size=100)
        b2 = self.engine.next_universe_batch(batch_size=100)
        self.assertEqual(len(b1), 100)
        self.assertEqual(len(b2), 100)
        self.assertEqual(set(b1).intersection(set(b2)), set())

    def test_nyse_holidays_and_early_close(self):
        # Thanksgiving 2026-11-26 10:30 AM EST = 15:30 UTC (market closed)
        thanksgiving_utc = datetime.datetime(2026, 11, 26, 15, 30, tzinfo=datetime.timezone.utc)
        with mock.patch("trader.auto_trader.datetime.datetime") as mock_dt:
            mock_dt.now.return_value = thanksgiving_utc
            times = self.engine.get_market_times()
            self.assertFalse(times["is_weekday_ny"])
            self.assertFalse(times["is_market_open"])
            self.assertFalse(times["is_orb_trading_active"])

        # Early close 2026-11-27 12:56 PM EST = 17:56 UTC (flat_by active, entries closed)
        early_close_utc = datetime.datetime(2026, 11, 27, 17, 56, tzinfo=datetime.timezone.utc)
        with mock.patch("trader.auto_trader.datetime.datetime") as mock_dt:
            mock_dt.now.return_value = early_close_utc
            times = self.engine.get_market_times()
            self.assertTrue(times["is_market_open"])
            self.assertFalse(times["is_orb_trading_active"])
            self.assertTrue(times["is_flat_by_time"])

        # Regular session 2026-11-25 10:00 AM EST = 15:00 UTC (active ORB trading)
        regular_utc = datetime.datetime(2026, 11, 25, 15, 0, tzinfo=datetime.timezone.utc)
        with mock.patch("trader.auto_trader.datetime.datetime") as mock_dt:
            mock_dt.now.return_value = regular_utc
            times = self.engine.get_market_times()
            self.assertTrue(times["is_market_open"])
            self.assertTrue(times["is_orb_trading_active"])
            self.assertFalse(times["is_flat_by_time"])

    def test_run_cycle(self):
        res = self.engine.run_cycle()
        self.assertEqual(res["status"], "cycle_completed")
        self.assertIn("cash", res)

    def test_execute_buy_rejects_uneconomical_1r_trade(self):
        # 1R $25 TSLA trade ($0.50 gross vs ~$0.52 round-trip fee) must be rejected
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            with mock.patch("trader.auto_trader.PORTFOLIO_FILE", p / "portfolio.json"), \
                 mock.patch("trader.auto_trader.HISTORY_FILE", p / "trade_history.json"), \
                 mock.patch("trader.auto_trader.ALERTS_FILE", p / "alerts.json"):
                res = self.engine.execute_buy("TSLA", entry_price=384.28, stop_price=376.59, target_price=391.97, usd_amount=25.0)
                self.assertIsNone(res)

    def test_execute_buy_approves_profitable_2r_fractional_trade(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            with mock.patch("trader.auto_trader.PORTFOLIO_FILE", p / "portfolio.json"), \
                 mock.patch("trader.auto_trader.HISTORY_FILE", p / "trade_history.json"), \
                 mock.patch("trader.auto_trader.ALERTS_FILE", p / "alerts.json"):
                res = self.engine.execute_buy("TSLA", entry_price=384.28, stop_price=376.59, target_price=399.66, usd_amount=25.0)
                self.assertIsNotNone(res)
                self.assertLess(res["shares"], 1.0)
                self.assertEqual(res["tiger_fee"], 0.25)
                self.assertRegex(res["timestamp_nzdt"], r"^\d{4}-\d{2}-\d{2} ")


if __name__ == "__main__":
    unittest.main()
