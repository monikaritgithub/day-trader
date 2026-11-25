#!/usr/bin/env python3
"""
Day Trader Autonomous Signal Scanner & Execution Engine
Usage:
  python3 scan_signals.py                          # Scan stocks & display BUY/SELL/HOLD signals
  python3 scan_signals.py --regular --interval 30  # Scan regularly by yourself (autonomous daemon)
  python3 scan_signals.py --buy TSLA --qty 8       # Buy stock using demo portfolio cash
  python3 scan_signals.py --sell TSLA              # Sell position back to demo portfolio cash
  python3 scan_signals.py --cash                   # Show demo portfolio cash & active positions
  python3 scan_signals.py --reset-cash 5000        # Reset demo cash to $5,000
"""

import sys
import os
import time
import json
import argparse
import subprocess
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
TRADER_DIR = Path(__file__).resolve().parent
STATE_DIR = TRADER_DIR / "state"

sys.path.insert(0, str(REPO_DIR))
from trader.signals import evaluate_stock_signal, enrich_watchlist_with_signals
from trader.pipeline import resolve_real_market_price

def read_json(path: Path, default=None):
    if not path.is_file():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def show_portfolio_cash():
    pf = read_json(TRADER_DIR / "portfolio.json", {"cash": 100.0, "positions": []})
    prices = read_json(TRADER_DIR / "prices.json", {})
    cash = float(pf.get("cash", 100.0))
    positions = pf.get("positions", [])

    print("\n" + "=" * 70)
    print(" 💼 DEMO PORTFOLIO CASH & POSITIONS (MAX $100 USD)")
    print("=" * 70)
    print(f" Available Demo Cash:  ${cash:,.2f} USD")
    
    total_equity = 0.0
    total_cost = 0.0
    if positions:
        print("\n Open Positions:")
        print(f" {'TICKER':<8} {'SHARES':<12} {'AVG COST':<12} {'MARK':<12} {'VALUE':<12} {'P&L ($)':<12} {'P&L (%)':<8}")
        print(" " + "-" * 68)
        for p in positions:
            sym = p.get("ticker", "UNKNOWN")
            sh = float(p.get("shares", 0))
            cost = sum(float(l.get("cost", 0)) for l in p.get("lots", [])) if p.get("lots") else sh * 100.0
            avg_cost = cost / sh if sh > 0 else 0.0
            
            curr_p = resolve_real_market_price(sym)
            if curr_p <= 0:
                curr_p = avg_cost
                
            val = sh * curr_p
            pnl = val - cost
            pnl_pct = (pnl / cost * 100) if cost > 0 else 0.0
            total_equity += val
            total_cost += cost
            
            pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
            pct_str = f"+{pnl_pct:.2f}%" if pnl >= 0 else f"{pnl_pct:.2f}%"
            print(f" {sym:<8} {sh:<12.4f} ${avg_cost:<11.2f} ${curr_p:<11.2f} ${val:<11.2f} {pnl_str:<12} {pct_str:<8}")
    else:
        print("\n Open Positions: None (100% in Demo Cash)")
        
    net_worth = cash + total_equity
    tot_pnl = total_equity - total_cost
    print(" " + "-" * 68)
    print(f" Total Account Value: ${net_worth:,.2f} USD  |  Unrealized P&L: {('+$' if tot_pnl >= 0 else '-$') + f'{abs(tot_pnl):.2f}'}")
    print("=" * 70 + "\n")

def execute_demo_buy(symbol: str, qty: Optional[float] = None, usd: Optional[float] = None, price: Optional[float] = None):
    symbol = symbol.upper()
    pf = read_json(TRADER_DIR / "portfolio.json", {"cash": 100.0, "positions": []})
    cash = float(pf.get("cash", 100.0))
    
    # Resolve price
    if not price:
        price = resolve_real_market_price(symbol)
        if price <= 0:
            plan = read_json(TRADER_DIR / "plan.json")
            if plan and plan.get("symbol") == symbol:
                price = float(plan.get("entry", 100.0))
            else:
                price = 100.0

    # Buying by USD amount
    if usd and usd > 0:
        usd = min(100.0, usd)
        qty = round(usd / price, 4)
    elif not qty or qty <= 0:
        usd = min(cash, 25.0)  # Default $25 USD
        qty = round(usd / price, 4)
        
    cost = round(qty * price, 2)
    if cash < cost:
        if cash <= 0.05:
            print(f"❌ ERROR: Insufficient demo cash! Available: ${cash:.2f} USD.")
            return False
        qty = round(cash / price, 4)
        cost = round(qty * price, 2)
        print(f"⚠️ Sized order to remaining cash: {qty:.4f} shares (${cost:.2f} USD).")

    # Execute paper fill using trader-broker/ticket.py
    cmd = [
        sys.executable, "trader-broker/ticket.py", "fill",
        "--symbol", symbol,
        "--side", "buy",
        "--qty", str(qty),
        "--price", str(round(price, 2))
    ]
    res = subprocess.run(cmd, cwd=str(REPO_DIR), capture_output=True, text=True)
    if res.returncode == 0:
        stop_price = round(price * 0.98, 2)
        target_price = round(price * 1.02, 2)
        alerts = read_json(TRADER_DIR / "alerts.json", {"rules": []})
        rules = alerts.get("rules", [])
        rules.append({"type": "stop", "symbol": symbol, "price": stop_price})
        rules.append({"type": "target", "symbol": symbol, "price": target_price})
        alerts["rules"] = rules
        write_json(TRADER_DIR / "alerts.json", alerts)
        
        updated_pf = read_json(TRADER_DIR / "portfolio.json", {})
        print(f"✅ EXECUTED BUY: {qty:.4f} shares of {symbol} @ ${price:.2f} USD (${cost:.2f} USD)")
        print(f"   Remaining Demo Cash: ${updated_pf.get('cash', 0):,.2f} USD")
        print(f"   Stop-Loss @ ${stop_price:.2f}  |  Target @ ${target_price:.2f}")
        return True
    else:
        print(f"❌ Buy fill failed: {res.stderr or res.stdout}")
        return False

def execute_demo_sell(symbol: str, qty: Optional[float] = None, usd: Optional[float] = None, percent: Optional[float] = None, price: Optional[float] = None):
    symbol = symbol.upper()
    pf = read_json(TRADER_DIR / "portfolio.json", {"cash": 100.0, "positions": []})
    positions = pf.get("positions", [])
    pos_match = next((p for p in positions if str(p.get("ticker", "")).upper() == symbol), None)
    
    if not pos_match:
        print(f"❌ ERROR: No open position for {symbol} found in demo portfolio.")
        return False
        
    held_shares = float(pos_match.get("shares", 0))

    # Resolve price
    if not price:
        price = resolve_real_market_price(symbol)
        if price <= 0:
            if pos_match.get("lots") and pos_match["lots"]:
                price = float(pos_match["lots"][0].get("cost", 0)) / float(held_shares)
            else:
                price = 100.0

    if usd and usd > 0:
        sell_qty = min(held_shares, round(usd / price, 4))
    elif percent and percent > 0:
        sell_qty = round(held_shares * (percent / 100.0), 4)
    elif qty and qty <= held_shares:
        sell_qty = round(qty, 4)
    else:
        sell_qty = held_shares

    cmd = [
        sys.executable, "trader-broker/ticket.py", "fill",
        "--symbol", symbol,
        "--side", "sell",
        "--qty", str(sell_qty),
        "--price", str(round(price, 2))
    ]
    res = subprocess.run(cmd, cwd=str(REPO_DIR), capture_output=True, text=True)
    if res.returncode == 0:
        proceeds = round(sell_qty * price, 2)
        alerts = read_json(TRADER_DIR / "alerts.json", {"rules": []})
        alerts["rules"] = [r for r in alerts.get("rules", []) if r.get("symbol") != symbol]
        write_json(TRADER_DIR / "alerts.json", alerts)
        
        updated_pf = read_json(TRADER_DIR / "portfolio.json", {})
        print(f"✅ EXECUTED SELL: {sell_qty:.4f} shares of {symbol} @ ${price:.2f} USD")
        print(f"   Proceeds Credited: ${proceeds:,.2f} USD  |  New Demo Cash: ${updated_pf.get('cash', 0):,.2f} USD")
        return True
    else:
        print(f"❌ Sell fill failed: {res.stderr or res.stdout}")
        return False

def run_scan_once(symbols: str = "TSLA,NVDA,AAPL,AMD,MSFT,AMZN,META,GOOGL,PLTR,SOFI"):
    import datetime, zoneinfo
    utc_now = datetime.datetime.now(datetime.timezone.utc)
    nz_tz = zoneinfo.ZoneInfo("Pacific/Auckland")
    nz_dt = utc_now.astimezone(nz_tz)
    
    print(f"\n🔍 Scanning stocks with Day Trader skills ({symbols})...")
    print(f" 🇳🇿 Auckland Time: {nz_dt.strftime('%I:%M:%S %p NZDT (%A)')} | Next Open: 03:30 AM NZDT | Flatten: 09:55 AM NZDT")
    
    # 1. Run trader-scanner daily or orb
    cmd = [sys.executable, "trader-scanner/scan.py", "daily", "--symbols", symbols]
    subprocess.run(cmd, cwd=str(REPO_DIR), capture_output=True, text=True)
    
    # 2. Load watchlist, portfolio, prices
    watchlist = read_json(TRADER_DIR / "watchlist.json", {"hits": []})
    portfolio = read_json(TRADER_DIR / "portfolio.json", {"cash": 100.0, "positions": []})
    prices = read_json(TRADER_DIR / "prices.json", {})
    plan = read_json(TRADER_DIR / "plan.json", {})
    entry = read_json(TRADER_DIR / "entry.json", {})
    timemachine = read_json(TRADER_DIR / "timemachine.json", {})
    risk = read_json(STATE_DIR / "risk.json", {})
    
    # Enrich watchlist (filtered to only day-trader-skill approved setups)
    watchlist = enrich_watchlist_with_signals(watchlist, portfolio, prices, approved_only=True)
    write_json(TRADER_DIR / "watchlist.json", watchlist)
    
    # Display visible BUY / SELL / HOLD table of approved trades
    print("\n" + "=" * 92)
    print(" ⚡ DAY TRADER SKILLS - APPROVED STOCKS & TRADES ONLY (R:R ≥ 1.0 • RISK CLEARED)")
    print("=" * 92)
    print(f" {'TICKER':<8} {'SIGNAL':<10} {'PRICE':<10} {'SETUP':<18} {'CONF':<8} {'ACTION RECOMMENDATION':<32}")
    print(" " + "-" * 90)
    
    hits = watchlist.get("hits", [])
    if not hits:
        # Fallback symbols check
        for sym in symbols.split(","):
            sym = sym.strip()
            sig = evaluate_stock_signal(sym, entry, plan, timemachine, risk, portfolio, prices)
            color_mark = "🟢" if sig["signal"] == "BUY" else ("🔴" if sig["signal"] == "SELL" else "🟡")
            rec = f"{sig['action']} ({sig['action_label']})"
            print(f" {sym:<8} {color_mark} {sig['signal']:<7} ${sig['curr_price']:<9.2f} {'Consolidation':<18} {sig['confidence']}%    {rec:<32}")
    else:
        for hit in hits:
            sym = hit.get("symbol", "")
            setups = hit.get("setups", ["breakout"])
            setup_str = setups[0].replace("_", " ") if setups else "breakout"
            price = float(hit.get("price", 0.0))
            
            sig = evaluate_stock_signal(sym, entry, plan, timemachine, risk, portfolio, prices, setup_name=setup_str)
            sig_name = sig["signal"]
            color_mark = "🟢" if sig_name == "BUY" else ("🔴" if sig_name == "SELL" else "🟡")
            rec = f"{sig['action_label']}"
            print(f" {sym:<8} {color_mark} {sig_name:<7} ${price:<9.2f} {setup_str:<18} {sig['confidence']}%    {rec:<32}")
            
    print("=" * 90)
    print(f" 💵 Demo Portfolio Cash Available: ${portfolio.get('cash', 5000.0):,.2f}")
    print(" To execute: run `python3 scan_signals.py --buy TICKER --qty N` or open the Web Dashboard.")
    print("=" * 90 + "\n")

def main():
    parser = argparse.ArgumentParser(description="Day Trader Signal Scanner & Demo Execution")
    parser.add_argument("--symbols", default="TSLA,NVDA,AAPL,AMD,MSFT,AMZN,META,GOOGL,PLTR,SOFI", help="Symbols to scan")
    parser.add_argument("--regular", action="store_true", help="Continuously scan regularly by yourself")
    parser.add_argument("--interval", type=int, default=30, help="Interval in seconds for regular scanning")
    parser.add_argument("--buy", help="Buy stock using demo portfolio cash (e.g. --buy TSLA)")
    parser.add_argument("--sell", help="Sell open position for demo cash (e.g. --sell TSLA)")
    parser.add_argument("--usd", type=float, help="USD dollar amount to buy/sell (e.g. --buy TSLA --usd 25)")
    parser.add_argument("--percent", type=float, help="Percentage of position to sell (e.g. --sell TSLA --percent 50)")
    parser.add_argument("--qty", type=float, help="Number of shares to buy/sell")
    parser.add_argument("--price", type=float, help="Explicit price override")
    parser.add_argument("--cash", action="store_true", help="Display demo portfolio cash balance")
    parser.add_argument("--reset-cash", type=float, help="Reset demo cash balance (e.g. --reset-cash 100)")
    args = parser.parse_args()

    if args.reset_cash is not None:
        target_cash = min(100.0, float(args.reset_cash))
        pf = read_json(TRADER_DIR / "portfolio.json", {"cash": 100.0, "positions": []})
        pf["cash"] = target_cash
        pf["positions"] = []
        write_json(TRADER_DIR / "portfolio.json", pf)
        cfg = read_json(TRADER_DIR / "config.json", {})
        cfg["budget"] = target_cash
        write_json(TRADER_DIR / "config.json", cfg)
        print(f"✅ Reset demo portfolio cash to ${target_cash:,.2f} USD (Max $100)")
        return

    if args.cash:
        show_portfolio_cash()
        return

    if args.buy:
        execute_demo_buy(args.buy, qty=args.qty, usd=args.usd, price=args.price)
        show_portfolio_cash()
        return

    if args.sell:
        execute_demo_sell(args.sell, qty=args.qty, usd=args.usd, percent=args.percent, price=args.price)
        show_portfolio_cash()
        return

    if args.regular:
        print(f"⚡ Starting continuous autonomous regular scanner (every {args.interval}s)... Press Ctrl+C to stop.")
        while True:
            try:
                run_scan_once(args.symbols)
                time.sleep(args.interval)
            except KeyboardInterrupt:
                print("\nAutonomous scan stopped.")
                break
    else:
        run_scan_once(args.symbols)

if __name__ == "__main__":
    main()
