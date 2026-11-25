"""
Tiger Brokers New Zealand (Tiger Trade) US Stock & Fractional Fee Engine
Implements the Tiger Brokers NZ fee schedule for US Stocks/ETFs and enforces
the Fractional Share Trading Rule for small-capital (e.g. US$25) accounts:

Verified Tiger Brokers NZ US Stocks & ETFs Fee Schedule:
1. Fractional Shares (< 1.0 share, min US$1.00):
   - Commission: Waived ($0.00)
   - Platform Fee: 1.0% of trade value, capped at max US$1.00 per order
   - Third-party regulatory fees: Waived on fractional orders < 1 share
     (conservative preview also models optional regulatory reserve if enabled)

2. Standard US Stocks & ETFs (>= 1.0 share):
   - Commission: US$0.005 per share (min US$0.99/order; 0.5% cap on Tiered/promo,
     or flat US$0.99 minimum on standard Fixed orders)
   - Platform Fee: US$0.005 per share (min US$1.00/order; 0.5% cap on Tiered/promo,
     or flat US$1.00 minimum on standard Fixed orders)
   - Combined whole-share minimum: US$1.99/order (US$3.98 round-trip) when
     fixed minimums apply without small-order fee caps.
   - Settlement Fee: US$0.003 per share (max 7% of trade value)

3. Regulatory / Third-Party Pass-Through Fees (SELL orders >= 1 share):
   - SEC Section 31 Fee: US$20.60 per $1,000,000 (0.0000206 * sell value, min US$0.01,
     effective April 4, 2026)
   - FINRA TAF: US$0.00 during Q4 2026 fee holiday (Oct 1 - Dec 31, 2026);
     standard rate US$0.000195 per share (min US$0.01, max US$8.30) otherwise.
"""

import datetime
import re
from typing import Dict, Any, Optional

# Effective April 4, 2026 SEC Section 31 rate ($20.60 per million)
SEC_FEE_RATE = 0.0000206
# Standard FINRA TAF rate outside Q4 2026 holiday
FINRA_TAF_PER_SHARE = 0.000195
FINRA_TAF_MAX = 8.30
SETTLEMENT_FEE_PER_SHARE = 0.003

# Standard US ticker pattern (fractional US stocks/ETFs on Tiger NZ)
US_TICKER_RE = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")

# Non-fractional / unsupported edge cases (e.g. OTC / preferred / warrants)
UNSUPPORTED_FRACTIONAL_SUFFIXES = (".W", ".U", ".R", ".WS")


def _is_finra_taf_holiday(as_of_date: Optional[datetime.date] = None) -> bool:
    """FINRA Q4 2026 TAF fee holiday: Oct 1, 2026 through Dec 31, 2026."""
    d = as_of_date or datetime.date.today()
    return datetime.date(2026, 10, 1) <= d <= datetime.date(2026, 12, 31)


def check_fractional_support(
    symbol: str,
    price: float,
    target_usd: float = 25.0,
    universe_symbols: Optional[set] = None
) -> Dict[str, Any]:
    """
    Checks whether a US ticker is eligible for fractional share trading (< 1 share)
    on Tiger Brokers NZ and whether target_usd satisfies the US$1.00 minimum.
    """
    sym = str(symbol or "").strip().upper()
    px = float(price or 0.0)
    usd = float(target_usd or 0.0)

    if not sym or not US_TICKER_RE.match(sym) or any(sym.endswith(s) for s in UNSUPPORTED_FRACTIONAL_SUFFIXES):
        return {
            "supported": False,
            "reason": f"Ticker '{sym}' is not eligible for standard US fractional share execution."
        }
    if universe_symbols is not None and sym not in universe_symbols:
        # Allow major ETFs/US equities even if not in common-stock-only universe.txt
        if not re.match(r"^[A-Z]{1,5}$", sym):
            return {
                "supported": False,
                "reason": f"Ticker '{sym}' could not be verified in US stock universe."
            }
    if px <= 0:
        return {
            "supported": False,
            "reason": f"Invalid share price ({px}) for {sym}; cannot verify fractional fee structure."
        }
    if usd < 1.0:
        return {
            "supported": False,
            "reason": f"Order value ${usd:.2f} is below Tiger Brokers NZ US$1.00 fractional minimum."
        }

    raw_shares = round(usd / px, 4)
    fits_under_one_share = (raw_shares < 1.0)
    return {
        "supported": True,
        "symbol": sym,
        "price": px,
        "target_usd": usd,
        "raw_shares": raw_shares,
        "fits_under_one_share": fits_under_one_share,
        "reason": (
            f"{sym} eligible for fractional (<1 share: {raw_shares:.4f} sh @ ${px:.2f})"
            if fits_under_one_share else
            f"{sym} price (${px:.2f}) <= ${usd:.2f}: {raw_shares:.4f} shares >= 1.0 (whole-share fee tier unless capped <1 share)"
        )
    }


def calculate_tiger_nz_fee(
    side: str,
    shares: float,
    price: float,
    apply_small_order_cap: bool = False,
    conservative_regulatory: bool = False,
    as_of_date: Optional[datetime.date] = None
) -> Dict[str, Any]:
    """
    Calculates Tiger Brokers NZ trading fees for a US equity order.

    Parameters:
      side: "BUY" or "SELL"
      shares: order share quantity
      price: execution price per share in USD
      apply_small_order_cap: if True on whole-share orders (>=1 share), caps
        commission & platform fee at 0.5% each (1.0% total). Default False
        conservatively models the US$1.99 fixed minimum on >=1 share orders.
      conservative_regulatory: if True on fractional SELL (<1 share), reserves
        estimated US$0.01 SEC fee even though Tiger NZ normally waives 3rd-party
        fees on <1 share orders.
    """
    side = str(side or "BUY").upper().strip()
    shares = abs(float(shares or 0.0))
    price = abs(float(price or 0.0))
    trade_value = round(shares * price, 4)

    if trade_value <= 0 or shares <= 0:
        return {
            "total_fee": 0.0,
            "commission": 0.0,
            "platform_fee": 0.0,
            "settlement_fee": 0.0,
            "regulatory_fees": 0.0,
            "sec_fee": 0.0,
            "finra_taf": 0.0,
            "is_fractional": False,
            "trade_value": 0.0,
            "description": "No trade value"
        }

    is_fractional = (shares < 0.9999)

    if is_fractional:
        # Tiger Brokers NZ US Fractional Share (< 1 share):
        # Commission waived ($0.00); Platform fee 1.0% of trade value, capped at US$1.00
        commission = 0.0
        platform_fee = round(min(1.00, max(0.01, trade_value * 0.01)), 2)
        settlement_fee = 0.0
    else:
        # Standard US Stock (>= 1 share):
        # Commission: $0.005/share (min $0.99); Platform: $0.005/share (min $1.00)
        commission = max(0.99, round(shares * 0.005, 2))
        platform_fee = max(1.00, round(shares * 0.005, 2))
        if apply_small_order_cap:
            commission = min(commission, round(trade_value * 0.005, 2))
            platform_fee = min(platform_fee, round(trade_value * 0.005, 2))
        settlement_fee = min(round(trade_value * 0.07, 2), round(shares * SETTLEMENT_FEE_PER_SHARE, 2))

    broker_subtotal = round(commission + platform_fee + settlement_fee, 2)

    # Regulatory pass-through fees (SELL orders)
    sec_fee = 0.0
    finra_taf = 0.0
    if side == "SELL":
        if not is_fractional:
            sec_fee = max(0.01, round(trade_value * SEC_FEE_RATE, 2))
            if not _is_finra_taf_holiday(as_of_date):
                raw_taf = shares * FINRA_TAF_PER_SHARE
                finra_taf = min(FINRA_TAF_MAX, max(0.01, round(raw_taf, 2)))
        elif conservative_regulatory:
            # Optional conservative reserve if regulatory pass-through applies
            sec_fee = max(0.01, round(trade_value * SEC_FEE_RATE, 2))

    regulatory_fees = round(sec_fee + finra_taf, 2)
    total_fee = round(broker_subtotal + regulatory_fees, 2)

    desc = (
        f"Tiger NZ Fractional (Comm: $0.00, Plat 1%: ${platform_fee:.2f}"
        + (f", Reg: ${regulatory_fees:.2f}" if regulatory_fees > 0 else "")
        + f"): ${total_fee:.2f} USD"
        if is_fractional else
        f"Tiger NZ Standard (Comm: ${commission:.2f}, Plat: ${platform_fee:.2f}"
        + (f", Settle: ${settlement_fee:.2f}" if settlement_fee > 0 else "")
        + (f", Reg: ${regulatory_fees:.2f}" if regulatory_fees > 0 else "")
        + f"): ${total_fee:.2f} USD"
    )

    return {
        "total_fee": total_fee,
        "commission": commission,
        "platform_fee": platform_fee,
        "settlement_fee": settlement_fee,
        "regulatory_fees": regulatory_fees,
        "sec_fee": sec_fee,
        "finra_taf": finra_taf,
        "is_fractional": is_fractional,
        "trade_value": round(trade_value, 2),
        "description": desc
    }


def preview_round_trip_economics(
    symbol: str,
    shares: float,
    entry_price: float,
    stop_price: float,
    target_price: float,
    min_net_profit_usd: float = 0.05,
    conservative_regulatory: bool = True
) -> Dict[str, Any]:
    """
    Previews exact buy + sell + regulatory fees and expected net profit at target.
    Rejects trades where expected net profit after all fees is below min_net_profit_usd.
    """
    sym = str(symbol or "").strip().upper()
    sh = round(float(shares or 0.0), 4)
    entry_p = float(entry_price or 0.0)
    stop_p = float(stop_price or 0.0)
    target_p = float(target_price or 0.0)

    if not sym or sh <= 0 or entry_p <= 0 or stop_p <= 0 or target_p <= 0:
        return {
            "verified": False,
            "profitable": False,
            "reason": "Missing or invalid symbol/shares/prices; fee structure cannot be verified."
        }
    if target_p <= entry_p:
        return {
            "verified": False,
            "profitable": False,
            "reason": f"Target (${target_p:.2f}) must be above entry (${entry_p:.2f})."
        }
    if stop_p >= entry_p:
        return {
            "verified": False,
            "profitable": False,
            "reason": f"Stop (${stop_p:.2f}) must be below entry (${entry_p:.2f})."
        }

    buy_fee_info = calculate_tiger_nz_fee("BUY", sh, entry_p, conservative_regulatory=conservative_regulatory)
    sell_fee_info = calculate_tiger_nz_fee("SELL", sh, target_p, conservative_regulatory=conservative_regulatory)
    stop_sell_fee_info = calculate_tiger_nz_fee("SELL", sh, stop_p, conservative_regulatory=conservative_regulatory)

    buy_fee = buy_fee_info["total_fee"]
    sell_fee = sell_fee_info["total_fee"]
    round_trip_fee = round(buy_fee + sell_fee, 2)
    stop_round_trip_fee = round(buy_fee + stop_sell_fee_info["total_fee"], 2)

    notional = round(sh * entry_p, 2)
    gross_profit = round(sh * (target_p - entry_p), 2)
    expected_net_profit = round(gross_profit - round_trip_fee, 2)
    gross_loss_at_stop = round(sh * (entry_p - stop_p), 2)
    net_loss_at_stop = round(gross_loss_at_stop + stop_round_trip_fee, 2)
    fee_drag_pct = round((round_trip_fee / gross_profit) * 100.0, 1) if gross_profit > 0 else 999.9
    net_rr = round(expected_net_profit / net_loss_at_stop, 2) if net_loss_at_stop > 0 else 0.0

    profitable = (expected_net_profit >= min_net_profit_usd and expected_net_profit > 0)
    if not profitable:
        reason = (
            f"Uneconomical after fees: gross profit ${gross_profit:.2f} minus round-trip Tiger NZ fees "
            f"${round_trip_fee:.2f} = ${expected_net_profit:+.2f} net (below ${min_net_profit_usd:.2f} min threshold)."
        )
    else:
        reason = (
            f"Net profit ${expected_net_profit:+.2f} after ${round_trip_fee:.2f} round-trip fees "
            f"(gross ${gross_profit:.2f}, fee drag {fee_drag_pct:.1f}%, net R:R {net_rr:.2f}:1)."
        )

    return {
        "verified": True,
        "profitable": profitable,
        "symbol": sym,
        "shares": sh,
        "is_fractional": buy_fee_info["is_fractional"],
        "notional_usd": notional,
        "buy_fee": buy_fee,
        "sell_fee": sell_fee,
        "round_trip_fee": round_trip_fee,
        "gross_profit": gross_profit,
        "expected_net_profit": expected_net_profit,
        "gross_loss_at_stop": gross_loss_at_stop,
        "net_loss_at_stop": net_loss_at_stop,
        "fee_drag_pct": fee_drag_pct,
        "net_reward_risk": net_rr,
        "min_net_profit_usd": min_net_profit_usd,
        "buy_breakdown": buy_fee_info,
        "sell_breakdown": sell_fee_info,
        "reason": reason
    }


def evaluate_tiger_nz_order_plan(
    symbol: str,
    entry_price: float,
    stop_price: float,
    target_price: float,
    target_usd: float = 25.0,
    max_loss_usd: float = 1.50,
    min_net_profit_usd: float = 0.05,
    fractional_enabled: bool = True
) -> Dict[str, Any]:
    """
    Implements the Tiger Brokers NZ Fractional Share Trading Rule:
      1. Verifies fractional eligibility for the stock.
      2. Prefers fractional shares (< 1 share) whenever possible to avoid whole-share
         US$1.99/order minimums (US$3.98 round-trip).
      3. Enforces max_loss_per_trade_usd (including round-trip fees).
      4. Checks expected net profit after buy + sell + regulatory fees.
      5. Rejects if expected profit does not clear min_net_profit_usd or if whole-share
         fees make the trade uneconomical.
    """
    sym = str(symbol or "").strip().upper()
    entry_p = float(entry_price or 0.0)
    stop_p = float(stop_price or 0.0)
    target_p = float(target_price or 0.0)
    usd = float(target_usd or 25.0)

    support = check_fractional_support(sym, entry_p, usd)
    if not support["supported"]:
        return {
            "approved": False,
            "symbol": sym,
            "shares": 0.0,
            "order_mode": "rejected",
            "economics": None,
            "reason": support["reason"]
        }

    risk_per_share = entry_p - stop_p
    if risk_per_share <= 0 or target_p <= entry_p:
        return {
            "approved": False,
            "symbol": sym,
            "shares": 0.0,
            "order_mode": "rejected",
            "economics": None,
            "reason": f"Invalid geometry: entry=${entry_p:.2f}, stop=${stop_p:.2f}, target=${target_p:.2f}."
        }

    # Build candidate share quantities respecting max_loss_usd and fractional preference
    # Reserve ~$0.52 estimated round-trip fee out of max_loss_usd if fractional, or evaluate exact
    candidates = []

    if fractional_enabled:
        # Candidate A: Target USD (e.g. $25), capped by max_loss_usd
        sh_budget = round(usd / entry_p, 4)
        sh_risk = round(max(0.0, (max_loss_usd - 0.52)) / risk_per_share, 4)
        sh_a = min(sh_budget, sh_risk) if sh_risk > 0 else sh_budget
        if sh_a * entry_p >= 1.0:
            candidates.append(("fractional_budget", sh_a))

        # Candidate B: If price <= target_usd (so $25 buys >= 1 share), test < 1 share (0.9990)
        # to avoid triggering $1.99 whole-share minimum fees!
        if sh_budget >= 1.0:
            sh_sub_one = min(0.9990, sh_risk) if sh_risk > 0 else 0.9990
            if sh_sub_one * entry_p >= 1.0:
                candidates.append(("fractional_sub_one_cap", round(sh_sub_one, 4)))
    else:
        sh_whole = int(usd // entry_p)
        if sh_whole >= 1:
            candidates.append(("whole_shares", float(sh_whole)))

    best_eval = None
    best_mode = "rejected"
    for mode, sh in candidates:
        ev = preview_round_trip_economics(
            sym, sh, entry_p, stop_p, target_p,
            min_net_profit_usd=min_net_profit_usd,
            conservative_regulatory=True
        )
        if not ev.get("verified"):
            continue
        # Ensure total stop loss including fees stays within max_loss_usd
        within_loss = (ev["net_loss_at_stop"] <= max_loss_usd + 0.05)
        ev["within_max_loss"] = within_loss
        if ev["profitable"] and within_loss:
            if best_eval is None or ev["expected_net_profit"] > best_eval["expected_net_profit"]:
                best_eval = ev
                best_mode = mode

    if best_eval is not None:
        return {
            "approved": True,
            "symbol": sym,
            "shares": best_eval["shares"],
            "order_mode": best_mode,
            "is_fractional": best_eval["is_fractional"],
            "economics": best_eval,
            "reason": f"APPROVED ({best_mode}): {best_eval['reason']}"
        }

    # Neither candidate cleared profitability + max_loss; return primary preview as diagnostic
    diag_sh = candidates[0][1] if candidates else round(usd / entry_p, 4)
    diag = preview_round_trip_economics(
        sym, diag_sh, entry_p, stop_p, target_p,
        min_net_profit_usd=min_net_profit_usd,
        conservative_regulatory=True
    )
    diag["within_max_loss"] = (diag.get("net_loss_at_stop", 999.0) <= max_loss_usd + 0.05)
    reason = diag.get("reason", "Trade failed Tiger Brokers NZ fee & profitability check.")
    if diag.get("verified") and not diag["within_max_loss"]:
        reason += f" Stop loss + fees (${diag['net_loss_at_stop']:.2f}) exceeds max loss ${max_loss_usd:.2f}."
    if diag.get("verified") and not diag.get("is_fractional"):
        reason += " Whole-share order triggers higher US$1.99/leg minimum fees."

    return {
        "approved": False,
        "symbol": sym,
        "shares": diag_sh,
        "order_mode": "rejected",
        "is_fractional": diag.get("is_fractional", False),
        "economics": diag,
        "reason": reason
    }
