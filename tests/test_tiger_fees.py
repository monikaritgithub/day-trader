import datetime
import unittest
from trader.tiger_fees import (
    calculate_tiger_nz_fee,
    check_fractional_support,
    preview_round_trip_economics,
    evaluate_tiger_nz_order_plan,
)


class TestTigerNZFees(unittest.TestCase):
    def test_zero_or_negative(self):
        fee = calculate_tiger_nz_fee("BUY", 0, 100)
        self.assertEqual(fee["total_fee"], 0.0)

    def test_fractional_buy_25_usd(self):
        # 0.1 shares @ $250.00 = $25.00 trade value -> 1% platform fee = $0.25, commission $0
        fee = calculate_tiger_nz_fee("BUY", 0.1, 250.0)
        self.assertTrue(fee["is_fractional"])
        self.assertEqual(fee["commission"], 0.0)
        self.assertEqual(fee["platform_fee"], 0.25)
        self.assertEqual(fee["total_fee"], 0.25)
        self.assertEqual(fee["regulatory_fees"], 0.0)

    def test_fractional_sell_waived_vs_conservative_regulatory(self):
        # Tiger NZ waives 3rd-party fees on <1 share by default, or estimates $0.01 SEC conservatively
        fee_std = calculate_tiger_nz_fee("SELL", 0.1, 260.0, conservative_regulatory=False)
        self.assertTrue(fee_std["is_fractional"])
        self.assertEqual(fee_std["regulatory_fees"], 0.0)
        self.assertEqual(fee_std["total_fee"], 0.26)

        fee_cons = calculate_tiger_nz_fee("SELL", 0.1, 260.0, conservative_regulatory=True)
        self.assertGreater(fee_cons["regulatory_fees"], 0.0)
        self.assertEqual(fee_cons["sec_fee"], 0.01)

    def test_standard_whole_shares_buy(self):
        # 10 shares @ $50.00 = $500.00 -> min $0.99 comm + $1.00 platform + $0.03 settlement = $2.02
        fee = calculate_tiger_nz_fee("BUY", 10, 50.0)
        self.assertFalse(fee["is_fractional"])
        self.assertEqual(fee["commission"], 0.99)
        self.assertEqual(fee["platform_fee"], 1.00)
        self.assertEqual(fee["settlement_fee"], 0.03)
        self.assertEqual(fee["total_fee"], 2.02)

    def test_standard_whole_shares_sell(self):
        # Outside Q4 2026 FINRA TAF holiday, both SEC & FINRA TAF apply
        fee = calculate_tiger_nz_fee("SELL", 10, 55.0, as_of_date=datetime.date(2027, 1, 15))
        self.assertFalse(fee["is_fractional"])
        self.assertEqual(fee["commission"], 0.99)
        self.assertEqual(fee["platform_fee"], 1.00)
        self.assertGreater(fee["sec_fee"], 0.0)
        self.assertGreater(fee["finra_taf"], 0.0)
        self.assertGreater(fee["total_fee"], 2.02)

    def test_rejects_uneconomical_1r_25_usd_trade(self):
        # $25 TSLA 1R trade: gross target profit ~$0.50, round-trip fee ~$0.52 -> net <= 0 -> REJECTED
        res = evaluate_tiger_nz_order_plan(
            symbol="TSLA",
            entry_price=384.28,
            stop_price=376.59,
            target_price=391.97,
            target_usd=25.0,
            max_loss_usd=1.50,
            min_net_profit_usd=0.05,
        )
        self.assertFalse(res["approved"])
        self.assertLessEqual(res["economics"]["expected_net_profit"], 0.05)

    def test_approves_profitable_2r_fractional_trade(self):
        # $25 TSLA 2R trade: gross target profit ~$1.00, round-trip fee ~$0.52 -> net ~$0.48 -> APPROVED
        res = evaluate_tiger_nz_order_plan(
            symbol="TSLA",
            entry_price=384.28,
            stop_price=376.59,
            target_price=399.66,
            target_usd=25.0,
            max_loss_usd=1.50,
            min_net_profit_usd=0.05,
        )
        self.assertTrue(res["approved"])
        self.assertTrue(res["is_fractional"])
        self.assertLess(res["shares"], 1.0)
        self.assertGreater(res["economics"]["expected_net_profit"], 0.40)

    def test_sub_one_fractional_cap_beats_whole_share_minimum(self):
        # On a $15 stock, $25 buys 1.66 shares (triggers $1.99/leg whole-share min = $4.00+ round trip)
        # Capping <1 share (0.999 sh = $14.99) keeps 1% fractional fee (~$0.32 round-trip)!
        res = evaluate_tiger_nz_order_plan(
            symbol="SOFI",
            entry_price=15.00,
            stop_price=14.40,
            target_price=16.20,
            target_usd=25.0,
            max_loss_usd=1.50,
            min_net_profit_usd=0.05,
        )
        self.assertTrue(res["approved"])
        self.assertEqual(res["order_mode"], "fractional_sub_one_cap")
        self.assertLess(res["shares"], 1.0)
        self.assertGreater(res["economics"]["expected_net_profit"], 0.80)

    def test_fractional_support_validation(self):
        self.assertFalse(check_fractional_support("ABC.W", 20.0, 25.0)["supported"])
        self.assertFalse(check_fractional_support("TSLA", 380.0, 0.50)["supported"])
        self.assertTrue(check_fractional_support("TSLA", 380.0, 25.0)["supported"])


if __name__ == "__main__":
    unittest.main()
