#!/usr/bin/env python3
"""
Live Market State Publisher
Runs live US stock scanning, 11-skill auto-analysis, AutoTrader cycle,
real Yahoo Finance OHLCV charting, and live news/SEC 8-K collection,
writing sanitized live state to docs/live_state.json for real-time dashboards.
"""

import argparse
import datetime
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

REPO_DIR = Path(__file__).resolve().parent.parent
TRADER_DIR = REPO_DIR / "trader"
DOCS_DIR = REPO_DIR / "docs"
LIVE_STATE_FILE = DOCS_DIR / "live_state.json"

sys.path.insert(0, str(REPO_DIR))
from trader.auto_trader import get_auto_trader, read_json_safe, write_json_safe
from trader.chart_data import fetch_chart_data
from trader.gemini_news import fetch_live_headlines
from trader.pipeline import (
    get_all_11_skills_approved_stocks,
    resolve_real_market_price,
    run_day_trader_pipeline,
)
from trader.signals import enrich_watchlist_with_signals

PRIORITY_SYMBOLS = [
    "TSLA", "NVDA", "AAPL", "AMD", "PLTR", "SOFI", "GME", "MSFT",
    "AMZN", "META", "GOOGL", "COIN", "MARA", "INTC", "SMCI", "NFLX",
    "AVGO", "ORCL", "CRM", "HOOD", "RIVN", "BABA", "TSM", "ARM", "UBER"
]


def ensure_runtime_files() -> None:
    """Guarantee default paper config, portfolio, and history exist in fresh cloud/CI runners."""
    TRADER_DIR.mkdir(parents=True, exist_ok=True)
    cfg_path = TRADER_DIR / "config.json"
    if not cfg_path.is_file():
        sec_ua = os.environ.get("SEC_USER_AGENT", "DayTraderPro Station daytrader@example.com")
        write_json_safe(cfg_path, {
            "budget": 200.0,
            "cash_buffer_pct": 5,
            "max_position_pct": 25,
            "max_order_usd": 50.0,
            "target_order_usd": 25.0,
            "min_order_usd": 1.0,
            "min_net_profit_usd": 0.05,
            "max_loss_per_trade_usd": 1.5,
            "max_daily_loss_usd": 6.0,
            "max_trades_per_day": 4,
            "max_orders_per_day": 10,
            "min_reward_risk": 1.0,
            "require_stop": True,
            "no_entries_before": "09:45",
            "no_entries_after": "15:30",
            "flat_by": "15:55",
            "fractional": True,
            "broker": "tiger_nz",
            "paper": True,
            "blocked": [],
            "allow_options": False,
            "allow_margin": False,
            "allow_short": False,
            "pdt_guard": False,
            "sec_user_agent": sec_ua,
        })

    pf_path = TRADER_DIR / "portfolio.json"
    if not pf_path.is_file():
        write_json_safe(pf_path, {"cash": 200.0, "positions": []})

    th_path = TRADER_DIR / "trade_history.json"
    if not th_path.is_file():
        write_json_safe(th_path, {"trades": [], "starting_cash": 200.0, "max_daily_loss": 6.0})

    if not (TRADER_DIR / "universe.txt").is_file():
        try:
            subprocess.run(
                [sys.executable, "trader-scanner/scan.py", "universe"],
                cwd=str(REPO_DIR), capture_output=True, timeout=45
            )
        except Exception:
            pass


def refresh_live_quotes(symbols: List[str]) -> Dict[str, Any]:
    """Fetch fresh Yahoo v8 meta price and prev_close for all active symbols."""
    prices_doc = read_json_safe(TRADER_DIR / "prices.json", {}) or {}
    p_map = dict(prices_doc.get("prices") or {})
    detail = dict(prices_doc.get("detail") or {})
    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for sym in symbols:
        sym = sym.upper().strip()
        if not sym:
            continue
        for host in ("query2.finance.yahoo.com", "query1.finance.yahoo.com"):
            try:
                url = f"https://{host}/v8/finance/chart/{sym}?interval=5m&range=1d"
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=6) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                meta = payload["chart"]["result"][0]["meta"]
                px = float(meta.get("regularMarketPrice") or meta.get("chartPreviousClose") or 0.0)
                prev = float(meta.get("chartPreviousClose") or meta.get("previousClose") or px)
                if px > 0:
                    p_map[sym] = round(px, 2)
                    detail[sym] = {
                        "prev_close": round(prev, 2),
                        "pct": round(((px - prev) / prev) * 100.0, 2) if prev > 0 else 0.0,
                        "fetched": now_iso,
                        "source": "yahoo",
                    }
                break
            except Exception:
                continue

    prices_doc["as_of"] = now_iso
    prices_doc["source"] = "yahoo"
    prices_doc["prices"] = p_map
    prices_doc["detail"] = detail
    write_json_safe(TRADER_DIR / "prices.json", prices_doc)
    return prices_doc


def run_market_scan(engine, scan_batch: int = 300) -> Dict[str, Any]:
    """Scan priority + rolling US universe symbols with trader-scanner."""
    m_times = engine.get_market_times()
    mode = "orb" if m_times.get("is_orb_trading_active") else "daily"

    batch = engine.next_universe_batch(max(50, scan_batch))
    scan_syms = list(dict.fromkeys(PRIORITY_SYMBOLS + batch))

    prev_wl = read_json_safe(TRADER_DIR / "watchlist.json", {}) or {}
    prev_hits = {h.get("symbol"): h for h in prev_wl.get("hits", []) if h.get("symbol")}

    try:
        subprocess.run(
            [sys.executable, "trader-scanner/scan.py", mode, "--symbols", ",".join(scan_syms)],
            cwd=str(REPO_DIR), capture_output=True, text=True, timeout=75
        )
    except Exception:
        pass

    wl = read_json_safe(TRADER_DIR / "watchlist.json", {}) or {}
    cur_hits = wl.get("hits") or []
    # Merge rolling universe hits when today's scan didn't cover every stock
    merged = {h.get("symbol"): h for h in cur_hits if h.get("symbol")}
    if wl.get("as_of") == prev_wl.get("as_of"):
        for sym, hit in prev_hits.items():
            merged.setdefault(sym, hit)

    wl["hits"] = list(merged.values())
    wl["universe"] = len(engine.universe_symbols)
    wl["universe_cursor"] = engine.universe_pointer

    pf = read_json_safe(TRADER_DIR / "portfolio.json", {"cash": 200.0, "positions": []}) or {}
    px = read_json_safe(TRADER_DIR / "prices.json", {}) or {}
    wl = enrich_watchlist_with_signals(wl, pf, px)
    write_json_safe(TRADER_DIR / "watchlist.json", wl)
    return wl


def fetch_symbol_news(symbol: str) -> List[Dict[str, Any]]:
    """Collect real news + SEC 8-K filings via trader-news and Google News RSS."""
    items: List[Dict[str, Any]] = []
    try:
        proc = subprocess.run(
            [
                sys.executable, "trader-news/news.py",
                "--tickers", symbol, "--hours", "72", "--all",
                "--config", str(TRADER_DIR / "config.json"), "--json"
            ],
            cwd=str(REPO_DIR), capture_output=True, text=True, timeout=15
        )
        if proc.stdout.strip():
            doc = json.loads(proc.stdout)
            for it in doc.get("items", []):
                if it.get("title"):
                    items.append({
                        "title": it.get("title"),
                        "headline": it.get("title"),
                        "link": it.get("link") or it.get("url") or "#",
                        "url": it.get("link") or it.get("url") or "#",
                        "ticker": symbol,
                        "tickers": [symbol],
                        "time": it.get("time"),
                        "source": it.get("source") or "Market News",
                        "tags": it.get("tags") or ["live-feed", symbol],
                    })
    except Exception:
        pass

    if len(items) < 3:
        for it in fetch_live_headlines(symbol):
            if it.get("title") and not any(x["title"] == it["title"] for x in items):
                items.append(it)
    return items[:8]


def publish_live_state(run_auto_trade: bool = True, scan_batch: int = 300) -> Dict[str, Any]:
    ensure_runtime_files()
    engine = get_auto_trader()

    # 1. Scan US stocks & refresh watchlist
    watchlist = run_market_scan(engine, scan_batch=scan_batch)

    # 2. Gather target tickers (priority + scanner hits + currently held positions)
    portfolio = read_json_safe(TRADER_DIR / "portfolio.json", {"cash": 200.0, "positions": []}) or {}
    held_syms = [str(p.get("ticker", "")).upper() for p in portfolio.get("positions", []) if p.get("ticker")]
    hit_syms = [str(h.get("symbol", "")).upper() for h in watchlist.get("hits", []) if h.get("symbol")]
    active_syms = list(dict.fromkeys(PRIORITY_SYMBOLS[:15] + held_syms + hit_syms[:8]))[:22]

    # 3. Refresh real Yahoo market prices for active tickers
    prices_doc = refresh_live_quotes(active_syms)

    # 4. Run autonomous trading cycle (executes verified buys / target-stop exits / flat-by-close)
    cycle_info = {}
    if run_auto_trade:
        try:
            cycle_info = engine.run_cycle()
        except Exception as e:
            cycle_info = {"error": str(e)}

    # Reload updated portfolio & trade history after cycle
    portfolio = read_json_safe(TRADER_DIR / "portfolio.json", {"cash": 200.0, "positions": []}) or {}
    th_data = read_json_safe(TRADER_DIR / "trade_history.json", {"trades": [], "starting_cash": 200.0}) or {}
    trades = th_data.get("trades", [])
    starting_cash = float(th_data.get("starting_cash", 200.0))
    closed_trades = [t for t in trades if t.get("status") == "CLOSED" or str(t.get("side", "")).upper() == "SELL"]
    total_realized_pnl = round(sum(float(t.get("realized_pnl", 0.0)) for t in closed_trades), 2)
    wins = [t for t in closed_trades if float(t.get("realized_pnl", 0.0)) > 0]
    losses = [t for t in closed_trades if float(t.get("realized_pnl", 0.0)) < 0]
    win_rate = round((len(wins) / len(closed_trades)) * 100.0, 1) if closed_trades else 0.0
    total_fees = round(sum(float(t.get("tiger_fee", 0.0)) for t in trades), 2)

    # 5. Compute full 11-skill approved setups & per-ticker pipelines/charts/news (concurrently)
    from concurrent.futures import ThreadPoolExecutor

    approved_stocks = get_all_11_skills_approved_stocks(max_age=0.0)
    approved_syms = [s["symbol"] for s in approved_stocks if s.get("symbol")]
    publish_syms = list(dict.fromkeys(["TSLA", "NVDA", "AAPL", "AMD", "PLTR", "SOFI", "GME"] + held_syms + approved_syms + hit_syms[:5]))[:12]

    pipelines: Dict[str, Any] = {}
    charts: Dict[str, Any] = {}
    news_map: Dict[str, List[Dict[str, Any]]] = {}

    def _fetch_sym_io(sym: str):
        sym_news = []
        sym_charts = {}
        try:
            sym_news = fetch_symbol_news(sym)
        except Exception:
            sym_news = []
        for tf in ("1D", "1W", "1M", "1Y"):
            try:
                chart = fetch_chart_data(sym, tf)
                if chart and chart.get("candles"):
                    sym_charts[f"{sym}_{tf}"] = chart
            except Exception:
                pass
        return sym, sym_news, sym_charts

    with ThreadPoolExecutor(max_workers=6) as pool:
        for sym, sym_news, sym_charts in pool.map(_fetch_sym_io, publish_syms):
            news_map[sym] = sym_news
            charts.update(sym_charts)

    # Execute stateful 11-skill pipeline sequentially per ticker so shared entry/plan files never race
    for sym in publish_syms:
        try:
            sym_pip = run_day_trader_pipeline(
                symbol=sym, usd_amount=25.0, force_news=True, precomputed_approved=approved_stocks
            )
            if isinstance(sym_pip.get("gemini_news"), dict) and news_map.get(sym):
                sym_pip["gemini_news"]["news_items"] = news_map[sym]
            pipelines[sym] = sym_pip
        except Exception:
            pass

    m_times = engine.get_market_times()
    live_state = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_nzdt": m_times["nz_time_str"],
        "generated_et": m_times["ny_time_str"],
        "universe_count": len(engine.universe_symbols),
        "cycle": cycle_info,
        "prices": prices_doc,
        "watchlist": watchlist,
        "approved_stocks": approved_stocks,
        "portfolio": portfolio,
        "trades_summary": {
            "trades": trades,
            "summary": {
                "total_realized_pnl": total_realized_pnl,
                "total_pnl_pct": round((total_realized_pnl / starting_cash) * 100.0, 2) if starting_cash > 0 else 0.0,
                "win_rate": win_rate,
                "wins_count": len(wins),
                "losses_count": len(losses),
                "total_tiger_fees": total_fees,
                "current_cash": float(portfolio.get("cash", starting_cash)),
                "starting_cash": starting_cash,
            },
        },
        "pipelines": pipelines,
        "charts": charts,
        "news": news_map,
    }

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    write_json_safe(LIVE_STATE_FILE, live_state)
    return live_state


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Publish live US market state JSON for Day Trader dashboard")
    parser.add_argument("--no-auto-trade", action="store_true", help="Skip AutoTrader buy/sell execution")
    parser.add_argument("--scan-batch", type=int, default=300, help="Rolling US universe batch size to scan")
    args = parser.parse_args()
    state = publish_live_state(run_auto_trade=not args.no_auto_trade, scan_batch=args.scan_batch)
    print(json.dumps({
        "generated_at": state["generated_at"],
        "universe_count": state["universe_count"],
        "prices_count": len((state.get("prices") or {}).get("prices") or {}),
        "watchlist_hits": len((state.get("watchlist") or {}).get("hits") or []),
        "approved_stocks": [s.get("symbol") for s in state.get("approved_stocks") or []],
        "pipelines": list((state.get("pipelines") or {}).keys()),
        "charts": len(state.get("charts") or {}),
        "trades_count": len((state.get("trades_summary") or {}).get("trades") or []),
    }, indent=2))
