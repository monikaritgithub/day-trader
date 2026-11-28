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

    def test_run_cycle_active_orb_buys_then_flat_by_closes(self):
        import json as _json
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            watchlist_p = p / "watchlist.json"
            watchlist_p.write_text('{"mode":"orb","count":1,"results":[{"symbol":"TSLA","price":400.36}]}', encoding="utf-8")

            def fake_subproc(cmd, *args, **kwargs):
                script = " ".join(str(x) for x in cmd)
                if "entry.py" in script:
                    payload = {"symbol": "TSLA", "triggered": True, "trigger": {"price": 396.01}}
                elif "exit.py" in script:
                    payload = {"symbol": "TSLA", "stop": 389.95, "target": 408.13, "reward_risk": 2.0}
                elif "size.py" in script:
                    payload = {"symbol": "TSLA", "shares": 0.0631, "usd": 24.99, "passed": True}
                elif "check.py" in script:
                    payload = {"passed": 1, "blocked": 0, "orders": [{"symbol": "TSLA", "status": "PASS"}]}
                else:
                    payload = {}
                return mock.Mock(returncode=0, stdout=_json.dumps(payload), stderr="")

            import zoneinfo
            ny_tz = zoneinfo.ZoneInfo("America/New_York")
            nz_tz = zoneinfo.ZoneInfo("Pacific/Auckland")
            open_utc = datetime.datetime(2026, 11, 25, 15, 30, tzinfo=datetime.timezone.utc)
            flat_utc = datetime.datetime(2026, 11, 25, 20, 56, tzinfo=datetime.timezone.utc)
            open_orb_times = {
                "utc_now": open_utc,
                "ny_dt": open_utc.astimezone(ny_tz),
                "nz_dt": open_utc.astimezone(nz_tz),
                "nz_time_str": "2026-11-26 04:30:00 AM NZDT",
                "nz_date_str": "2026-11-26",
                "ny_time_str": "2026-11-25 10:30:00 AM ET",
                "is_weekday_ny": True,
                "is_market_open": True,
                "is_orb_trading_active": True,
                "is_flat_by_time": False,
                "is_close_reporting_time": False,
                "flat_by_str": "15:55",
            }
            flat_times = dict(open_orb_times, **{
                "utc_now": flat_utc,
                "ny_dt": flat_utc.astimezone(ny_tz),
                "nz_dt": flat_utc.astimezone(nz_tz),
                "nz_time_str": "2026-11-26 09:56:00 AM NZDT",
                "ny_time_str": "2026-11-25 03:56:00 PM ET",
                "is_orb_trading_active": False,
                "is_flat_by_time": True,
                "is_close_reporting_time": True,
            })

            with mock.patch("trader.auto_trader.PORTFOLIO_FILE", p / "portfolio.json"), \
                 mock.patch("trader.auto_trader.HISTORY_FILE", p / "trade_history.json"), \
                 mock.patch("trader.auto_trader.ALERTS_FILE", p / "alerts.json"), \
                 mock.patch("trader.auto_trader.WATCHLIST_FILE", watchlist_p), \
                 mock.patch("trader.auto_trader.AUTOTRADER_STATE_FILE", p / "autotrader_state.json"), \
                 mock.patch("trader.auto_trader.CONFIG_FILE", p / "config.json"), \
                 mock.patch("trader.auto_trader.subprocess.run", side_effect=fake_subproc), \
                 mock.patch("trader.auto_trader.resolve_real_market_price", return_value=400.36), \
                 mock.patch("trader.auto_trader.send_daily_market_close_report", return_value={"status": "mocked"}), \
                 mock.patch("trader.auto_trader.get_all_11_skills_approved_stocks", return_value=[{
                     "symbol": "TSLA", "status": "APPROVED", "entry": 396.01, "stop": 389.95, "target": 408.13, "price": 400.36
                 }]):
                with mock.patch.object(self.engine, "get_market_times", return_value=open_orb_times):
                    buy_cycle = self.engine.run_cycle()
                self.assertEqual(buy_cycle["status"], "cycle_completed")
                self.assertEqual(buy_cycle["open_positions"], 1)
                self.assertLess(buy_cycle["cash"], 200.0)

                with mock.patch.object(self.engine, "get_market_times", return_value=flat_times):
                    flat_cycle = self.engine.run_cycle()
                self.assertEqual(flat_cycle["open_positions"], 0)
                hist = _json.loads((p / "trade_history.json").read_text(encoding="utf-8"))
                self.assertEqual(len(hist["trades"]), 2)
                self.assertEqual(set(t["side"] for t in hist["trades"]), {"BUY", "SELL"})
                sell_trade = next(t for t in hist["trades"] if t["side"] == "SELL")
                self.assertIn("Flat-by-Close", sell_trade.get("exit_reason", ""))


if __name__ == "__main__":
    unittest.main()
