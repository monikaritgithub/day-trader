import tempfile
import unittest
from pathlib import Path
from unittest import mock
from trader.auto_trader import AutoTraderEngine


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
        self.assertIn("TSLA", self.engine.universe_symbols)
        self.assertIn("NVDA", self.engine.universe_symbols)

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
