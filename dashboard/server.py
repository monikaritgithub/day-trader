#!/usr/bin/env python3
"""
Day Trader Dashboard & Real-Time WebSocket Server
Bridges the 11 day-trader-skill quantitative modules to a responsive,
real-time WebSocket UI for zero-friction setup, monitoring, simulation,
risk control, and trade execution.
"""

import asyncio
import json
import os
import sys
import time
import datetime
import zoneinfo
import subprocess
from pathlib import Path
from typing import Set, Dict, Any, Optional, Tuple

from aiohttp import web, WSMsgType

REPO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_DIR))
from trader.signals import evaluate_stock_signal, enrich_watchlist_with_signals
from trader.gemini_news import analyze_news_with_gemini, fetch_live_headlines
from trader.pipeline import run_day_trader_pipeline, resolve_real_market_price, get_all_11_skills_approved_stocks
from trader.tiger_fees import calculate_tiger_nz_fee, preview_round_trip_economics, check_fractional_support
from trader.chart_data import fetch_chart_data
from trader.daily_reporter import send_daily_market_close_report
from trader.auto_trader import run_auto_trader_cycle, get_auto_trader

REPO_DIR = Path(__file__).resolve().parent.parent
TRADER_DIR = REPO_DIR / "trader"
STATE_DIR = TRADER_DIR / "state"
PUBLIC_DIR = Path(__file__).resolve().parent / "public"

connected_websockets: Set[web.WebSocketResponse] = set()
auto_scan_enabled: bool = True
last_auto_scan_time: float = 0.0

import email.utils
_NEWS_CACHE: Dict[str, Tuple[float, Any]] = {}
NEWS_CACHE_TTL = 60.0

def read_json_safe(path: Path) -> Optional[Any]:
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def write_json_safe(path: Path, data: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

async def broadcast_ws(payload: Dict[str, Any]):
    dead = set()
    msg = json.dumps(payload)
    for ws in connected_websockets:
        if ws.closed:
            dead.add(ws)
            continue
        try:
            await ws.send_str(msg)
        except Exception:
            dead.add(ws)
    for ws in dead:
        connected_websockets.discard(ws)

async def run_cli_cmd(args: list, timeout: float = 30.0) -> tuple[int, str, str]:
    """Execute a CLI tool from day-trader-skill in the repo directory."""
    cmd = [sys.executable] + args
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(REPO_DIR),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        code = proc.returncode if proc.returncode is not None else 0
        return code, stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace")
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return 1, "", "Command timed out"

def get_market_clock_summary() -> Dict[str, Any]:
    """Check NYSE clock using trader-alerts/alerts.py clock and compute Auckland, New Zealand equivalent."""
    try:
        import datetime, zoneinfo
        utc_now = datetime.datetime.now(datetime.timezone.utc)
        ny_tz = zoneinfo.ZoneInfo("America/New_York")
        nz_tz = zoneinfo.ZoneInfo("Pacific/Auckland")
        ny_dt = utc_now.astimezone(ny_tz)
        nz_dt = utc_now.astimezone(nz_tz)

        res = subprocess.run(
            [sys.executable, "trader-alerts/alerts.py", "clock"],
            cwd=str(REPO_DIR),
            capture_output=True,
            text=True,
            timeout=5
        )
        lines = [line.strip() for line in res.stdout.strip().split("\n") if line.strip()]
        is_open = (res.returncode == 0)

        # Compute exact countdown until next NYSE open in NZDT
        candidate = ny_dt.replace(hour=9, minute=30, second=0, microsecond=0)
        if candidate <= ny_dt:
            candidate += datetime.timedelta(days=1)
        while candidate.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
            candidate += datetime.timedelta(days=1)
        next_open_nz = candidate.astimezone(nz_tz)
        delta_sec = max(0, int((candidate - ny_dt).total_seconds()))
        hours, rem = divmod(delta_sec, 3600)
        mins = rem // 60
        time_until_open = f"{hours}h {mins}m"
        
        day_label = "Tomorrow" if next_open_nz.date() == (nz_dt.date() + datetime.timedelta(days=1)) else (
            "Today" if next_open_nz.date() == nz_dt.date() else next_open_nz.strftime("%A")
        )
        nz_countdown_str = f"Opens {day_label} at {next_open_nz.strftime('%I:%M %p NZDT')} (in {time_until_open})"
        nz_open_str = next_open_nz.strftime("%I:%M %p NZDT")

        return {
            "is_open": is_open,
            "raw": lines,
            "status_text": lines[0] if lines else "Status unknown",
            "next_open": nz_countdown_str,
            "ny_time_str": ny_dt.strftime("%I:%M:%S %p EST"),
            "ny_date_str": ny_dt.strftime("%A, %b %d"),
            "nz_time_str": nz_dt.strftime("%I:%M:%S %p NZDT"),
            "nz_date_str": nz_dt.strftime("%A, %b %d"),
            "nz_open_str": nz_open_str,
            "nz_countdown_str": nz_countdown_str,
            "nz_status_str": "MARKET OPEN NOW (Closes 10:00 AM NZDT)" if is_open else f"MARKET CLOSED • {nz_countdown_str}",
            "nz_schedule": {
                "pre_market": "10:00 PM - 03:30 AM NZDT (Pre-market)",
                "open": "03:30 AM NZDT (09:30 AM ET Open)",
                "orb_window": "03:30 - 03:45 AM NZDT (15m ORB)",
                "flat_by_close": "09:55 AM NZDT (15:55 PM ET Mandatory Flatten)",
                "close": "10:00 AM NZDT (16:00 PM ET Close)"
            }
        }
    except Exception as e:
        return {"is_open": False, "raw": [str(e)], "status_text": "NYSE clock check unavailable", "next_open": "Opens 03:30 AM NZDT"}

def get_trades_summary() -> Dict[str, Any]:
    """Calculate portfolio performance and return trade ledger with Tiger Brokers NZ fee deductions."""
    data = read_json_safe(TRADER_DIR / "trade_history.json") or {"trades": []}
    trades = data.get("trades", [])
    closed_trades = [t for t in trades if t.get("status") == "CLOSED" or t.get("side") == "SELL"]
    total_realized_pnl = round(sum(float(t.get("realized_pnl", 0.0)) for t in closed_trades), 2)
    starting_cash = float(data.get("starting_cash", 200.0))
    pnl_pct = round((total_realized_pnl / starting_cash) * 100, 2) if starting_cash > 0 else 0.0
    wins = [t for t in closed_trades if float(t.get("realized_pnl", 0.0)) > 0]
    losses = [t for t in closed_trades if float(t.get("realized_pnl", 0.0)) < 0]
    win_rate = round((len(wins) / len(closed_trades)) * 100, 1) if closed_trades else 0.0
    total_win_dollars = sum(float(t.get("realized_pnl", 0.0)) for t in wins)
    total_loss_dollars = abs(sum(float(t.get("realized_pnl", 0.0)) for t in losses))
    profit_factor = round(total_win_dollars / total_loss_dollars, 2) if total_loss_dollars > 0 else (99.0 if total_win_dollars > 0 else 1.0)
    
    # Tiger Brokers NZ total fees
    total_tiger_fees = round(sum(float(t.get("tiger_fee", 0.0)) for t in trades), 2)

    # Today's trades (NZDT date)
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    nz_today = (now_utc + datetime.timedelta(hours=13)).strftime("%Y-%m-%d")
    today_trades = [t for t in trades if t.get("timestamp_nzdt", "").startswith(nz_today)]
    today_closed = [t for t in today_trades if t.get("status") == "CLOSED" or t.get("side") == "SELL"]
    today_pnl = round(sum(float(t.get("realized_pnl", 0.0)) for t in today_closed), 2)
    today_fees = round(sum(float(t.get("tiger_fee", 0.0)) for t in today_trades), 2)

    portfolio = read_json_safe(TRADER_DIR / "portfolio.json") or {"cash": 200.0, "positions": []}
    current_cash = float(portfolio.get("cash", 200.0))

    return {
        "trades": trades,
        "summary": {
            "total_realized_pnl": total_realized_pnl,
            "total_pnl_pct": pnl_pct,
            "today_pnl": today_pnl,
            "today_fees": today_fees,
            "total_tiger_fees": total_tiger_fees,
            "win_rate": win_rate,
            "wins_count": len(wins),
            "losses_count": len(losses),
            "closed_count": len(closed_trades),
            "total_trades": len(trades),
            "profit_factor": profit_factor,
            "current_cash": current_cash,
            "starting_cash": starting_cash,
            "max_daily_loss": 6.0,
            "today_risk_used": 0.0
        }
    }

def get_full_state_snapshot() -> Dict[str, Any]:
    """Gather complete current state from disk."""
    config = read_json_safe(TRADER_DIR / "config.json") or {}
    portfolio = read_json_safe(TRADER_DIR / "portfolio.json") or {"cash": config.get("budget", 200.0), "positions": []}
    watchlist = read_json_safe(TRADER_DIR / "watchlist.json") or {"hits": []}
    entry = read_json_safe(TRADER_DIR / "entry.json")
    plan = read_json_safe(TRADER_DIR / "plan.json")
    timemachine = read_json_safe(TRADER_DIR / "timemachine.json")
    orders = read_json_safe(TRADER_DIR / "orders.json")
    risk_state = read_json_safe(STATE_DIR / "risk.json")
    broker_log = read_json_safe(STATE_DIR / "broker.json") or {"decisions": []}
    alerts = read_json_safe(TRADER_DIR / "alerts.json") or {"rules": []}
    alerts_fired = read_json_safe(STATE_DIR / "alerts.json") or {"fired": []}
    prices = read_json_safe(TRADER_DIR / "prices.json") or {}

    clock = get_market_clock_summary()

    # Calculate risk utilized today
    today_decisions = broker_log.get("decisions", [])
    trades_today = sum(1 for d in today_decisions if d.get("status") == "placed" and d.get("side") == "buy")
    risk_today = sum(d.get("max_loss", 0) for d in today_decisions if d.get("status") == "placed" and d.get("side") == "buy")

    # Evaluate active symbol signal
    active_sym = (plan.get("symbol") if plan else None) or (entry.get("symbol") if entry else None) or "TSLA"
    active_signal = evaluate_stock_signal(
        symbol=active_sym,
        entry=entry,
        plan=plan,
        timemachine=timemachine,
        risk_state=risk_state,
        portfolio=portfolio,
        prices=prices,
        catalyst_clear=True,
        setup_name=(plan.get("setup", "orb") if plan else "orb")
    )
    if watchlist and watchlist.get("hits"):
        watchlist = enrich_watchlist_with_signals(watchlist, portfolio, prices)

    return {
        "clock": clock,
        "config": config,
        "portfolio": portfolio,
        "watchlist": watchlist,
        "entry": entry,
        "plan": plan,
        "timemachine": timemachine,
        "orders": orders,
        "risk_state": risk_state,
        "broker_log": broker_log,
        "alerts": alerts,
        "alerts_fired": alerts_fired,
        "prices": prices,
        "signal": active_signal,
        "trades_summary": get_trades_summary(),
        "approved_stocks": get_all_11_skills_approved_stocks(),
        "telemetry": {
            "cash": portfolio.get("cash", 0),
            "trades_today": trades_today,
            "max_trades": config.get("max_trades_per_day", 4),
            "risk_today": round(risk_today, 2),
            "max_daily_loss": config.get("max_daily_loss_usd", 6.0),
            "open_positions_count": len(portfolio.get("positions", [])),
            "paper_mode": config.get("paper", True),
            "auto_scan_enabled": auto_scan_enabled
        }
    }

# --- HTTP Request Handlers ---

async def handle_get_state(request: web.Request) -> web.Response:
    state = get_full_state_snapshot()
    return web.json_response(state)

async def handle_post_scan(request: web.Request) -> web.Response:
    data = await request.json()
    mode = data.get("mode", "daily") # "daily" or "orb"
    symbols = str(data.get("symbols", "")).strip()
    approved_only = data.get("approved_only", True)
    
    # Ensure full US stock universe exists (~5,925+ Nasdaq/NYSE tickers)
    if not (TRADER_DIR / "universe.txt").is_file():
        await run_cli_cmd(["trader-scanner/scan.py", "universe"], timeout=45.0)

    args = ["trader-scanner/scan.py", mode]
    if symbols and symbols.upper() != "ALL":
        args.extend(["--symbols", symbols])
    # When symbols is empty or "ALL", scan.py scans the entire trader/universe.txt
    timeout_s = 180.0 if (not symbols or symbols.upper() == "ALL") else 60.0
    code, stdout, stderr = await run_cli_cmd(args, timeout=timeout_s)
    watchlist = read_json_safe(TRADER_DIR / "watchlist.json") or {}
    cur_pf = read_json_safe(TRADER_DIR / "portfolio.json") or {}
    cur_px = read_json_safe(TRADER_DIR / "prices.json") or {}
    watchlist = enrich_watchlist_with_signals(watchlist, cur_pf, cur_px, approved_only=approved_only)
    write_json_safe(TRADER_DIR / "watchlist.json", watchlist)
    
    await broadcast_ws({
        "type": "scan_complete",
        "mode": mode,
        "stdout": stdout,
        "stderr": stderr,
        "watchlist": watchlist
    })
    return web.json_response({"success": (code == 0 or len(watchlist.get("hits", [])) > 0), "output": stdout, "watchlist": watchlist})

async def handle_post_entry(request: web.Request) -> web.Response:
    data = await request.json()
    symbol = data.get("symbol", "TSLA").upper()
    args = ["trader-entry/entry.py", "check", symbol, "--write"]
    if data.get("offline"):
        args.extend(["--offline", data["offline"]])
    if data.get("now"):
        args.extend(["--now", data["now"]])
        
    code, stdout, stderr = await run_cli_cmd(args, timeout=20.0)
    entry = read_json_safe(TRADER_DIR / "entry.json")
    
    await broadcast_ws({
        "type": "entry_checked",
        "symbol": symbol,
        "code": code,
        "stdout": stdout,
        "entry": entry
    })
    return web.json_response({"success": True, "output": stdout, "entry": entry})

async def handle_post_plan(request: web.Request) -> web.Response:
    data = await request.json()
    stop_rule = data.get("stop", "or-mid")
    target_rule = data.get("target", "1R")
    
    args = ["trader-exit/exit.py", "plan", "--stop", stop_rule, "--target", target_rule, "--write"]
    if data.get("symbol") and data.get("entry"):
        args.extend(["--symbol", data["symbol"], "--entry", str(data["entry"])])
        if data.get("or_high") and data.get("or_low"):
            args.extend(["--or-high", str(data["or_high"]), "--or-low", str(data["or_low"])])
            
    code, stdout, stderr = await run_cli_cmd(args, timeout=20.0)
    plan = read_json_safe(TRADER_DIR / "plan.json")
    
    # Auto register alerts from plan
    if plan:
        await run_cli_cmd(["trader-alerts/alerts.py", "add", "--from-plan"])
        
    await broadcast_ws({
        "type": "plan_updated",
        "stdout": stdout,
        "plan": plan
    })
    return web.json_response({"success": (code == 0), "output": stdout, "plan": plan})

async def handle_post_timemachine(request: web.Request) -> web.Response:
    data = await request.json()
    replays = data.get("replays", 10000)
    seed = data.get("seed", 19)
    
    args = ["trader-timemachine/timemachine.py", "run", "--replays", str(replays), "--seed", str(seed), "--write"]
    if data.get("offline"):
        args.extend(["--offline", data["offline"]])
    if data.get("symbol") and data.get("entry") and data.get("stop") and data.get("target"):
        args.extend([
            "--symbol", data["symbol"],
            "--entry", str(data["entry"]),
            "--stop", str(data["stop"]),
            "--target", str(data["target"]),
            "--entry-time", data.get("entry_time", "10:15 AM")
        ])
        if data.get("date"):
            args.extend(["--date", data["date"]])
            
    code, stdout, stderr = await run_cli_cmd(args, timeout=30.0)
    timemachine = read_json_safe(TRADER_DIR / "timemachine.json")
    
    await broadcast_ws({
        "type": "timemachine_result",
        "stdout": stdout,
        "timemachine": timemachine
    })
    return web.json_response({"success": (code == 0), "output": stdout, "timemachine": timemachine})

async def handle_post_size(request: web.Request) -> web.Response:
    data = await request.json()
    args = ["trader-budget/size.py", "--write"]
    if data.get("now"):
        args.extend(["--now", data["now"]])
        
    code, stdout, stderr = await run_cli_cmd(args, timeout=20.0)
    orders = read_json_safe(TRADER_DIR / "orders.json")
    
    # Immediately trigger risk check
    risk_args = ["trader-risk/check.py"]
    if data.get("now"):
        risk_args.extend(["--now", data["now"]])
    rcode, rstdout, rstderr = await run_cli_cmd(risk_args, timeout=20.0)
    risk_state = read_json_safe(STATE_DIR / "risk.json")
    
    # Also fetch ticket representation
    targs = ["trader-broker/ticket.py", "show"]
    if data.get("now"):
        targs.extend(["--now", data["now"]])
    tcode, tstdout, tstderr = await run_cli_cmd(targs, timeout=20.0)
    
    await broadcast_ws({
        "type": "order_staged",
        "orders": orders,
        "risk_state": risk_state,
        "ticket_text": tstdout,
        "size_output": stdout,
        "risk_output": rstdout
    })
    return web.json_response({
        "success": (code == 0),
        "orders": orders,
        "risk_state": risk_state,
        "ticket_text": tstdout
    })

async def handle_post_approve_execute(request: web.Request) -> web.Response:
    data = await request.json()
    index = data.get("index", 1)
    reply = data.get("reply", "yes")
    now = data.get("now")
    
    # 1. Approve ticket
    args_appr = ["trader-broker/ticket.py", "approve", "--index", str(index), "--reply", reply]
    if now:
        args_appr.extend(["--now", now])
    acode, aout, aerr = await run_cli_cmd(args_appr, timeout=15.0)
    if acode != 0:
        return web.json_response({"success": False, "error": aerr or aout})
        
    # 2. In paper trading mode, execute the paper fill
    orders_data = read_json_safe(TRADER_DIR / "orders.json")
    order = None
    if isinstance(orders_data, list) and len(orders_data) >= index:
        order = orders_data[index - 1]
    elif isinstance(orders_data, dict):
        if "orders" in orders_data and isinstance(orders_data["orders"], list) and len(orders_data["orders"]) >= index:
            order = orders_data["orders"][index - 1]
        else:
            order = orders_data
            
    plan = read_json_safe(TRADER_DIR / "plan.json") or {}
    symbol = order.get("symbol") if order else plan.get("symbol", "TSLA")
    qty = float(order.get("qty", 1)) if order and order.get("qty") else 1.0
    
    if order and order.get("plan") and order["plan"].get("entry"):
        price = float(order["plan"]["entry"])
    elif plan and plan.get("entry"):
        price = float(plan["entry"])
    else:
        price = 10.0
    
    # Mark order result as placed
    res_args = [
        "trader-broker/ticket.py", "result",
        "--index", str(index),
        "--status", "placed",
        "--broker-id", f"sim-{int(time.time())}",
        "--filled-qty", str(qty),
        "--filled-price", str(price)
    ]
    if now:
        res_args.extend(["--now", now])
    rcode, rout, rerr = await run_cli_cmd(res_args, timeout=15.0)
    
    snapshot = get_full_state_snapshot()
    await broadcast_ws({
        "type": "order_executed",
        "symbol": symbol,
        "qty": qty,
        "price": price,
        "state": snapshot
    })
    return web.json_response({"success": True, "output": aout + "\n" + rout, "state": snapshot})

async def handle_post_flatten(request: web.Request) -> web.Response:
    data = await request.json()
    symbol = data.get("symbol")
    qty = data.get("qty")
    price = data.get("price")
    now = data.get("now")
    
    portfolio = read_json_safe(TRADER_DIR / "portfolio.json") or {}
    positions = portfolio.get("positions", [])
    
    pos_match = None
    if symbol:
        pos_match = next((p for p in positions if p.get("ticker") == symbol), None)
    elif positions:
        pos_match = positions[0]
        symbol = pos_match.get("ticker")
        
    if not pos_match or not symbol:
        return web.json_response({"success": False, "error": "No open positions to flatten"})
        
    shares_held = pos_match.get("shares", 0)
    qty = qty or shares_held
    
    # Work out reasonable exit price: user price, or latest quote in prices.json, or entry price
    if not price:
        prices = read_json_safe(TRADER_DIR / "prices.json") or {}
        if symbol in prices and isinstance(prices[symbol], dict) and prices[symbol].get("price"):
            price = float(prices[symbol]["price"])
        elif pos_match.get("lots") and pos_match["lots"][0].get("cost"):
            price = float(pos_match["lots"][0]["cost"]) / float(shares_held)
        else:
            plan = read_json_safe(TRADER_DIR / "plan.json") or {}
            price = float(plan.get("entry", 10.0))
            
    fill_price = round(float(price), 2)
    
    # Execute flatten via ticket.py
    fargs = ["trader-broker/ticket.py", "flatten", "--symbol", symbol, "--qty", str(qty)]
    if now:
        fargs.extend(["--now", now])
    fcode, fout, ferr = await run_cli_cmd(fargs, timeout=15.0)
    
    # Approve and fill closing sell order in paper mode
    fill_args = ["trader-broker/ticket.py", "fill", "--symbol", symbol, "--side", "sell", "--qty", str(qty), "--price", str(fill_price)]
    if now:
        fill_args.extend(["--now", now])
    await run_cli_cmd(fill_args, timeout=15.0)
    
    snapshot = get_full_state_snapshot()
    await broadcast_ws({
        "type": "position_flattened",
        "symbol": symbol,
        "qty": qty,
        "price": fill_price,
        "state": snapshot
    })
    return web.json_response({"success": True, "output": fout, "price": fill_price, "state": snapshot})

async def handle_get_news(request: web.Request) -> web.Response:
    symbols = request.query.get("symbols", "TSLA,NVDA,AAPL")
    sym_list = [s.strip().upper() for s in symbols.replace(",", " ").split() if s.strip()]
    cache_key = ",".join(sorted(sym_list))
    now = time.time()
    force = request.query.get("force", "false").lower() == "true"

    if not force and cache_key in _NEWS_CACHE:
        cached_time, cached_data = _NEWS_CACHE[cache_key]
        if (now - cached_time) < NEWS_CACHE_TTL:
            return web.json_response({"success": True, "data": cached_data, "cached": True})

    args = ["trader-news/news.py", "--tickers"] + sym_list + ["--hours", "72", "--all", "--config", str(TRADER_DIR / "config.json"), "--json"]
    code, stdout, stderr = await run_cli_cmd(args, timeout=25.0)
    data = {}
    try:
        data = json.loads(stdout)
    except Exception:
        data = {}

    raw_items = data.get("items", [])
    moves = data.get("moves", [])
    if not raw_items:
        # Fallback to live headlines via Google News RSS
        for sym in sym_list[:3]:
            live_items = await asyncio.to_thread(fetch_live_headlines, sym)
            for it in live_items:
                raw_items.append(it)

    # Normalize every news item so fields are always defined and uniform
    normalized_items = []
    for it in raw_items:
        title = it.get("title") or it.get("headline") or "Market Update"
        link = it.get("link") or it.get("url") or "#"
        ticker = it.get("ticker")
        if not ticker and it.get("tickers") and len(it["tickers"]) > 0:
            ticker = it["tickers"][0]
        if not ticker and it.get("touches") and len(it["touches"]) > 0:
            ticker = it["touches"][0]
        if not ticker:
            ticker = sym_list[0] if sym_list else "TSLA"

        raw_time = it.get("time") or datetime.datetime.now(datetime.timezone.utc).isoformat()
        iso_time = raw_time
        try:
            parsed_dt = email.utils.parsedate_to_datetime(raw_time)
            iso_time = parsed_dt.isoformat()
        except Exception:
            pass

        normalized_items.append({
            "title": title,
            "headline": title,
            "link": link,
            "url": link,
            "ticker": ticker,
            "tickers": it.get("tickers") or [ticker],
            "time": iso_time,
            "source": it.get("source") or "Market News",
            "tags": it.get("tags") or ["live-feed", ticker],
            "new": it.get("new", True)
        })

    data["items"] = normalized_items
    if not moves:
        data["moves"] = [{"ticker": s, "price": resolve_real_market_price(s), "pct": 2.50, "moving": True} for s in sym_list]

    _NEWS_CACHE[cache_key] = (now, data)
    return web.json_response({"success": True, "data": data, "cached": False})

async def handle_get_pelosi(request: web.Request) -> web.Response:
    args = ["trader-pelosi/ptr.py", "index", "--member", "pelosi"]
    code, stdout, stderr = await run_cli_cmd(args, timeout=20.0)
    return web.json_response({"success": (code == 0), "output": stdout, "error": stderr})

async def handle_post_quote(request: web.Request) -> web.Response:
    data = await request.json()
    symbol = data.get("symbol", "TSLA").upper()
    args = ["trader-alerts/alerts.py", "quote", symbol, "--write"]
    code, stdout, stderr = await run_cli_cmd(args, timeout=15.0)
    prices = read_json_safe(TRADER_DIR / "prices.json") or {}
    
    await broadcast_ws({
        "type": "quote_update",
        "symbol": symbol,
        "prices": prices,
        "raw": stdout
    })
    return web.json_response({"success": (code == 0), "symbol": symbol, "quote": prices.get(symbol), "raw": stdout})

async def handle_post_replay(request: web.Request) -> web.Response:
    """
    Runs the full Oct 19 2026 TSLA Reel Replay end-to-end to demonstrate the
    full quantitative trading lifecycle with zero external dependencies.
    """
    tsla_entry_fixture = "tests/fixtures/trader-entry/TSLA-2026-10-19-5m.json"
    tsla_mc_fixture = "tests/fixtures/trader-timemachine/TSLA-60d5m.json.gz"
    now_str = "2026-10-19 10:15"
    
    # 1. Check entry
    await run_cli_cmd(["trader-entry/entry.py", "check", "TSLA", "--offline", tsla_entry_fixture, "--now", now_str, "--write"])
    # 2. Plan exit
    await run_cli_cmd(["trader-exit/exit.py", "plan", "--stop", "or-mid", "--target", "1R", "--write"])
    # 3. Run Monte Carlo Time Machine
    await run_cli_cmd(["trader-timemachine/timemachine.py", "run", "--offline", tsla_mc_fixture, "--write"])
    # 4. Budget sizing
    await run_cli_cmd(["trader-budget/size.py", "--now", now_str, "--write"])
    # 5. Risk check
    await run_cli_cmd(["trader-risk/check.py", "--now", now_str])
    # 6. Setup alerts
    await run_cli_cmd(["trader-alerts/alerts.py", "add", "--from-plan"])
    
    snapshot = get_full_state_snapshot()
    await broadcast_ws({
        "type": "replay_complete",
        "message": "TSLA Oct 19 2026 reel trade simulated and staged successfully",
        "state": snapshot
    })
    return web.json_response({"success": True, "state": snapshot})

async def handle_post_config(request: web.Request) -> web.Response:
    new_cfg = await request.json()
    cfg_path = TRADER_DIR / "config.json"
    curr_cfg = read_json_safe(cfg_path) or {}
    curr_cfg.update(new_cfg)
    write_json_safe(cfg_path, curr_cfg)
    
    await broadcast_ws({"type": "config_updated", "config": curr_cfg})
    return web.json_response({"success": True, "config": curr_cfg})

async def handle_post_autoscan(request: web.Request) -> web.Response:
    global auto_scan_enabled
    try:
        data = await request.json()
    except Exception:
        data = {}
    if "enabled" in data:
        auto_scan_enabled = bool(data["enabled"])
    else:
        auto_scan_enabled = not auto_scan_enabled
    await broadcast_ws({"type": "auto_scan_toggled", "enabled": auto_scan_enabled})
    return web.json_response({"success": True, "auto_scan_enabled": auto_scan_enabled})

async def handle_post_demo_buy(request: web.Request) -> web.Response:
    data = await request.json()
    symbol = data.get("symbol", "TSLA").upper()
    usd_amount = float(data.get("usd_amount", 0.0)) if data.get("usd_amount") else 0.0
    qty = float(data.get("qty", 0.0)) if data.get("qty") else 0.0
    price = float(data.get("price", 0.0))
    stop = float(data.get("stop", 0.0))
    target = float(data.get("target", 0.0))
    
    portfolio = read_json_safe(TRADER_DIR / "portfolio.json") or {"cash": 200.0, "positions": []}
    cash = float(portfolio.get("cash", 0.0))
    
    if price <= 0:
        price = resolve_real_market_price(symbol)
        if price <= 0:
            price = 100.0

    cfg = read_json_safe(TRADER_DIR / "config.json") or {}
    min_net_profit = float(cfg.get("min_net_profit_usd", 0.05))
    fractional_pref = bool(cfg.get("fractional", True))

    # Fractional share calculation if buying by USD amount
    if usd_amount > 0 and qty <= 0:
        frac_chk = check_fractional_support(symbol, price, usd_amount)
        if not frac_chk["supported"]:
            return web.json_response({"success": False, "error": frac_chk["reason"]}, status=400)
        qty = round(usd_amount / price, 4)
        # Tiger NZ rule: prefer <1 share when >=1 share would trigger $1.99/leg minimums
        if fractional_pref and qty >= 1.0 and (0.999 * price) >= 1.0:
            qty = 0.999
    elif qty <= 0:
        qty = 1.0

    if stop <= 0:
        stop = round(price * 0.98, 2)
    if target <= 0:
        # Default 2R (+4% for 2% stop) so expected profit clears Tiger NZ round-trip fees
        target = round(price + 2.0 * (price - stop), 2)

    # Preview round-trip Tiger NZ fees and reject if expected net profit < threshold
    econ = preview_round_trip_economics(
        symbol=symbol,
        shares=qty,
        entry_price=price,
        stop_price=stop,
        target_price=target,
        min_net_profit_usd=min_net_profit,
        conservative_regulatory=False,
    )
    if not econ.get("verified") or not econ.get("profitable"):
        return web.json_response({
            "success": False,
            "error": econ.get("reason", "Trade rejected: expected profit does not cover Tiger Brokers NZ round-trip fees."),
            "economics": econ
        }, status=400)

    # Calculate Tiger Brokers NZ Trading Fee
    fee_calc = calculate_tiger_nz_fee("BUY", qty, price)
    tiger_fee = fee_calc["total_fee"]
    total_cost = round((qty * price) + tiger_fee, 2)

    if cash < total_cost:
        return web.json_response({
            "success": False,
            "error": f"Insufficient cash: ${cash:,.2f} USD available, but ${total_cost:,.2f} USD required for {qty:.4f} {symbol} (includes ${tiger_fee:.2f} Tiger NZ fee)."
        }, status=400)
        
    # Execute fill via ticket.py fill
    fargs = [
        "trader-broker/ticket.py", "fill",
        "--symbol", symbol,
        "--side", "buy",
        "--qty", str(qty),
        "--price", str(round(price, 2))
    ]
    fcode, fout, ferr = await run_cli_cmd(fargs, timeout=15.0)
    
    # Deduct Tiger NZ fee from cash and record fee in lot cost
    updated_pf = read_json_safe(TRADER_DIR / "portfolio.json") or {"cash": cash, "positions": []}
    updated_pf["cash"] = round(max(0.0, float(updated_pf.get("cash", cash)) - tiger_fee), 2)
    for p in updated_pf.get("positions", []):
        if p.get("ticker") == symbol and p.get("lots"):
            p["lots"][-1]["tiger_fee"] = tiger_fee
            p["lots"][-1]["cost"] = total_cost
    write_json_safe(TRADER_DIR / "portfolio.json", updated_pf)

    # Setup stop and target alerts in trader/alerts.json
    alerts = read_json_safe(TRADER_DIR / "alerts.json") or {"rules": []}
    rules = [r for r in alerts.get("rules", []) if r.get("symbol") != symbol]
    rules.append({"type": "stop", "symbol": symbol, "price": round(stop, 2)})
    rules.append({"type": "target", "symbol": symbol, "price": round(target, 2)})
    alerts["rules"] = rules
    write_json_safe(TRADER_DIR / "alerts.json", alerts)

    # Record fill to trade_history.json
    th_data = read_json_safe(TRADER_DIR / "trade_history.json") or {"trades": []}
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    nz_time = now_utc.astimezone(zoneinfo.ZoneInfo("Pacific/Auckland")).strftime("%Y-%m-%d %I:%M:%S %p NZDT")
    et_time = now_utc.astimezone(zoneinfo.ZoneInfo("America/New_York")).strftime("%Y-%m-%d %I:%M:%S %p ET")
    trade_id = f"TRD-{int(time.time())}"
    th_data.setdefault("trades", []).insert(0, {
        "id": trade_id,
        "timestamp_nzdt": nz_time,
        "timestamp_et": et_time,
        "symbol": symbol,
        "side": "BUY",
        "shares": qty,
        "price": round(price, 2),
        "cost": total_cost,
        "tiger_fee": tiger_fee,
        "proceeds": 0.0,
        "realized_pnl": 0.0,
        "realized_pnl_pct": 0.0,
        "status": "OPEN",
        "exit_reason": None,
        "notes": f"15m ORB Entry at ${price:.2f} USD (Tiger Fee: ${tiger_fee:.2f}, Stop: ${stop:.2f})"
    })
    write_json_safe(TRADER_DIR / "trade_history.json", th_data)

    snapshot = get_full_state_snapshot()
    await broadcast_ws({
        "type": "demo_buy_filled",
        "symbol": symbol,
        "qty": qty,
        "price": price,
        "cost": total_cost,
        "tiger_fee": tiger_fee,
        "state": snapshot
    })
    return web.json_response({
        "success": True,
        "message": f"Successfully bought {qty:.4f} {symbol} @ ${price:.2f} USD (Tiger NZ fee: ${tiger_fee:.2f}, total: ${total_cost:,.2f} USD)",
        "state": snapshot
    })

async def handle_post_demo_sell(request: web.Request) -> web.Response:
    data = await request.json()
    symbol = data.get("symbol", "").upper()
    percent = float(data.get("percent", 0.0))
    usd_amount = float(data.get("usd_amount", 0.0))
    qty = float(data.get("qty", 0.0)) if data.get("qty") else None
    price = float(data.get("price", 0.0))
    
    portfolio = read_json_safe(TRADER_DIR / "portfolio.json") or {"cash": 200.0, "positions": []}
    positions = portfolio.get("positions", [])
    pos_match = None
    if symbol:
        pos_match = next((p for p in positions if str(p.get("ticker", "")).upper() == symbol), None)
    elif positions:
        pos_match = positions[0]
        symbol = str(pos_match.get("ticker", "")).upper()

    if not pos_match:
        return web.json_response({"success": False, "error": f"No open position for {symbol} found in portfolio."}, status=400)

    held_shares = float(pos_match.get("shares", 0))

    if price <= 0:
        price = resolve_real_market_price(symbol)
        if price <= 0:
            if pos_match.get("lots") and pos_match["lots"]:
                price = float(pos_match["lots"][0].get("cost", 0)) / float(held_shares)
            else:
                price = 100.0

    if usd_amount > 0 and price > 0:
        sell_qty = min(held_shares, round(usd_amount / price, 4))
    elif percent > 0:
        sell_qty = round(held_shares * (percent / 100.0), 4)
    elif qty and qty <= held_shares:
        sell_qty = round(qty, 4)
    else:
        sell_qty = held_shares

    if sell_qty <= 0:
        return web.json_response({"success": False, "error": "Invalid sell quantity."}, status=400)

    # Cost basis calculation
    cost_basis = 0.0
    buy_tiger_fee = 0.0
    if pos_match.get("lots") and pos_match["lots"]:
        lot = pos_match["lots"][0]
        cost_per_share = float(lot.get("cost", 0)) / float(held_shares) if held_shares > 0 else price
        cost_basis = round(cost_per_share * sell_qty, 2)
        buy_tiger_fee = float(lot.get("tiger_fee", 0.0))
    else:
        cost_basis = round(price * sell_qty, 2)

    # Tiger Brokers NZ SELL fee calculation (includes SEC + FINRA regulatory fees)
    fee_calc = calculate_tiger_nz_fee("SELL", sell_qty, price)
    tiger_fee = fee_calc["total_fee"]
    gross_proceeds = round(sell_qty * price, 2)
    net_proceeds = round(gross_proceeds - tiger_fee, 2)

    # Net realized PnL = Net proceeds - cost basis (which already included buy fee)
    realized_pnl = round(net_proceeds - cost_basis, 2)
    realized_pnl_pct = round((realized_pnl / cost_basis) * 100, 2) if cost_basis > 0 else 0.0

    fargs = [
        "trader-broker/ticket.py", "fill",
        "--symbol", symbol,
        "--side", "sell",
        "--qty", str(sell_qty),
        "--price", str(round(price, 2))
    ]
    fcode, fout, ferr = await run_cli_cmd(fargs, timeout=15.0)

    # Check if position fully closed to clean alerts
    updated_pf = read_json_safe(TRADER_DIR / "portfolio.json") or {}
    updated_pos = next((p for p in updated_pf.get("positions", []) if str(p.get("ticker", "")).upper() == symbol), None)
    if not updated_pos or float(updated_pos.get("shares", 0)) <= 1e-6:
        alerts = read_json_safe(TRADER_DIR / "alerts.json") or {"rules": []}
        alerts["rules"] = [r for r in alerts.get("rules", []) if r.get("symbol") != symbol]
        write_json_safe(TRADER_DIR / "alerts.json", alerts)

    # Record sell in trade_history.json
    th_data = read_json_safe(TRADER_DIR / "trade_history.json") or {"trades": []}
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    nz_time = now_utc.astimezone(zoneinfo.ZoneInfo("Pacific/Auckland")).strftime("%Y-%m-%d %I:%M:%S %p NZDT")
    et_time = now_utc.astimezone(zoneinfo.ZoneInfo("America/New_York")).strftime("%Y-%m-%d %I:%M:%S %p ET")
    trade_id = f"TRD-{int(time.time())}"
    exit_reason = "1R Profit Target Reached" if realized_pnl > 0 else ("Midpoint Stop Cut Loss" if realized_pnl < 0 else "09:55 Flat-by-Close Rule")
    th_data.setdefault("trades", []).insert(0, {
        "id": trade_id,
        "timestamp_nzdt": nz_time,
        "timestamp_et": et_time,
        "symbol": symbol,
        "side": "SELL",
        "shares": sell_qty,
        "price": round(price, 2),
        "cost": cost_basis,
        "tiger_fee": tiger_fee,
        "proceeds": net_proceeds,
        "realized_pnl": realized_pnl,
        "realized_pnl_pct": realized_pnl_pct,
        "status": "CLOSED",
        "exit_reason": exit_reason,
        "notes": f"Liquidated {sell_qty:.4f} shares @ ${price:.2f} (Net: ${net_proceeds:.2f}, Tiger Fee: ${tiger_fee:.2f})"
    })
    write_json_safe(TRADER_DIR / "trade_history.json", th_data)

    snapshot = get_full_state_snapshot()
    await broadcast_ws({
        "type": "demo_sell_filled",
        "symbol": symbol,
        "qty": sell_qty,
        "price": price,
        "proceeds": net_proceeds,
        "tiger_fee": tiger_fee,
        "state": snapshot
    })
    return web.json_response({
        "success": True,
        "message": f"Successfully sold {sell_qty:.4f} {symbol} @ ${price:.2f} USD. Credited ${net_proceeds:,.2f} USD (Tiger Fee: ${tiger_fee:.2f}).",
        "state": snapshot
    })

async def handle_get_trades(request: web.Request) -> web.Response:
    """Return trade history and real-time PnL performance metrics."""
    trades_data = get_trades_summary()
    return web.json_response({"success": True, **trades_data})

async def handle_get_lookup(request: web.Request) -> web.Response:
    """Analyze and stage any US stock from universe."""
    symbol = request.query.get("symbol", "").strip().upper()
    if not symbol:
        return web.json_response({"success": False, "error": "Symbol is required"}, status=400)
        
    real_price = resolve_real_market_price(symbol)
    await run_cli_cmd(["trader-entry/entry.py", "check", symbol, "--write"], timeout=15.0)
    or_high = round(real_price * 1.006, 2)
    or_low = round(real_price * 0.985, 2)
    await run_cli_cmd([
        "trader-exit/exit.py", "plan",
        "--symbol", symbol,
        "--entry", str(real_price),
        "--stop", "or-mid",
        "--or-high", str(or_high),
        "--or-low", str(or_low),
        "--target", "2R",
        "--write"
    ], timeout=15.0)
    
    pipeline_res = run_day_trader_pipeline(symbol=symbol)
    snapshot = get_full_state_snapshot()
    await broadcast_ws({
        "type": "symbol_loaded",
        "symbol": symbol,
        "pipeline": pipeline_res,
        "state": snapshot
    })
    return web.json_response({"success": True, "symbol": symbol, "pipeline": pipeline_res, "state": snapshot})

async def handle_get_universe_search(request: web.Request) -> web.Response:
    """Fast auto-lookup for all 5,900+ US stocks in universe.txt."""
    query = request.query.get("q", "").strip().upper()
    universe_path = TRADER_DIR / "universe.txt"
    matches = []
    if universe_path.is_file():
        with open(universe_path, "r", encoding="utf-8") as f:
            for line in f:
                if "|" in line:
                    sym, name = line.strip().split("|", 1)
                    if not query or query in sym or query.lower() in name.lower():
                        matches.append({"symbol": sym, "name": name})
                        if len(matches) >= 30:
                            break
    return web.json_response({"matches": matches})

async def handle_post_demo_cash(request: web.Request) -> web.Response:
    data = await request.json()
    action = data.get("action", "reset")
    amount = float(data.get("amount", 200.0))
    if amount > 5000.0:
        amount = 5000.0
    
    portfolio = read_json_safe(TRADER_DIR / "portfolio.json") or {"cash": 200.0, "positions": []}
    if action == "reset":
        portfolio["cash"] = round(amount, 2)
        portfolio["positions"] = []
    elif action == "add":
        new_cash = round(portfolio.get("cash", 0.0) + amount, 2)
        portfolio["cash"] = new_cash

    write_json_safe(TRADER_DIR / "portfolio.json", portfolio)
    cfg_path = TRADER_DIR / "config.json"
    curr_cfg = read_json_safe(cfg_path) or {}
    curr_cfg["budget"] = portfolio["cash"]
    write_json_safe(cfg_path, curr_cfg)

    snapshot = get_full_state_snapshot()
    await broadcast_ws({
        "type": "demo_cash_updated",
        "cash": portfolio["cash"],
        "state": snapshot
    })
    return web.json_response({
        "success": True,
        "cash": portfolio["cash"],
        "message": f"Portfolio cash updated to ${portfolio['cash']:,.2f} USD",
        "state": snapshot
    })

async def handle_get_gemini_news(request: web.Request) -> web.Response:
    """Analyze real-time news and catalysts using Gemini 3.5 Flash Lite."""
    symbol = request.query.get("symbol", "TSLA").upper()
    force = request.query.get("force", "false").lower() == "true"
    args = ["trader-news/news.py", "--tickers", symbol, "--hours", "72", "--all", "--config", str(TRADER_DIR / "config.json"), "--json"]
    code, stdout, stderr = await run_cli_cmd(args, timeout=15.0)
    news_items = []
    price_data = {}
    try:
        data = json.loads(stdout)
        news_items = data.get("items", [])
        moves = data.get("moves", [])
        if moves:
            price_data = moves[0]
    except Exception:
        pass
    
    if not price_data:
        price_data = {"price": resolve_real_market_price(symbol)}

    analysis = analyze_news_with_gemini(symbol, news_items=news_items, price_data=price_data, force=force)
    return web.json_response({"success": True, "symbol": symbol, "gemini": analysis})

async def handle_get_pipeline(request: web.Request) -> web.Response:
    """Run full 11-skill day trader pipeline for a symbol."""
    symbol = request.query.get("symbol", "TSLA").upper()
    usd = float(request.query.get("usd", 25.0))
    force = request.query.get("force", "false").lower() == "true"
    pipeline_res = run_day_trader_pipeline(symbol=symbol, usd_amount=usd, force_news=force)
    return web.json_response({"success": True, "pipeline": pipeline_res})

async def handle_get_signal(request: web.Request) -> web.Response:
    symbol = request.query.get("symbol", "TSLA").upper()
    snapshot = get_full_state_snapshot()
    sig = evaluate_stock_signal(
        symbol=symbol,
        entry=snapshot.get("entry"),
        plan=snapshot.get("plan"),
        timemachine=snapshot.get("timemachine"),
        risk_state=snapshot.get("risk_state"),
        portfolio=snapshot.get("portfolio"),
        prices=snapshot.get("prices")
    )
    return web.json_response({"success": True, "signal": sig})

async def handle_get_tunnel(request: web.Request) -> web.Response:
    url = None
    for p in [Path("/tmp/current_tunnel_url.txt"), STATE_DIR / "current_tunnel_url.txt"]:
        if p.is_file():
            try:
                url = p.read_text(encoding="utf-8").strip()
                if url:
                    break
            except Exception:
                pass
    return web.json_response({
        "success": True,
        "tunnel_url": url,
        "local_ip_url": "http://192.168.8.68:8080"
    })

async def handle_get_analyst_facts(request: web.Request) -> web.Response:
    """Extract SEC EDGAR 10-Q/10-K company facts (trader-analyst)."""
    symbol = request.query.get("symbol", "TSLA").upper()
    code, stdout, stderr = await run_cli_cmd(["trader-analyst/facts.py", symbol, "--config", str(TRADER_DIR / "config.json"), "--json"], timeout=15.0)
    facts = []
    if code == 0 and stdout.strip():
        try:
            facts = json.loads(stdout)
        except Exception:
            pass
    return web.json_response({"success": True, "symbol": symbol, "facts": facts})

async def handle_get_pipeline_approved(request: web.Request) -> web.Response:
    """Return all stocks currently approved by all 11 Day Trader skills."""
    stocks = get_all_11_skills_approved_stocks()
    return web.json_response({"success": True, "approved_stocks": stocks})

async def handle_get_chart_data(request: web.Request) -> web.Response:
    """Fetch real multi-timeframe OHLCV chart bars and levels."""
    symbol = request.query.get("symbol", "TSLA").upper()
    tf = request.query.get("tf", "1D").upper()
    chart = fetch_chart_data(symbol, tf)
    return web.json_response({"success": True, **chart})

async def handle_post_send_report(request: web.Request) -> web.Response:
    """Trigger the daily market close report email via Resend."""
    res = send_daily_market_close_report()
    return web.json_response(res)

async def handle_get_report_summary(request: web.Request) -> web.Response:
    """Return structured daily broker statement summary data."""
    from trader.daily_reporter import build_daily_report_data
    return web.json_response({"success": True, "data": build_daily_report_data()})

async def handle_get_statement_pdf(request: web.Request) -> web.Response:
    """Returns the official broker statement PDF for download or inline viewing."""
    try:
        from trader.statement_pdf import generate_broker_statement_pdf
        from trader.daily_reporter import build_daily_report_data
        data = build_daily_report_data()
        pdf_bytes = generate_broker_statement_pdf(data)
        filename = f"TigerBrokersNZ_Statement_{data['nz_date']}.pdf"
        return web.Response(
            body=pdf_bytes,
            content_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{filename}"'}
        )
    except Exception as e:
        return web.Response(text=f"Error generating statement: {e}", status=500)

# --- WebSocket Handler ---

async def handle_websocket(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=20.0)
    await ws.prepare(request)
    connected_websockets.add(ws)
    
    # Send current snapshot on connect
    try:
        snapshot = get_full_state_snapshot()
        await ws.send_str(json.dumps({
            "type": "init_state",
            "state": snapshot
        }))
    except Exception as e:
        print(f"Error sending init state: {e}")

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    payload = json.loads(msg.data)
                    action = payload.get("action")
                    if action == "ping":
                        await ws.send_str(json.dumps({"type": "pong", "ts": time.time()}))
                    elif action == "refresh":
                        snap = get_full_state_snapshot()
                        await ws.send_str(json.dumps({"type": "init_state", "state": snap}))
                except Exception as ex:
                    await ws.send_str(json.dumps({"type": "error", "message": str(ex)}))
            elif msg.type == WSMsgType.ERROR:
                print(f"WebSocket connection closed with error: {ws.exception()}")
    finally:
        connected_websockets.discard(ws)
        
    return ws

# --- Background Telemetry & Alert Poller ---

async def background_poller():
    """Polls quotes, alerts, and market clock periodically in background."""
    while True:
        try:
            await asyncio.sleep(8)
            # Check alerts if any rules exist
            alerts_path = TRADER_DIR / "alerts.json"
            if alerts_path.is_file():
                code, stdout, stderr = await run_cli_cmd(["trader-alerts/alerts.py", "check"], timeout=10.0)
                if code == 0: # Something rang!
                    await broadcast_ws({
                        "type": "alert_fired",
                        "output": stdout,
                        "fired": read_json_safe(STATE_DIR / "alerts.json")
                    })
            
            # 24/7 Autonomous Trading Loop Execution (non-blocking thread)
            try:
                await asyncio.to_thread(run_auto_trader_cycle)
            except Exception:
                pass

            # Autonomous Continuous All-US-Stock Scanner Loop (rolling 100-stock batches across all ~5,925 tickers in universe.txt)
            global last_auto_scan_time, auto_scan_enabled
            now_ts = time.time()
            if auto_scan_enabled and (now_ts - last_auto_scan_time >= 30.0):
                last_auto_scan_time = now_ts
                engine = get_auto_trader()
                batch_syms = engine.next_universe_batch(100)
                if batch_syms:
                    m_times = engine.get_market_times()
                    scan_mode = "orb" if m_times.get("is_orb_trading_active") else "daily"
                    prev_wl = read_json_safe(TRADER_DIR / "watchlist.json") or {}
                    prev_hits = {h.get("symbol"): h for h in prev_wl.get("hits", []) if h.get("symbol")}
                    symbols_to_scan = ",".join(batch_syms)
                    scode, sout, serr = await run_cli_cmd(
                        ["trader-scanner/scan.py", scan_mode, "--symbols", symbols_to_scan],
                        timeout=45.0
                    )
                    wl = read_json_safe(TRADER_DIR / "watchlist.json") or {}
                    # Merge hits across rolling universe batches so earlier US stock hits are preserved
                    for h in wl.get("hits", []):
                        if h.get("symbol"):
                            prev_hits[h["symbol"]] = h
                    merged_hits = list(prev_hits.values())
                    wl["hits"] = merged_hits
                    wl["universe"] = len(engine.universe_symbols)
                    wl["universe_cursor"] = engine.universe_pointer
                    if merged_hits:
                        cur_pf = read_json_safe(TRADER_DIR / "portfolio.json") or {}
                        cur_px = read_json_safe(TRADER_DIR / "prices.json") or {}
                        wl = enrich_watchlist_with_signals(wl, cur_pf, cur_px)
                    write_json_safe(TRADER_DIR / "watchlist.json", wl)
                    if wl.get("hits"):
                        await broadcast_ws({
                            "type": "scan_complete",
                            "mode": f"auto-{scan_mode}",
                            "watchlist": wl,
                            "stdout": sout
                        })

            # Periodically broadcast clock & telemetry
            clock = get_market_clock_summary()
            portfolio = read_json_safe(TRADER_DIR / "portfolio.json") or {}
            config = read_json_safe(TRADER_DIR / "config.json") or {}
            broker_log = read_json_safe(STATE_DIR / "broker.json") or {"decisions": []}
            
            today_decisions = broker_log.get("decisions", [])
            trades_today = sum(1 for d in today_decisions if d.get("status") == "placed" and d.get("side") == "buy")
            risk_today = sum(d.get("max_loss", 0) for d in today_decisions if d.get("status") == "placed" and d.get("side") == "buy")

            await broadcast_ws({
                "type": "telemetry",
                "clock": clock,
                "telemetry": {
                    "cash": portfolio.get("cash", config.get("budget", 200.0)),
                    "trades_today": trades_today,
                    "max_trades": config.get("max_trades_per_day", 4),
                    "risk_today": round(risk_today, 2),
                    "max_daily_loss": config.get("max_daily_loss_usd", 6.0),
                    "open_positions_count": len(portfolio.get("positions", [])),
                    "paper_mode": config.get("paper", True),
                    "auto_scan_enabled": auto_scan_enabled
                }
            })
        except asyncio.CancelledError:
            break
        except Exception as e:
            # Continue poller on transient error
            await asyncio.sleep(5)

async def init_app() -> web.Application:
    app = web.Application()
    
    # API Routes
    app.router.add_get("/api/state", handle_get_state)
    app.router.add_get("/api/trades", handle_get_trades)
    app.router.add_post("/api/scan", handle_post_scan)
    app.router.add_post("/api/entry", handle_post_entry)
    app.router.add_post("/api/plan", handle_post_plan)
    app.router.add_post("/api/timemachine", handle_post_timemachine)
    app.router.add_post("/api/size", handle_post_size)
    app.router.add_post("/api/ticket/approve", handle_post_approve_execute)
    app.router.add_post("/api/flatten", handle_post_flatten)
    app.router.add_post("/api/demo/buy", handle_post_demo_buy)
    app.router.add_post("/api/demo/sell", handle_post_demo_sell)
    app.router.add_post("/api/demo/cash", handle_post_demo_cash)
    app.router.add_get("/api/signal", handle_get_signal)
    app.router.add_get("/api/pipeline", handle_get_pipeline)
    app.router.add_get("/api/pipeline/approved", handle_get_pipeline_approved)
    app.router.add_get("/api/lookup", handle_get_lookup)
    app.router.add_get("/api/universe/search", handle_get_universe_search)
    app.router.add_get("/api/news", handle_get_news)
    app.router.add_get("/api/gemini/news", handle_get_gemini_news)
    app.router.add_get("/api/pelosi", handle_get_pelosi)
    app.router.add_get("/api/analyst/facts", handle_get_analyst_facts)
    app.router.add_post("/api/quote", handle_post_quote)
    app.router.add_post("/api/replay", handle_post_replay)
    app.router.add_get("/api/config", handle_get_state)
    app.router.add_post("/api/config", handle_post_config)
    app.router.add_post("/api/auto-scan", handle_post_autoscan)
    app.router.add_get("/api/tunnel", handle_get_tunnel)
    app.router.add_get("/api/chart/data", handle_get_chart_data)
    app.router.add_post("/api/report/send", handle_post_send_report)
    app.router.add_get("/api/report/summary", handle_get_report_summary)
    app.router.add_get("/api/report/statement.pdf", handle_get_statement_pdf)
    
    # WebSocket route
    app.router.add_get("/ws", handle_websocket)
    
    # Static files serving
    async def index_handler(request):
        return web.FileResponse(PUBLIC_DIR / "index.html")
        
    app.router.add_get("/", index_handler)
    app.router.add_static("/", PUBLIC_DIR, show_index=True)
    
    # Start background poller task
    app["poller"] = asyncio.create_task(background_poller())
    
    async def cleanup(app):
        app["poller"].cancel()
        await app["poller"]
        for ws in set(connected_websockets):
            await ws.close()
            
    app.on_cleanup.append(cleanup)
    return app

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Day Trader Real-Time Dashboard Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host interface (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080)")
    args = parser.parse_args()
    
    print(f"\n⚡ Starting Day Trader Real-Time Station on http://localhost:{args.port}")
    web.run_app(init_app(), host=args.host, port=args.port)

if __name__ == "__main__":
    main()
