"""
24/7 Autonomous Day Trader Engine
Executes non-stop scanning, 11-skill verification, automated order execution,
risk management, Tiger Brokers NZ fee calculations, and daily closing statements.
"""

import os
import sys
import json
import time
import subprocess
import datetime
import zoneinfo
from pathlib import Path
from typing import Dict, Any, List, Optional

REPO_DIR = Path(__file__).resolve().parent.parent
TRADER_DIR = REPO_DIR / "trader"
STATE_DIR = TRADER_DIR / "state"

sys.path.insert(0, str(REPO_DIR))
from trader.tiger_fees import calculate_tiger_nz_fee, evaluate_tiger_nz_order_plan
from trader.daily_reporter import send_daily_market_close_report, load_env
from trader.pipeline import resolve_real_market_price, get_all_11_skills_approved_stocks

NYSE_HOLIDAYS = {
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
    "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31",
    "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
}
NYSE_EARLY_CLOSE = {"2026-11-27", "2026-12-24", "2027-11-26"}

load_env()

# State paths
PORTFOLIO_FILE = TRADER_DIR / "portfolio.json"
HISTORY_FILE = TRADER_DIR / "trade_history.json"
CONFIG_FILE = TRADER_DIR / "config.json"
WATCHLIST_FILE = TRADER_DIR / "watchlist.json"
ALERTS_FILE = TRADER_DIR / "alerts.json"
UNIVERSE_FILE = TRADER_DIR / "universe.txt"
AUTOTRADER_STATE_FILE = STATE_DIR / "autotrader_state.json"

def read_json_safe(path: Path, default=None):
    if not path.is_file():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def write_json_safe(path: Path, data: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

class AutoTraderEngine:
    def __init__(self):
        self.load_configuration()
        self.universe_symbols = self._load_universe_pool()
        persisted = read_json_safe(AUTOTRADER_STATE_FILE, {}) or {}
        self.universe_pointer = int(persisted.get("universe_pointer", 0))
        self.last_email_date_sent = persisted.get("last_email_sent_date")

    def load_configuration(self):
        load_env()
        cfg = read_json_safe(CONFIG_FILE, {}) or {}
        self.initial_capital = float(os.environ.get("INITIAL_CAPITAL", cfg.get("budget", 200.0)))
        self.max_positions = int(os.environ.get("MAX_POSITIONS", cfg.get("max_trades_per_day", 4)))
        self.max_order_usd = float(os.environ.get("MAX_ORDER_USD", cfg.get("max_order_usd", 50.0)))
        self.target_order_usd = float(os.environ.get("TARGET_ORDER_USD", min(25.0, self.max_order_usd)))
        self.max_loss_per_trade = float(os.environ.get("MAX_LOSS_PER_TRADE_USD", cfg.get("max_loss_per_trade_usd", 1.50)))
        self.max_daily_loss = float(os.environ.get("MAX_DAILY_LOSS_USD", cfg.get("max_daily_loss_usd", 6.00)))
        self.max_trades_per_day = int(cfg.get("max_trades_per_day", 4))
        self.min_net_profit_usd = float(cfg.get("min_net_profit_usd", 0.05))
        self.fractional_enabled = bool(cfg.get("fractional", True))
        self.auto_trading_enabled = os.environ.get("AUTO_TRADING_ENABLED", "true").lower() == "true"

    def _load_universe_pool(self) -> List[str]:
        """Loads ALL US-listed stocks from trader/universe.txt (built by trader-scanner)."""
        priority_pool = [
            "TSLA", "NVDA", "AAPL", "AMD", "MSFT", "AMZN", "META", "GOOGL", "PLTR", "SOFI",
            "MARA", "COIN", "SMCI", "F", "RIVN", "AAL", "NIO", "LCID", "WBD", "SNAP",
            "PFE", "BABA", "TSM", "UBER", "INTC", "PYPL", "HOOD", "GME", "AMC", "ARM"
        ]
        pool = list(priority_pool)
        seen = set(pool)
        if not UNIVERSE_FILE.is_file():
            try:
                subprocess.run(
                    [sys.executable, "trader-scanner/scan.py", "universe"],
                    cwd=str(REPO_DIR), capture_output=True, timeout=25
                )
            except Exception:
                pass
        if UNIVERSE_FILE.is_file():
            try:
                with open(UNIVERSE_FILE, "r", encoding="utf-8") as f:
                    for line in f:
                        if "|" in line:
                            sym = line.split("|", 1)[0].strip()
                            if sym and sym not in seen and "." not in sym:
                                pool.append(sym)
                                seen.add(sym)
            except Exception:
                pass
        return pool

    def next_universe_batch(self, batch_size: int = 100) -> List[str]:
        """Returns the next rolling batch across ALL US-listed stocks in universe.txt."""
        if not self.universe_symbols:
            self.universe_symbols = self._load_universe_pool()
        total = len(self.universe_symbols)
        if total == 0:
            return []
        start = self.universe_pointer % total
        end = start + batch_size
        if end <= total:
            batch = self.universe_symbols[start:end]
        else:
            batch = self.universe_symbols[start:] + self.universe_symbols[: end - total]
        self.universe_pointer = end % total
        return batch

    def get_market_times(self) -> Dict[str, Any]:
        """Calculates exact NZDT/NZST and NY times, honoring NYSE holidays and early closes."""
        utc_now = datetime.datetime.now(datetime.timezone.utc)
        ny_tz = zoneinfo.ZoneInfo("America/New_York")
        nz_tz = zoneinfo.ZoneInfo("Pacific/Auckland")
        ny_dt = utc_now.astimezone(ny_tz)
        nz_dt = utc_now.astimezone(nz_tz)

        ny_date_iso = ny_dt.date().isoformat()
        is_trading_day = (ny_dt.weekday() < 5) and (ny_date_iso not in NYSE_HOLIDAYS)
        is_early_close = ny_date_iso in NYSE_EARLY_CLOSE
        ny_minutes = ny_dt.hour * 60 + ny_dt.minute

        market_open_ny = 9 * 60 + 30
        orb_complete_ny = 9 * 60 + 45
        market_close_ny = (13 * 60) if is_early_close else (16 * 60)
        entry_cutoff_ny = (12 * 60 + 30) if is_early_close else (15 * 60 + 30)
        flat_by_ny = market_close_ny - 5

        is_market_open = is_trading_day and (market_open_ny <= ny_minutes < market_close_ny)
        is_orb_trading_active = is_trading_day and (orb_complete_ny <= ny_minutes < entry_cutoff_ny)
        # Active from flat_by (15:55 / 12:55 half-day) through end of NY day so scheduled cycles never miss flattening
        is_flat_by_time = is_trading_day and (ny_minutes >= flat_by_ny)
        is_close_reporting_time = is_trading_day and (ny_minutes >= flat_by_ny and ny_minutes <= market_close_ny + 90)

        return {
            "utc_now": utc_now,
            "ny_dt": ny_dt,
            "nz_dt": nz_dt,
            "nz_time_str": nz_dt.strftime("%Y-%m-%d %I:%M:%S %p NZDT"),
            "nz_date_str": nz_dt.strftime("%Y-%m-%d"),
            "ny_time_str": ny_dt.strftime("%Y-%m-%d %I:%M:%S %p ET"),
            "is_weekday_ny": is_trading_day,
            "is_market_open": is_market_open,
            "is_orb_trading_active": is_orb_trading_active,
            "is_flat_by_time": is_flat_by_time,
            "is_close_reporting_time": is_close_reporting_time
        }

    def execute_buy(self, symbol: str, entry_price: float, stop_price: float, target_price: float, usd_amount: float = 25.0) -> Optional[Dict[str, Any]]:
        """
        Executes automated BUY following the Tiger Brokers NZ Fractional Share Trading Rule:
        - Prioritizes fractional shares (< 1 share where possible) for US$25 target orders
        - Previews round-trip buy + sell + regulatory fees
        - Rejects trades where expected net profit after fees < min_net_profit_usd
        - Enforces max_loss_per_trade_usd (including fees)
        """
        portfolio = read_json_safe(PORTFOLIO_FILE, {"cash": self.initial_capital, "positions": []})
        cash = float(portfolio.get("cash", self.initial_capital))

        budget_usd = min(float(usd_amount), self.max_order_usd, cash)
        if budget_usd < 1.0 or cash < 1.0:
            return None

        # Enforce Tiger Brokers NZ Fractional & Net-Profit-After-Fees Safeguard
        plan_eval = evaluate_tiger_nz_order_plan(
            symbol=symbol,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            target_usd=budget_usd,
            max_loss_usd=self.max_loss_per_trade,
            min_net_profit_usd=self.min_net_profit_usd,
            fractional_enabled=self.fractional_enabled,
        )
        if not plan_eval.get("approved"):
            return None

        shares = float(plan_eval["shares"])
        if shares <= 0:
            return None

        trade_val = round(shares * entry_price, 2)
        fee_calc = calculate_tiger_nz_fee("BUY", shares, entry_price)
        tiger_fee = fee_calc["total_fee"]
        total_cost = round(trade_val + tiger_fee, 2)

        if cash < total_cost:
            return None

        # Deduct cash and add position
        m_times = self.get_market_times()
        ny_date_iso = m_times["ny_dt"].date().isoformat()
        portfolio["cash"] = round(cash - total_cost, 2)
        existing_pos = next((p for p in portfolio.get("positions", []) if p.get("ticker") == symbol), None)
        if existing_pos:
            existing_pos["shares"] = round(float(existing_pos.get("shares", 0)) + shares, 4)
            existing_pos.setdefault("lots", []).append({
                "id": f"{symbol}-{int(time.time())}",
                "date": ny_date_iso,
                "shares": shares,
                "cost": total_cost,
                "entry_price": entry_price,
                "stop_price": stop_price,
                "target_price": target_price,
                "tiger_fee": tiger_fee
            })
        else:
            portfolio.setdefault("positions", []).append({
                "ticker": symbol,
                "shares": shares,
                "lots": [{
                    "id": f"{symbol}-{int(time.time())}",
                    "date": ny_date_iso,
                    "shares": shares,
                    "cost": total_cost,
                    "entry_price": entry_price,
                    "stop_price": stop_price,
                    "target_price": target_price,
                    "tiger_fee": tiger_fee
                }]
            })
        write_json_safe(PORTFOLIO_FILE, portfolio)

        # Update alerts
        alerts = read_json_safe(ALERTS_FILE, {"rules": []})
        rules = [r for r in alerts.get("rules", []) if r.get("symbol") != symbol]
        rules.append({"type": "stop", "symbol": symbol, "price": stop_price})
        rules.append({"type": "target", "symbol": symbol, "price": target_price})
        alerts["rules"] = rules
        write_json_safe(ALERTS_FILE, alerts)

        # Record in trade_history.json
        th_data = read_json_safe(HISTORY_FILE, {"trades": [], "starting_cash": self.initial_capital})
        trade_id = f"TRD-{int(time.time())}"
        trade_entry = {
            "id": trade_id,
            "timestamp_nzdt": m_times["nz_time_str"],
            "timestamp_et": m_times["ny_time_str"],
            "symbol": symbol,
            "side": "BUY",
            "shares": shares,
            "price": entry_price,
            "cost": total_cost,
            "tiger_fee": tiger_fee,
            "proceeds": 0.0,
            "realized_pnl": 0.0,
            "realized_pnl_pct": 0.0,
            "status": "OPEN",
            "exit_reason": None,
            "notes": f"Auto 15m ORB Entry at ${entry_price:.2f} (Midpoint Stop: ${stop_price:.2f}, Target: ${target_price:.2f})"
        }
        th_data.setdefault("trades", []).insert(0, trade_entry)
        write_json_safe(HISTORY_FILE, th_data)

        return trade_entry

    def execute_sell(self, symbol: str, shares: float, price: float, exit_reason: str, buy_fee: float = 0.0) -> Optional[Dict[str, Any]]:
        """Executes SELL with Tiger Brokers NZ fees deducted and net PnL calculated."""
        portfolio = read_json_safe(PORTFOLIO_FILE, {"cash": self.initial_capital, "positions": []})
        positions = portfolio.get("positions", [])
        pos = next((p for p in positions if p.get("ticker") == symbol), None)
        if not pos:
            return None

        held_shares = float(pos.get("shares", 0))
        sell_shares = min(held_shares, round(shares, 4))
        if sell_shares <= 0:
            return None

        # Cost basis calculation
        cost_basis = 0.0
        lot_buy_fee = buy_fee
        if pos.get("lots") and pos["lots"]:
            lot = pos["lots"][0]
            lot_cost = float(lot.get("cost", 0))
            cost_basis = round((lot_cost / held_shares) * sell_shares, 2)
            lot_buy_fee = float(lot.get("tiger_fee", 0.0))
        else:
            cost_basis = round(price * sell_shares, 2)

        # Tiger Brokers NZ SELL fee calculation
        fee_calc = calculate_tiger_nz_fee("SELL", sell_shares, price)
        tiger_fee = fee_calc["total_fee"]
        gross_proceeds = round(sell_shares * price, 2)
        net_proceeds = round(gross_proceeds - tiger_fee, 2)

        # Net Realized PnL = Net Proceeds - Cost Basis
        realized_pnl = round(net_proceeds - cost_basis, 2)
        realized_pnl_pct = round((realized_pnl / cost_basis) * 100, 2) if cost_basis > 0 else 0.0

        # Update cash & remove/reduce position
        portfolio["cash"] = round(float(portfolio.get("cash", 0)) + net_proceeds, 2)
        new_shares = round(held_shares - sell_shares, 4)
        if new_shares <= 1e-5:
            portfolio["positions"] = [p for p in positions if p.get("ticker") != symbol]
            # Clean alerts
            alerts = read_json_safe(ALERTS_FILE, {"rules": []})
            alerts["rules"] = [r for r in alerts.get("rules", []) if r.get("symbol") != symbol]
            write_json_safe(ALERTS_FILE, alerts)
        else:
            pos["shares"] = new_shares

        write_json_safe(PORTFOLIO_FILE, portfolio)

        # Record in trade_history.json
        th_data = read_json_safe(HISTORY_FILE, {"trades": [], "starting_cash": self.initial_capital})
        m_times = self.get_market_times()
        trade_id = f"TRD-{int(time.time())}"
        trade_entry = {
            "id": trade_id,
            "timestamp_nzdt": m_times["nz_time_str"],
            "timestamp_et": m_times["ny_time_str"],
            "symbol": symbol,
            "side": "SELL",
            "shares": sell_shares,
            "price": price,
            "cost": cost_basis,
            "tiger_fee": tiger_fee,
            "proceeds": net_proceeds,
            "realized_pnl": realized_pnl,
            "realized_pnl_pct": realized_pnl_pct,
            "status": "CLOSED",
            "exit_reason": exit_reason,
            "notes": f"Liquidated {sell_shares:.4f} shares @ ${price:.2f} (Net: ${net_proceeds:.2f}, Tiger Fee: ${tiger_fee:.2f})"
        }
        th_data.setdefault("trades", []).insert(0, trade_entry)
        write_json_safe(HISTORY_FILE, th_data)

        return trade_entry

    def monitor_open_positions(self, is_flat_time: bool = False):
        """Monitors open positions against live market price, stop loss, take profit, and overnight flat rules."""
        portfolio = read_json_safe(PORTFOLIO_FILE, {"cash": self.initial_capital, "positions": []})
        positions = list(portfolio.get("positions", []))
        ny_today_iso = self.get_market_times()["ny_dt"].date().isoformat()

        for pos in positions:
            sym = pos.get("ticker")
            shares = float(pos.get("shares", 0))
            if not sym or shares <= 0:
                continue

            current_price = resolve_real_market_price(sym)
            lots = pos.get("lots", [])
            lot = lots[0] if lots else {}
            lot_date = str(lot.get("date") or ny_today_iso)
            stop_price = float(lot.get("stop_price", current_price * 0.98))
            target_price = float(lot.get("target_price", current_price * 1.02))

            if is_flat_time or lot_date < ny_today_iso:
                # Mandatory 09:55 AM NZDT / 15:55 ET flat close — zero overnight hold!
                self.execute_sell(sym, shares, current_price, "09:55 Flat-by-Close Rule")
            elif current_price >= target_price:
                self.execute_sell(sym, shares, current_price, "Profit Target Reached")
            elif current_price <= stop_price:
                self.execute_sell(sym, shares, current_price, "Midpoint Stop Cut Loss")

    def execute_skill_verified_buy(self, stock: Dict[str, Any], usd_to_use: float) -> Optional[Dict[str, Any]]:
        """
        Runs the Day Trading Skills pipeline before placing an automated paper BUY:
        trader-news -> trader-entry -> trader-exit -> trader-timemachine ->
        trader-budget (size.py) -> trader-risk (check.py) -> trader-alerts.
        """
        sym = str(stock.get("symbol", "")).upper().strip()
        if not sym:
            return None

        # 1. trader-news: abort if dangerous catalyst (halt, bankruptcy, delist, offering)
        try:
            news_proc = subprocess.run(
                [sys.executable, "trader-news/news.py", "--tickers", sym, "--hours", "24", "--no-moves", "--json"],
                cwd=str(REPO_DIR), capture_output=True, text=True, timeout=10
            )
            if news_proc.stdout.strip():
                news_doc = json.loads(news_proc.stdout)
                for item in news_doc.get("items", []):
                    tags = set(item.get("tags", []))
                    if tags & {"halt", "risk"}:
                        return None
        except Exception:
            pass

        # 2. trader-entry: require confirmed closed-bar ORB breakout
        try:
            e_proc = subprocess.run(
                [sys.executable, "trader-entry/entry.py", "check", sym, "--setup", "orb", "--write"],
                cwd=str(REPO_DIR), capture_output=True, text=True, timeout=10
            )
            if e_proc.returncode != 0:
                return None
        except Exception:
            return None

        entry_p = float(stock.get("entry", 0))
        stop_p = float(stock.get("stop", 0))
        target_p = float(stock.get("target", 0))
        target_r = int(round(float(stock.get("target_r", 2))))

        # 3. trader-exit: write formal exit plan
        try:
            x_proc = subprocess.run(
                [
                    sys.executable, "trader-exit/exit.py", "plan",
                    "--stop", "or-mid", "--target", f"{target_r}R", "--write"
                ],
                cwd=str(REPO_DIR), capture_output=True, text=True, timeout=8
            )
            if x_proc.returncode != 0:
                return None
        except Exception:
            return None

        # 4. trader-timemachine: 60-day Monte Carlo check up to flat_by
        flat_by_str = str((read_json_safe(CONFIG_FILE, {}) or {}).get("flat_by", "15:55"))
        if m_times_now := self.get_market_times():
            if m_times_now["ny_dt"].date().isoformat() in NYSE_EARLY_CLOSE:
                flat_by_str = "12:55"
        try:
            subprocess.run(
                [sys.executable, "trader-timemachine/timemachine.py", "run", "--until", flat_by_str, "--replays", "2000", "--seed", "19", "--write"],
                cwd=str(REPO_DIR), capture_output=True, timeout=12
            )
        except Exception:
            pass

        # 5. trader-budget + trader-risk: formal fractional bracket sizing (respecting $25 target budget) & risk check
        try:
            b_proc = subprocess.run(
                [sys.executable, "trader-budget/size.py", "--limit", "--budget", str(round(min(200.0, usd_to_use * 4.0), 2)), "--write"],
                cwd=str(REPO_DIR), capture_output=True, text=True, timeout=8
            )
            if b_proc.returncode != 0:
                return None
            r_proc = subprocess.run(
                [sys.executable, "trader-risk/check.py"],
                cwd=str(REPO_DIR), capture_output=True, text=True, timeout=8
            )
            if r_proc.returncode != 0:
                return None
        except Exception:
            return None

        # 6. Execute fractional paper buy + arm trader-alerts
        trade = self.execute_buy(sym, entry_p, stop_p, target_p, usd_amount=usd_to_use)
        if trade:
            try:
                subprocess.run(
                    [sys.executable, "trader-alerts/alerts.py", "add", "--from-plan"],
                    cwd=str(REPO_DIR), capture_output=True, timeout=8
                )
            except Exception:
                pass
        return trade

    def run_cycle(self) -> Dict[str, Any]:
        """Runs a complete autonomous cycle using all 11 Day Trading skills."""
        self.load_configuration()
        m_times = self.get_market_times()
        today_nz = m_times["nz_date_str"]

        # 1. Check Mandatory Flat-by-close or stale prior-day positions
        pf_check = read_json_safe(PORTFOLIO_FILE, {"positions": []}) or {"positions": []}
        if pf_check.get("positions"):
            self.monitor_open_positions(is_flat_time=m_times["is_flat_by_time"])

        # 2. Check Daily Market Close Email Report
        if m_times["is_close_reporting_time"] and self.last_email_date_sent != today_nz:
            try:
                res = send_daily_market_close_report()
                if res.get("success"):
                    self.last_email_date_sent = today_nz
                    write_json_safe(AUTOTRADER_STATE_FILE, {
                        "last_email_sent_date": today_nz,
                        "universe_pointer": self.universe_pointer
                    })
            except Exception:
                pass

        # 3. If within active ORB trading window, monitor positions & scan US universe
        if m_times["is_orb_trading_active"] and self.auto_trading_enabled:
            self.monitor_open_positions(is_flat_time=False)

            # Refresh ORB watchlist if stale (>180s) so standalone cron/GitHub Actions discovers live breakouts across US market
            wl_stale = True
            if WATCHLIST_FILE.is_file():
                wl_age = time.time() - WATCHLIST_FILE.stat().st_mtime
                if wl_age < 180.0:
                    wl_stale = False
            if wl_stale:
                try:
                    batch = self.next_universe_batch(300)
                    if batch:
                        prev_wl = read_json_safe(WATCHLIST_FILE, {}) or {}
                        prev_hits = {h.get("symbol"): h for h in prev_wl.get("hits", []) if h.get("symbol")}
                        subprocess.run(
                            [sys.executable, "trader-scanner/scan.py", "orb", "--symbols", ",".join(batch)],
                            cwd=str(REPO_DIR), capture_output=True, timeout=45
                        )
                        new_wl = read_json_safe(WATCHLIST_FILE, {}) or {}
                        for h in new_wl.get("hits", []):
                            if h.get("symbol"):
                                prev_hits[h["symbol"]] = h
                        new_wl["hits"] = list(prev_hits.values())
                        write_json_safe(WATCHLIST_FILE, new_wl)
                except Exception:
                    pass

            portfolio = read_json_safe(PORTFOLIO_FILE, {"cash": self.initial_capital, "positions": []})
            current_positions = portfolio.get("positions", [])
            held_symbols = {p.get("ticker") for p in current_positions}
            cash = float(portfolio.get("cash", 0))

            th_data = read_json_safe(HISTORY_FILE, {"trades": []}) or {"trades": []}
            today_trades_list = [
                t for t in th_data.get("trades", [])
                if str(t.get("timestamp_nzdt", "")).startswith(today_nz)
            ]
            entries_today = sum(1 for t in today_trades_list if t.get("side") == "BUY")
            realized_loss_today = sum(
                max(0.0, -float(t.get("realized_pnl", 0.0)))
                for t in today_trades_list if t.get("side") == "SELL"
            )

            if (
                len(current_positions) < self.max_positions
                and entries_today < self.max_trades_per_day
                and realized_loss_today < self.max_daily_loss
                and cash >= 10.0
            ):
                approved_stocks = get_all_11_skills_approved_stocks()
                for stock in approved_stocks:
                    sym = stock.get("symbol")
                    if sym not in held_symbols and stock.get("status") == "APPROVED":
                        entry_p = float(stock.get("entry", 0))
                        curr_p = float(stock.get("price", entry_p))
                        if curr_p >= (entry_p * 0.998):
                            usd_to_use = min(self.target_order_usd, self.max_order_usd, cash * 0.5)
                            if usd_to_use >= 1.0:
                                self.execute_skill_verified_buy(stock, usd_to_use)
                                break

        return {
            "status": "cycle_completed",
            "nz_time": m_times["nz_time_str"],
            "is_open": m_times["is_market_open"],
            "is_orb_active": m_times["is_orb_trading_active"],
            "open_positions": len(read_json_safe(PORTFOLIO_FILE, {}).get("positions", [])),
            "cash": read_json_safe(PORTFOLIO_FILE, {}).get("cash", self.initial_capital)
        }

_ENGINE = None
def get_auto_trader() -> AutoTraderEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = AutoTraderEngine()
    return _ENGINE

def run_auto_trader_cycle() -> Dict[str, Any]:
    engine = get_auto_trader()
    return engine.run_cycle()

if __name__ == "__main__":
    eng = AutoTraderEngine()
    result = eng.run_cycle()
    print("AutoTrader Cycle Result:", json.dumps(result, indent=2))
