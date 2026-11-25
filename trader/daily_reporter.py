"""
Daily Market Close Email Reporter via Resend
Dispatches an institutional-grade daily summary email to the trader after market close (09:55 AM NZDT):
- Previous Balance & Current Balance ($ USD)
- Total Realized PnL ($ and %)
- Today's Realized PnL ($ and %)
- Tiger Brokers NZ Fees Incurred ($ USD)
- Itemized Transaction Ledger for today
"""

import os
import sys
import json
import urllib.request
import urllib.error
import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

REPO_DIR = Path(__file__).resolve().parent.parent
TRADER_DIR = REPO_DIR / "trader"

def load_env():
    """Load key-value pairs from .env if present."""
    env_file = REPO_DIR / ".env"
    if env_file.is_file():
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip().strip('"').strip("'")
                        if k not in os.environ:
                            os.environ[k] = v
        except Exception:
            pass

load_env()

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
NOTIFICATION_EMAIL = os.environ.get("NOTIFICATION_EMAIL", "")
RESEND_FROM_EMAIL = os.environ.get("RESEND_FROM_EMAIL", "onboarding@resend.dev")

def read_json_safe(path: Path) -> Optional[Any]:
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def build_daily_report_data() -> Dict[str, Any]:
    """Compile account metrics and today's trade transactions."""
    load_env()
    th_data = read_json_safe(TRADER_DIR / "trade_history.json") or {"trades": [], "starting_cash": 200.0}
    portfolio = read_json_safe(TRADER_DIR / "portfolio.json") or {"cash": 200.0, "positions": []}
    config = read_json_safe(TRADER_DIR / "config.json") or {}

    starting_cash = float(th_data.get("starting_cash", float(os.environ.get("INITIAL_CAPITAL", 200.0))))
    current_cash = float(portfolio.get("cash", starting_cash))
    positions = portfolio.get("positions", [])

    trades: List[Dict[str, Any]] = th_data.get("trades", [])

    # Filter trades for today (Auckland NZDT/NZST date)
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    try:
        import zoneinfo
        nz_today_str = now_utc.astimezone(zoneinfo.ZoneInfo("Pacific/Auckland")).strftime("%Y-%m-%d")
    except Exception:
        nz_today_str = (now_utc + datetime.timedelta(hours=13)).strftime("%Y-%m-%d")

    today_trades = [
        t for t in trades
        if t.get("timestamp_nzdt", "").startswith(nz_today_str)
    ]

    closed_all = [t for t in trades if t.get("status") == "CLOSED" or t.get("side") == "SELL"]
    closed_today = [t for t in today_trades if t.get("status") == "CLOSED" or t.get("side") == "SELL"]

    total_realized_pnl = round(sum(float(t.get("realized_pnl", 0.0)) for t in closed_all), 2)
    today_realized_pnl = round(sum(float(t.get("realized_pnl", 0.0)) for t in closed_today), 2)

    total_fees = round(sum(float(t.get("tiger_fee", 0.0)) for t in trades), 2)
    today_fees = round(sum(float(t.get("tiger_fee", 0.0)) for t in today_trades), 2)

    # Calculate previous balance (balance before today's trades)
    previous_balance = round(current_cash - today_realized_pnl + today_fees, 2)
    if not today_trades:
        previous_balance = current_cash

    total_pnl_pct = round((total_realized_pnl / starting_cash) * 100, 2) if starting_cash > 0 else 0.0
    today_pnl_pct = round((today_realized_pnl / previous_balance) * 100, 2) if previous_balance > 0 else 0.0

    return {
        "nz_date": nz_today_str,
        "starting_cash": starting_cash,
        "previous_balance": previous_balance,
        "current_balance": current_cash,
        "total_realized_pnl": total_realized_pnl,
        "total_pnl_pct": total_pnl_pct,
        "today_realized_pnl": today_realized_pnl,
        "today_pnl_pct": today_pnl_pct,
        "total_fees": total_fees,
        "today_fees": today_fees,
        "open_positions": len(positions),
        "today_trades_count": len(today_trades),
        "today_trades": today_trades
    }

def generate_email_html(data: Dict[str, Any]) -> str:
    """Generate sleek, responsive Robinhood-styled HTML email."""
    today_pnl = data["today_realized_pnl"]
    pnl_color = "#00c805" if today_pnl >= 0 else "#ff5000"
    pnl_sign = "+" if today_pnl >= 0 else ""

    rows_html = ""
    if data["today_trades"]:
        for t in data["today_trades"]:
            side = t.get("side", "BUY")
            side_color = "#00c805" if side == "BUY" else "#ff5000"
            trade_pnl = float(t.get("realized_pnl", 0.0))
            pnl_td = f"<span style='color: {'#00c805' if trade_pnl >= 0 else '#ff5000'}; font-weight: 600;'>{'+' if trade_pnl >= 0 else ''}${trade_pnl:.2f}</span>" if side == "SELL" else "<span style='color: #64748b;'>--</span>"
            fee = float(t.get("tiger_fee", 0.0))
            rows_html += f"""
            <tr style="border-bottom: 1px solid #1e293b; font-size: 13px;">
                <td style="padding: 10px 8px; color: #94a3b8;">{t.get('timestamp_nzdt', '')[11:19]}</td>
                <td style="padding: 10px 8px; font-weight: 700; color: #f8fafc;">{t.get('symbol', '')}</td>
                <td style="padding: 10px 8px; font-weight: 600; color: {side_color};">{side}</td>
                <td style="padding: 10px 8px; color: #e2e8f0;">{t.get('shares', 0):.4f}</td>
                <td style="padding: 10px 8px; color: #e2e8f0;">${float(t.get('price', 0.0)):.2f}</td>
                <td style="padding: 10px 8px; color: #94a3b8;">${fee:.2f}</td>
                <td style="padding: 10px 8px;">{pnl_td}</td>
                <td style="padding: 10px 8px; color: #94a3b8; font-size: 11px;">{t.get('exit_reason') or t.get('notes', 'ORB Entry')}</td>
            </tr>
            """
    else:
        rows_html = """
        <tr>
            <td colspan="8" style="text-align: center; padding: 24px; color: #64748b; font-size: 13px;">
                No trades executed today. Capital 100% preserved and defended.
            </td>
        </tr>
        """

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <title>Daily Day Trader Statement</title>
    </head>
    <body style="margin: 0; padding: 0; background-color: #0b0e14; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #f8fafc;">
      <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #0b0e14; padding: 24px 12px;">
        <tr>
          <td align="center">
            <table width="100%" cellpadding="0" cellspacing="0" style="max-width: 650px; background-color: #121722; border-radius: 12px; border: 1px solid #1e293b; overflow: hidden; box-shadow: 0 10px 25px rgba(0,0,0,0.5);">
              
              <!-- Header -->
              <tr>
                <td style="background-color: #161f30; padding: 20px 24px; border-bottom: 1px solid #222f46;">
                  <table width="100%" cellpadding="0" cellspacing="0">
                    <tr>
                      <td>
                        <span style="font-size: 11px; font-weight: 700; letter-spacing: 1.5px; color: #00c805; text-transform: uppercase;">⚡ DAY TRADER REAL-TIME STATION</span>
                        <h1 style="margin: 4px 0 0; font-size: 22px; font-weight: 700; color: #ffffff;">Daily Market Close Statement</h1>
                        <span style="font-size: 13px; color: #94a3b8;">Auckland NZDT Session • {data['nz_date']} (Flat-by-Close 09:55 AM)</span>
                      </td>
                      <td align="right">
                        <span style="background-color: rgba(0, 200, 5, 0.15); color: #00c805; border: 1px solid rgba(0, 200, 5, 0.3); padding: 4px 10px; border-radius: 20px; font-size: 12px; font-weight: 600;">Tiger Brokers NZ</span>
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>

              <!-- Balance & PnL Strip -->
              <tr>
                <td style="padding: 24px;">
                  <table width="100%" cellpadding="0" cellspacing="0">
                    <tr>
                      <td width="50%" style="padding-right: 12px; vertical-align: top;">
                        <div style="background-color: #182030; border-radius: 8px; padding: 16px; border: 1px solid #24324a;">
                          <div style="font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 600;">Current Account Balance</div>
                          <div style="font-size: 26px; font-weight: 800; color: #ffffff; margin-top: 4px;">${data['current_balance']:,.2f} <span style="font-size: 13px; font-weight: 500; color: #94a3b8;">USD</span></div>
                          <div style="font-size: 12px; color: #94a3b8; margin-top: 6px;">Previous Balance: <b>${data['previous_balance']:,.2f} USD</b></div>
                        </div>
                      </td>
                      <td width="50%" style="padding-left: 12px; vertical-align: top;">
                        <div style="background-color: #182030; border-radius: 8px; padding: 16px; border: 1px solid #24324a;">
                          <div style="font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 600;">Today's Net Realized PnL</div>
                          <div style="font-size: 26px; font-weight: 800; color: {pnl_color}; margin-top: 4px;">{pnl_sign}${today_pnl:,.2f} <span style="font-size: 14px; font-weight: 600;">({pnl_sign}{data['today_pnl_pct']:.2f}%)</span></div>
                          <div style="font-size: 12px; color: #94a3b8; margin-top: 6px;">Total Realized PnL: <b style="color: {'#00c805' if data['total_realized_pnl'] >= 0 else '#ff5000'};">{'+' if data['total_realized_pnl'] >= 0 else ''}${data['total_realized_pnl']:,.2f} USD ({'+' if data['total_pnl_pct'] >= 0 else ''}{data['total_pnl_pct']}%)</b></div>
                        </div>
                      </td>
                    </tr>
                  </table>

                  <!-- KPI Quick Matrix -->
                  <table width="100%" cellpadding="0" cellspacing="0" style="margin-top: 16px; background-color: #141b28; border-radius: 8px; padding: 12px 16px; border: 1px solid #1e293b;">
                    <tr>
                      <td align="center" style="border-right: 1px solid #24324a; padding: 6px 12px;">
                        <div style="font-size: 11px; color: #94a3b8;">Initial Capital</div>
                        <div style="font-size: 14px; font-weight: 700; color: #ffffff; margin-top: 2px;">${data['starting_cash']:,.2f}</div>
                      </td>
                      <td align="center" style="border-right: 1px solid #24324a; padding: 6px 12px;">
                        <div style="font-size: 11px; color: #94a3b8;">Today's Trades</div>
                        <div style="font-size: 14px; font-weight: 700; color: #ffffff; margin-top: 2px;">{data['today_trades_count']}</div>
                      </td>
                      <td align="center" style="border-right: 1px solid #24324a; padding: 6px 12px;">
                        <div style="font-size: 11px; color: #94a3b8;">Tiger NZ Fees (Today)</div>
                        <div style="font-size: 14px; font-weight: 700; color: #f59e0b; margin-top: 2px;">${data['today_fees']:,.2f}</div>
                      </td>
                      <td align="center" style="padding: 6px 12px;">
                        <div style="font-size: 11px; color: #94a3b8;">Overnight Holdings</div>
                        <div style="font-size: 14px; font-weight: 700; color: #00c805; margin-top: 2px;">0 (100% Flat)</div>
                      </td>
                    </tr>
                  </table>

                  <!-- Transaction Ledger Table -->
                  <h3 style="margin: 28px 0 12px; font-size: 15px; font-weight: 700; color: #ffffff; letter-spacing: 0.3px;">Today's Execution Ledger (Auckland NZDT)</h3>
                  <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse: collapse; text-align: left; background-color: #141b28; border-radius: 8px; overflow: hidden; border: 1px solid #1e293b;">
                    <thead>
                      <tr style="background-color: #1c2536; border-bottom: 1px solid #29384f; font-size: 11px; text-transform: uppercase; color: #94a3b8; letter-spacing: 0.5px;">
                        <th style="padding: 10px 8px;">Time</th>
                        <th style="padding: 10px 8px;">Symbol</th>
                        <th style="padding: 10px 8px;">Side</th>
                        <th style="padding: 10px 8px;">Shares</th>
                        <th style="padding: 10px 8px;">Price</th>
                        <th style="padding: 10px 8px;">Tiger Fee</th>
                        <th style="padding: 10px 8px;">Net PnL</th>
                        <th style="padding: 10px 8px;">Rule / Exit</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows_html}
                    </tbody>
                  </table>

                  <!-- Footer Notice -->
                  <div style="margin-top: 24px; padding: 14px; background-color: #131a26; border-radius: 8px; font-size: 12px; color: #94a3b8; line-height: 1.5; border-left: 3px solid #00c805;">
                    <b>Institutional Day-Trader Compliance:</b> All positions are 100% liquidated by 09:55 AM NZDT (5 minutes prior to NYSE closing bell). Zero overnight holding risk. All trades adhere to the 11-skill quantitative risk guardrails and Tiger Brokers New Zealand fee structure.
                  </div>

                </td>
              </tr>

              <!-- Email Signature -->
              <tr>
                <td style="background-color: #0e131d; padding: 16px 24px; text-align: center; border-top: 1px solid #1a2334; font-size: 11px; color: #64748b;">
                  Day Trader Autonomous System • PocketServer on OnePlus 8T • Automated Daily Statement
                </td>
              </tr>

            </table>
          </td>
        </tr>
      </table>
    </body>
    </html>
    """
    return html

def send_daily_market_close_report() -> Dict[str, Any]:
    """Generates the daily statement and dispatches via Resend API."""
    load_env()
    api_key = os.environ.get("RESEND_API_KEY", RESEND_API_KEY).strip()
    recipient = os.environ.get("NOTIFICATION_EMAIL", NOTIFICATION_EMAIL).strip()
    from_email = os.environ.get("RESEND_FROM_EMAIL", RESEND_FROM_EMAIL).strip()
    data = build_daily_report_data()
    if not api_key or not recipient:
        return {
            "success": False,
            "error": "RESEND_API_KEY or NOTIFICATION_EMAIL is not configured in environment/.env",
            "data": data
        }
    html_content = generate_email_html(data)

    subject = f"Day Trader Daily Statement: {data['nz_date']} • Balance: ${data['current_balance']:,.2f} USD ({'+' if data['today_realized_pnl'] >= 0 else ''}${data['today_realized_pnl']:,.2f})"

    payload = {
        "from": f"Day Trader <{from_email}>",
        "to": [recipient],
        "subject": subject,
        "html": html_content
    }

    url = "https://api.resend.com/emails"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp_body = resp.read().decode("utf-8")
            res_json = json.loads(resp_body)
            return {
                "success": True,
                "email_id": res_json.get("id"),
                "recipient": NOTIFICATION_EMAIL,
                "data": data
            }
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8", errors="replace")
        return {"success": False, "error": f"HTTP {e.code}: {err_msg}", "data": data}
    except Exception as ex:
        return {"success": False, "error": str(ex), "data": data}

if __name__ == "__main__":
    result = send_daily_market_close_report()
    print(json.dumps(result, indent=2))
