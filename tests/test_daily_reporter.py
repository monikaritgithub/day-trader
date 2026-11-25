import unittest
from trader.daily_reporter import build_daily_report_data, generate_email_html
from trader.statement_pdf import generate_broker_statement_pdf

class TestDailyReporter(unittest.TestCase):
    def test_build_daily_report_data(self):
        data = build_daily_report_data()
        self.assertIn("nz_date", data)
        self.assertIn("starting_cash", data)
        self.assertIn("current_balance", data)
        self.assertIn("previous_balance", data)
        self.assertIn("total_realized_pnl", data)
        self.assertIn("today_realized_pnl", data)
        self.assertIn("today_trades", data)
        self.assertEqual(data["starting_cash"], 200.0)

    def test_generate_email_html(self):
        data = {
            "nz_date": "2026-11-25",
            "starting_cash": 200.0,
            "previous_balance": 200.0,
            "current_balance": 204.50,
            "total_realized_pnl": 4.50,
            "total_pnl_pct": 2.25,
            "today_realized_pnl": 4.50,
            "today_pnl_pct": 2.25,
            "total_fees": 0.50,
            "today_fees": 0.50,
            "open_positions": 0,
            "today_trades_count": 2,
            "today_trades": [
                {
                    "timestamp_nzdt": "2026-11-25 04:15:00 AM NZDT",
                    "symbol": "TSLA",
                    "side": "BUY",
                    "shares": 0.065,
                    "price": 384.0,
                    "tiger_fee": 0.25,
                    "realized_pnl": 0.0,
                    "notes": "ORB Entry"
                },
                {
                    "timestamp_nzdt": "2026-11-25 05:20:00 AM NZDT",
                    "symbol": "TSLA",
                    "side": "SELL",
                    "shares": 0.065,
                    "price": 393.0,
                    "tiger_fee": 0.28,
                    "realized_pnl": 4.50,
                    "exit_reason": "1R Target Reached"
                }
            ]
        }
        html = generate_email_html(data)
        self.assertIn("Daily Market Close Statement", html)
        self.assertIn("204.50", html)
        self.assertIn("TSLA", html)
        self.assertIn("Tiger Brokers NZ", html)

    def test_generate_broker_statement_pdf(self):
        data = build_daily_report_data()
        pdf = generate_broker_statement_pdf(data)
        self.assertIsInstance(pdf, bytes)
        self.assertGreater(len(pdf), 1000)
        self.assertTrue(pdf.startswith(b"%PDF"))

if __name__ == "__main__":
    unittest.main()
