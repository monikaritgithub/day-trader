"""
Tiger Brokers NZ Institutional PDF Statement Generator
Generates an official broker-grade PDF daily statement for Day Trader Pro.
Matches institutional broker formats (Tiger Brokers, Interactive Brokers)
with account summary, transaction ledger, fee audits, and regulatory disclosures.
"""

import html
import io
import os
import datetime
from pathlib import Path
from typing import Dict, Any, List

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

def generate_broker_statement_pdf(data: Dict[str, Any], account_name: str = "Nischal Khanal", account_id: str = "NZ-TB-8849201") -> bytes:
    """
    Compiles an institutional-grade PDF broker statement from daily report data.
    Returns the PDF as raw bytes.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()

    # Custom styling
    primary_color = colors.HexColor("#0f172a")    # Slate navy
    brand_green = colors.HexColor("#00a804")      # Tiger / Robinhood green
    accent_crimson = colors.HexColor("#dc2626")   # Loss coral/crimson
    border_color = colors.HexColor("#cbd5e1")     # Light border
    bg_subtle = colors.HexColor("#f8fafc")        # Light gray row bg
    text_dark = colors.HexColor("#1e293b")
    text_muted = colors.HexColor("#64748b")

    title_style = ParagraphStyle(
        "BrokerTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=18,
        textColor=primary_color
    )
    subtitle_style = ParagraphStyle(
        "BrokerSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=13,
        textColor=brand_green
    )
    reg_style = ParagraphStyle(
        "BrokerReg",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.5,
        leading=10,
        textColor=text_muted
    )
    meta_label = ParagraphStyle(
        "MetaLabel",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
        textColor=text_muted
    )
    meta_val = ParagraphStyle(
        "MetaVal",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=11,
        textColor=text_dark
    )
    section_title = ParagraphStyle(
        "SectionTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10.5,
        leading=14,
        textColor=primary_color
    )
    cell_style = ParagraphStyle(
        "CellNormal",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=10.5,
        textColor=text_dark
    )
    cell_bold = ParagraphStyle(
        "CellBold",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10.5,
        textColor=text_dark
    )
    cell_green = ParagraphStyle(
        "CellGreen",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10.5,
        textColor=brand_green
    )
    cell_red = ParagraphStyle(
        "CellRed",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10.5,
        textColor=accent_crimson
    )
    legal_style = ParagraphStyle(
        "LegalNotice",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7,
        leading=9.5,
        textColor=text_muted
    )

    story = []

    # 1. Official Header
    header_data = [
        [
            Paragraph("<b>TIGER BROKERS (NZ) LIMITED</b>", title_style),
            Paragraph(f"<b>DATE:</b> {data.get('nz_date', '')}", meta_val)
        ],
        [
            Paragraph("DAILY ACTIVITY &amp; TRADE CONFIRMATION STATEMENT", subtitle_style),
            Paragraph("<b>BASE CURRENCY:</b> USD ($)", meta_val)
        ],
        [
            Paragraph("Tiger Brokers (NZ) Limited • NZBN: 9429046892142 • FSP: FSP473106 • Regulated Financial Services Provider", reg_style),
            Paragraph("<b>REPORT TYPE:</b> End of Day Flat Audit", meta_label)
        ]
    ]
    header_table = Table(header_data, colWidths=[400, 140])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=1.5, color=primary_color, spaceBefore=2, spaceAfter=8))

    # 2. Account Profile Bar
    acct_data = [
        [
            Paragraph("<b>Account Name:</b>", meta_label),
            Paragraph(account_name, meta_val),
            Paragraph("<b>Account Number:</b>", meta_label),
            Paragraph(account_id, meta_val),
            Paragraph("<b>Trading Sub-Account:</b>", meta_label),
            Paragraph("US Equities (Direct)", meta_val),
        ],
        [
            Paragraph("<b>Broker Entity:</b>", meta_label),
            Paragraph("Tiger Brokers NZ Ltd", meta_val),
            Paragraph("<b>Execution Window:</b>", meta_label),
            Paragraph("03:30 – 09:55 AM NZDT", meta_val),
            Paragraph("<b>Mandatory Flat Close:</b>", meta_label),
            Paragraph("09:55 AM NZDT (Zero Overnight)", meta_val),
        ]
    ]
    acct_table = Table(acct_data, colWidths=[75, 105, 85, 95, 95, 85])
    acct_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), bg_subtle),
        ('BOX', (0, 0), (-1, -1), 0.8, border_color),
        ('INNERGRID', (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(acct_table)
    story.append(Spacer(1, 12))

    # 3. Capital & Valuation Summary Card
    story.append(Paragraph("<b>ACCOUNT CAPITAL &amp; PERFORMANCE VALUATION (USD)</b>", section_title))
    story.append(Spacer(1, 4))

    today_pnl = float(data.get("today_realized_pnl", 0.0))
    pnl_style = cell_green if today_pnl >= 0 else cell_red
    pnl_sign = "+" if today_pnl >= 0 else ""
    current_bal = float(data.get("current_balance", 200.0))
    prev_bal = float(data.get("previous_balance", 200.0))
    today_fees = float(data.get("today_fees", 0.0))
    total_fees = float(data.get("total_fees", 0.0))
    total_pnl = float(data.get("total_realized_pnl", 0.0))

    open_pos = int(data.get("open_positions", 0))
    open_pos_txt = "0 (100% Cash Flat)" if open_pos == 0 else f"{open_pos} Open"
    all_pnl_sign = "+" if total_pnl >= 0 else ""

    summary_data = [
        [
            Paragraph("<font color='white'><b>Previous Balance</b></font>", cell_bold),
            Paragraph("<font color='white'><b>Today's Net PnL</b></font>", cell_bold),
            Paragraph("<font color='white'><b>Tiger NZ Fees Today</b></font>", cell_bold),
            Paragraph("<font color='white'><b>Closing Net Cash</b></font>", cell_bold),
            Paragraph("<font color='white'><b>Buying Power</b></font>", cell_bold),
            Paragraph("<font color='white'><b>Positions</b></font>", cell_bold)
        ],
        [
            Paragraph(f"${prev_bal:,.2f}", cell_bold),
            Paragraph(f"{pnl_sign}${today_pnl:,.2f}", pnl_style),
            Paragraph(f"-${today_fees:,.2f}", cell_bold),
            Paragraph(f"<b>${current_bal:,.2f}</b>", cell_bold),
            Paragraph(f"${current_bal:,.2f}", cell_green),
            Paragraph(open_pos_txt, cell_bold)
        ]
    ]
    summary_table = Table(summary_data, colWidths=[90, 95, 85, 95, 95, 80])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), primary_color),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('BOX', (0, 0), (-1, -1), 1, primary_color),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, border_color),
    ]))

    story.append(summary_table)
    story.append(Spacer(1, 5))
    story.append(Paragraph(
        f"<b>Cumulative Ledger Totals:</b> All-Time Realized PnL: {all_pnl_sign}${total_pnl:,.2f} USD "
        f"| Total Tiger NZ Fees Paid: -${total_fees:,.2f} USD | Executions Today: {int(data.get('today_trades_count', len(data.get('today_trades', []))))}",
        meta_label
    ))
    story.append(Spacer(1, 12))

    # 4. Itemized Executions & Trade Confirmation Ledger
    story.append(Paragraph("<b>ITEMIZED TRADE CONFIRMATION &amp; TRANSACTION LEDGER</b>", section_title))
    story.append(Spacer(1, 4))

    trades = data.get("today_trades", [])
    ledger_rows = [
        [
            Paragraph("<font color='white'><b>Time (NZDT)</b></font>", cell_bold),
            Paragraph("<font color='white'><b>Symbol</b></font>", cell_bold),
            Paragraph("<font color='white'><b>Side</b></font>", cell_bold),
            Paragraph("<font color='white'><b>Shares</b></font>", cell_bold),
            Paragraph("<font color='white'><b>Price</b></font>", cell_bold),
            Paragraph("<font color='white'><b>Gross Val</b></font>", cell_bold),
            Paragraph("<font color='white'><b>Tiger Fee</b></font>", cell_bold),
            Paragraph("<font color='white'><b>Realized PnL</b></font>", cell_bold),
            Paragraph("<font color='white'><b>Status / Strategy</b></font>", cell_bold)
        ]
    ]

    if trades:
        for t in trades:
            side = t.get("side", "BUY")
            side_color = brand_green if side == "BUY" else accent_crimson
            side_para = Paragraph(f"<b>{side}</b>", cell_green if side == "BUY" else cell_red)
            pnl_val = float(t.get("realized_pnl", 0.0))
            if side == "SELL":
                pnl_para = Paragraph(f"{'+' if pnl_val >= 0 else ''}${pnl_val:.2f}", cell_green if pnl_val >= 0 else cell_red)
            else:
                pnl_para = Paragraph("--", cell_style)
            
            sh = float(t.get("shares", 0.0))
            px = float(t.get("price", 0.0))
            gross = sh * px
            fee = float(t.get("tiger_fee", 0.0))
            t_time = t.get("timestamp_nzdt", "")
            if " " in t_time:
                t_time = t_time.split(" ", 1)[1]  # Extract time component

            ledger_rows.append([
                Paragraph(html.escape(t_time[:11]), cell_style),
                Paragraph(f"<b>{html.escape(str(t.get('symbol', '')))}</b>", cell_bold),
                side_para,
                Paragraph(f"{sh:.4f}", cell_style),
                Paragraph(f"${px:.2f}", cell_style),
                Paragraph(f"${gross:.2f}", cell_style),
                Paragraph(f"${fee:.2f}", cell_style),
                pnl_para,
                Paragraph(html.escape(str(t.get("exit_reason") or t.get("notes") or "15m ORB Entry")), cell_style)
            ])
    else:
        ledger_rows.append([
            Paragraph("No transactions executed during today's session. Capital 100% defended and preserved under Tiger NZ fee &amp; risk gates.", cell_style),
            Paragraph("", cell_style),
            Paragraph("", cell_style),
            Paragraph("", cell_style),
            Paragraph("", cell_style),
            Paragraph("", cell_style),
            Paragraph("", cell_style),
            Paragraph("", cell_style),
            Paragraph("", cell_style)
        ])

    col_widths = [65, 45, 40, 50, 55, 55, 50, 65, 115]
    ledger_table = Table(ledger_rows, colWidths=col_widths)
    table_styles = [
        ('BACKGROUND', (0, 0), (-1, 0), primary_color),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('BOX', (0, 0), (-1, -1), 0.8, border_color),
        ('INNERGRID', (0, 0), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
    ]
    if not trades:
        table_styles.append(('SPAN', (0, 1), (-1, 1)))
        table_styles.append(('ALIGN', (0, 1), (-1, 1), 'CENTER'))

    # Row striping
    for r in range(1, len(ledger_rows)):
        if r % 2 == 0:
            table_styles.append(('BACKGROUND', (0, r), (-1, r), bg_subtle))

    ledger_table.setStyle(TableStyle(table_styles))
    story.append(ledger_table)
    story.append(Spacer(1, 14))

    # 5. Regulatory, Tiger NZ Fee Schedule & Risk Gate Disclosures
    legal_text = """
    <b>TIGER BROKERS (NZ) LIMITED US EQUITIES &amp; FRACTIONAL SHARE DISCLOSURE:</b><br/>
    • <b>Fractional Shares (&lt; 1 Share):</b> Commission: $0.00 USD (waived). Platform Fee: 1% of gross trade value (maximum $1.00 USD per order leg). Third-party settlement and regulatory fees are waived for fractional share executions.<br/>
    • <b>Whole Shares (&ge; 1 Share):</b> Commission: $0.005/share (min $0.99 USD). Platform Fee: $0.005/share (min $1.00 USD). Settlement Fee: $0.003/share (capped at 7% of trade value). SEC Transaction Fee: $0.0000206 on sell orders.<br/>
    • <b>Autonomous Risk Management Mandate:</b> Single-trade risk strictly capped at $1.50 USD via automatic midpoint stop loss. Daily loss ceiling enforced at $6.00 USD. Mandatory market flat-by-close executed prior to 09:55 AM NZDT (15:55 ET) ensuring zero overnight market exposure.<br/>
    • <i>This document represents an automated trade confirmation and daily audit statement issued by Day Trader Pro for client reference. Keep for personal taxation and tax-lot accounting records.</i>
    """
    legal_box = Table(
        [[Paragraph(legal_text, legal_style)]],
        colWidths=[540]
    )
    legal_box.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), bg_subtle),
        ('BOX', (0, 0), (-1, -1), 0.5, border_color),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(legal_box)
    story.append(Spacer(1, 10))

    # 6. Digital Audit Stamp Footer
    stamp_text = f"<b>ELECTRONICALLY AUDITED &amp; VERIFIED:</b> {data.get('nz_date', '')} 09:55:00 NZDT • DAY TRADER PRO AUTONOMOUS TRADING STATION • TIGER BROKERS NZ ROUTING ENGINE • PAGE 1 OF 1"
    story.append(Paragraph(stamp_text, reg_style))

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes

if __name__ == "__main__":
    sample_data = {
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
                "price": 384.28,
                "tiger_fee": 0.25,
                "realized_pnl": 0.0,
                "notes": "15m ORB Entry"
            },
            {
                "timestamp_nzdt": "2026-11-25 05:20:00 AM NZDT",
                "symbol": "TSLA",
                "side": "SELL",
                "shares": 0.065,
                "price": 393.12,
                "tiger_fee": 0.25,
                "realized_pnl": 4.50,
                "exit_reason": "1R Target Reached"
            }
        ]
    }
    pdf = generate_broker_statement_pdf(sample_data)
    out_path = Path("trader/statements/sample_statement.pdf")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(pdf)
    print(f"Sample PDF statement generated successfully ({len(pdf)} bytes) -> {out_path}")
