import unittest
from trader.chart_data import fetch_chart_data

class TestChartData(unittest.TestCase):
    def test_fetch_1d_chart(self):
        res = fetch_chart_data("TSLA", "1D")
        self.assertEqual(res["symbol"], "TSLA")
        self.assertEqual(res["timeframe"], "1D")
        self.assertGreater(len(res["candles"]), 0)
        self.assertIn("levels", res)
        self.assertIn("entry", res["levels"])
        self.assertIn("stop", res["levels"])
        self.assertIn("target", res["levels"])

    def test_fetch_1w_chart(self):
        res = fetch_chart_data("AAPL", "1W")
        self.assertEqual(res["symbol"], "AAPL")
        self.assertEqual(res["timeframe"], "1W")
        self.assertGreater(len(res["candles"]), 0)

    def test_candle_structure(self):
        res = fetch_chart_data("NVDA", "1D")
        c = res["candles"][0]
        self.assertIn("open", c)
        self.assertIn("high", c)
        self.assertIn("low", c)
        self.assertIn("close", c)
        self.assertIn("volume", c)
        self.assertIn("label", c)

if __name__ == "__main__":
    unittest.main()
