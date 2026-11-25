#!/usr/bin/env python3
"""
Day Trader Station - One-Step Launch Command
Initializes configuration, verifies dependencies, prepares the quantitative
workspace, and launches the real-time WebSocket trading station.
"""

import sys
import os
import json
import shutil
import argparse
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent
TRADER_DIR = REPO_DIR / "trader"
STATE_DIR = TRADER_DIR / "state"

sys.path.insert(0, str(REPO_DIR))
try:
    from trader.daily_reporter import load_env
    load_env()
except Exception:
    pass

def setup_workspace():
    """Ensure all required directories and default configs exist."""
    TRADER_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Config
    config_file = TRADER_DIR / "config.json"
    if not config_file.is_file():
        example_config = REPO_DIR / "trader-budget" / "config.example.json"
        if example_config.is_file():
            shutil.copy(example_config, config_file)
            try:
                with open(config_file, "r+", encoding="utf-8") as f:
                    cfg = json.load(f)
                    cfg["sec_user_agent"] = "DayTrader User daytrader@example.com"
                    f.seek(0)
                    json.dump(cfg, f, indent=2)
                    f.truncate()
            except Exception:
                pass

    # 2. Portfolio (Initial paper account)
    portfolio_file = TRADER_DIR / "portfolio.json"
    if not portfolio_file.is_file():
        init_portfolio = {
            "cash": 5000.0,
            "positions": []
        }
        with open(portfolio_file, "w", encoding="utf-8") as f:
            json.dump(init_portfolio, f, indent=2)

    # 3. Alerts
    alerts_file = TRADER_DIR / "alerts.json"
    if not alerts_file.is_file():
        example_alerts = REPO_DIR / "trader-alerts" / "alerts.example.json"
        if example_alerts.is_file():
            shutil.copy(example_alerts, alerts_file)

def get_lan_ip() -> str:
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def print_banner(host: str, port: int):
    lan_ip = get_lan_ip()
    local_url = f"http://localhost:{port}"
    mobile_url = f"http://{lan_ip}:{port}"
    cfg_file = TRADER_DIR / "config.json"
    port_file = TRADER_DIR / "portfolio.json"
    cash = 50.0
    max_loss = 1.50
    daily_loss = 4.50
    try:
        if port_file.is_file():
            with open(port_file, "r") as f:
                cash = float(json.load(f).get("cash", 50.0))
        if cfg_file.is_file():
            with open(cfg_file, "r") as f:
                cfg = json.load(f)
                max_loss = float(cfg.get("max_loss_per_trade_usd", 1.50))
                daily_loss = float(cfg.get("max_daily_loss_usd", 4.50))
    except Exception:
        pass

    banner = f"""
================================================================================
                    ⚡ DAY TRADER REAL-TIME STATION ⚡
        Algorithmic Scanning • 10,000-Replay Edge Engine • Risk Gates
================================================================================

  ► Web Dashboard (PC):   {local_url}
  ► Mobile Phone (Wi-Fi): {mobile_url}
  ► WebSocket Feed:       ws://{lan_ip}:{port}/ws
  ► Broker Mode:          Tiger Brokers NZ (US Stock & Fractional Fee Engine)
  ► Account Balance:      ${cash:.2f} USD ($200.00 Initial Capital)
  ► Max Loss Per Trade:   ${max_loss:.2f} USD
  ► Daily Loss Limit:     ${daily_loss:.2f} USD (Max 4 trades/day)
  ► Flat-by-Close Rule:   15:55 ET / 09:55 NZDT (Mandatory, zero overnight hold)
  ► Daily Report:         Auto email via Resend to khanalnischal2075@gmail.com

  24/7 Autonomous Operation Active. System ready to trade during NZDT market window.
================================================================================
"""
    print(banner)

def main():
    parser = argparse.ArgumentParser(description="Launch Day Trader Station")
    parser.add_argument("--host", default="0.0.0.0", help="Host interface (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080)")
    parser.add_argument("--demo", action="store_true", help="Pre-load TSLA reel demo trade on start")
    args = parser.parse_args()

    # Ensure python version
    if sys.version_info < (3, 8):
        sys.exit("Error: Python 3.8 or newer is required.")

    setup_workspace()
    print_banner(args.host, args.port)

    # Import and run dashboard server
    sys.path.insert(0, str(REPO_DIR))
    from dashboard.server import init_app
    from aiohttp import web
    
    web.run_app(init_app(), host=args.host, port=args.port, print=lambda msg: None)

if __name__ == "__main__":
    main()
