/**
 * Static GitHub Pages Runtime Adapter for Day Trader Pro
 * Provides an interactive browser-side simulation of the 11-skill pipeline
 * and Tiger Brokers NZ Fractional Share Fee & Net-Profit Gate when hosted
 * without the local Python/aiohttp backend.
 */
(function () {
  const isLocalBackend =
    window.location.hostname === "localhost" ||
    window.location.hostname === "127.0.0.1";
  if (isLocalBackend) return;

  const STORAGE_KEY = "day_trader_pages_state_v1";
  const PRICES = {
    TSLA: 384.68,
    NVDA: 155.38,
    AAPL: 354.07,
    AMD: 413.27,
    PLTR: 161.18,
    SOFI: 12.86,
    GME: 27.48,
    MSFT: 496.13,
    AMZN: 255.39,
    META: 597.60,
    GOOGL: 282.10,
    COIN: 108.78,
    MARA: 5.58,
    INTC: 59.66,
    SMCI: 24.53,
  };

  const NAMES = {
    TSLA: "Tesla, Inc.",
    NVDA: "NVIDIA Corporation",
    AAPL: "Apple Inc.",
    AMD: "Advanced Micro Devices",
    PLTR: "Palantir Technologies",
    SOFI: "SoFi Technologies",
    GME: "GameStop Corp.",
    MSFT: "Microsoft Corp.",
    AMZN: "Amazon.com Inc.",
    META: "Meta Platforms Inc.",
    GOOGL: "Alphabet Inc.",
    COIN: "Coinbase Global",
    MARA: "MARA Holdings",
    INTC: "Intel Corp.",
    SMCI: "Super Micro Computer",
  };

  // Tiger Brokers NZ US Stocks & Fractional Fee Schedule:
  // - Fractional (< 1 share): Commission $0 (waived), Platform Fee 1% (max $1.00), 3rd-party fees waived
  // - Whole (>= 1 share): Commission $0.005/sh (min $0.99), Platform $0.005/sh (min $1.00), Settlement $0.003/sh, SEC 0.0000206 on SELL
  function calcTigerNZFee(side, shares, price, conservativeReg = false) {
    const sh = Math.abs(Number(shares || 0));
    const px = Math.abs(Number(price || 0));
    const val = Math.round(sh * px * 10000) / 10000;
    if (sh <= 0 || val <= 0) {
      return { total_fee: 0, commission: 0, platform_fee: 0, regulatory_fees: 0, is_fractional: false };
    }
    const isFrac = sh < 0.9999;
    let commission = 0;
    let platform = 0;
    let settlement = 0;
    if (isFrac) {
      commission = 0;
      platform = Math.round(Math.min(1.0, Math.max(0.01, val * 0.01)) * 100) / 100;
    } else {
      commission = Math.max(0.99, Math.round(sh * 0.005 * 100) / 100);
      platform = Math.max(1.0, Math.round(sh * 0.005 * 100) / 100);
      settlement = Math.min(Math.round(val * 0.07 * 100) / 100, Math.round(sh * 0.003 * 100) / 100);
    }
    let reg = 0;
    if (String(side).toUpperCase() === "SELL") {
      if (!isFrac || conservativeReg) {
        reg = Math.max(0.01, Math.round(val * 0.0000206 * 100) / 100);
      }
    }
    const total = Math.round((commission + platform + settlement + reg) * 100) / 100;
    return { total_fee: total, commission, platform_fee: platform, settlement_fee: settlement, regulatory_fees: reg, is_fractional: isFrac };
  }

  function buildOrbGeometry(sym) {
    const px = PRICES[sym] || 100.0;
    // Realistic 15m Opening Range (~1.8% width for volatile US tech/growth)
    const orLow = Math.round(px * 0.978 * 100) / 100;
    const orHigh = Math.round(px * 0.996 * 100) / 100;
    const entry = Math.round(orHigh * 1.003 * 100) / 100; // +0.3% breakout close above OR high
    // Match trader-exit/exit.py: long midpoint stop rounded DOWN (ROUND_FLOOR) to cent
    const stop = Math.floor(((orHigh + orLow) / 2) * 100 + 1e-9) / 100;
    const risk = Math.max(0.01, Math.round((entry - stop) * 100) / 100);
    return { px, orLow, orHigh, entry, stop, risk };
  }

  function evaluateTigerPlan(symbol, entry, stop, target, targetUsd = 25.0, maxLossUsd = 1.50, minNetProfit = 0.05) {
    const risk = entry - stop;
    if (risk <= 0 || target <= entry) {
      return { approved: false, shares: 0, economics: { expected_net_profit: 0, round_trip_fee: 0, breakeven_win_rate_pct: 100, reason: "Invalid stop/target geometry" } };
    }
    const rawSh = Math.round((targetUsd / entry) * 10000) / 10000;
    // Prioritize < 1 share fractional order when >= 1 share would trigger $1.99/leg minimums
    const sh = rawSh >= 1.0 && 0.999 * entry >= 1.0 ? 0.999 : rawSh;
    const buyFee = calcTigerNZFee("BUY", sh, entry, false).total_fee;
    const sellFee = calcTigerNZFee("SELL", sh, target, false).total_fee;
    const stopSellFee = calcTigerNZFee("SELL", sh, stop, false).total_fee;
    const rtFee = Math.round((buyFee + sellFee) * 100) / 100;
    const stopRtFee = Math.round((buyFee + stopSellFee) * 100) / 100;
    const grossProfit = Math.round(sh * (target - entry) * 100) / 100;
    const netProfit = Math.round((grossProfit - rtFee) * 100) / 100;
    const stopLoss = Math.round((sh * risk + stopRtFee) * 100) / 100;
    const breakeven = netProfit > 0 ? Math.round((stopLoss / (netProfit + stopLoss)) * 1000) / 10 : 100.0;
    const approved = netProfit >= minNetProfit && netProfit > 0 && stopLoss <= maxLossUsd + 0.05;
    const reason = approved
      ? `Net +$${netProfit.toFixed(2)} after $${rtFee.toFixed(2)} Tiger NZ fees (${sh.toFixed(4)} sh fractional, BE win rate ${breakeven.toFixed(1)}%)`
      : `Rejected: gross $${grossProfit.toFixed(2)} - Tiger NZ fees $${rtFee.toFixed(2)} = $${netProfit.toFixed(2)} net (below $${minNetProfit.toFixed(2)} min)`;
    return {
      approved,
      shares: sh,
      is_fractional: sh < 0.9999,
      economics: {
        verified: true,
        profitable: netProfit >= minNetProfit && netProfit > 0,
        shares: sh,
        is_fractional: sh < 0.9999,
        buy_fee: buyFee,
        sell_fee: sellFee,
        round_trip_fee: rtFee,
        gross_profit: grossProfit,
        expected_net_profit: netProfit,
        net_loss_at_stop: stopLoss,
        breakeven_win_rate_pct: breakeven,
        reason,
      },
    };
  }

  function selectViableTarget(sym, entry, stop, risk, usd) {
    // Follow trader-exit default 2R first, then 3R if 2R doesn't clear Tiger NZ round-trip fees
    for (const rMult of [2, 3]) {
      const target = Math.round((entry + rMult * risk) * 100 + 1e-9) / 100;
      const ev = evaluateTigerPlan(sym, entry, stop, target, usd, 1.5, 0.05);
      if (ev.approved) {
        return { rMult, target, tiger: ev };
      }
    }
    const fallbackTarget = Math.round((entry + 2 * risk) * 100 + 1e-9) / 100;
    return { rMult: 2, target: fallbackTarget, tiger: evaluateTigerPlan(sym, entry, stop, fallbackTarget, usd, 1.5, 0.05) };
  }

  function buildApprovedList(usdAmount = 25) {
    const out = [];
    for (const sym of ["TSLA", "NVDA", "AAPL", "AMD", "PLTR", "SOFI", "GME"]) {
      const { px, entry, stop, risk } = buildOrbGeometry(sym);
      const { rMult, target, tiger } = selectViableTarget(sym, entry, stop, risk, usdAmount);
      if (!tiger.approved) continue;
      const econ = tiger.economics;
      out.push({
        symbol: sym,
        name: NAMES[sym] || sym,
        price: px,
        change_pct: sym === "NVDA" ? 3.12 : sym === "TSLA" ? 2.50 : 1.85,
        verdict: "BUY",
        skills_passed: 11,
        skills_total: 11,
        status: "APPROVED",
        setup: `15m ORB (${rMult}R Fractional)`,
        entry,
        stop,
        target,
        target_r: rMult,
        shares: tiger.shares,
        is_fractional: tiger.is_fractional,
        round_trip_fee: econ.round_trip_fee,
        expected_net_profit: econ.expected_net_profit,
        breakeven_win_rate_pct: econ.breakeven_win_rate_pct,
        win_rate: sym === "NVDA" ? 54.2 : sym === "TSLA" ? 52.0 : 51.5,
        risk_loss: econ.net_loss_at_stop,
      });
    }
    return out;
  }

  function loadStore() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) return JSON.parse(raw);
    } catch (e) {}
    return {
      cash: 200.0,
      starting_cash: 200.0,
      positions: [],
      trades: [],
      autoScan: true,
    };
  }

  function saveStore(st) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(st));
    } catch (e) {}
  }

  function nzNowStrings() {
    const now = new Date();
    const nzDate = new Intl.DateTimeFormat("en-CA", { timeZone: "Pacific/Auckland" }).format(now);
    const nzTime = new Intl.DateTimeFormat("en-NZ", {
      timeZone: "Pacific/Auckland",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: true,
    }).format(now);
    return { nzDate, nzTimeStr: `${nzDate} ${nzTime} NZDT` };
  }

  function buildTradesSummary(store) {
    const closed = store.trades.filter((t) => t.side === "SELL" || t.status === "CLOSED");
    const totalPnl = Math.round(closed.reduce((a, t) => a + Number(t.realized_pnl || 0), 0) * 100) / 100;
    const wins = closed.filter((t) => Number(t.realized_pnl || 0) > 0).length;
    const losses = closed.filter((t) => Number(t.realized_pnl || 0) < 0).length;
    const fees = Math.round(store.trades.reduce((a, t) => a + Number(t.tiger_fee || 0), 0) * 100) / 100;
    return {
      success: true,
      trades: store.trades,
      summary: {
        total_realized_pnl: totalPnl,
        total_pnl_pct: store.starting_cash > 0 ? Math.round((totalPnl / store.starting_cash) * 10000) / 100 : 0,
        win_rate: closed.length > 0 ? Math.round((wins / closed.length) * 1000) / 10 : 0,
        wins_count: wins,
        losses_count: losses,
        total_tiger_fees: fees,
        current_cash: store.cash,
      },
    };
  }

  function buildPipeline(symbol, usdAmount) {
    const sym = (symbol || "TSLA").toUpperCase();
    const usd = Math.min(200, Math.max(1, Number(usdAmount || 25)));
    const { px, orLow, orHigh, entry, stop, risk } = buildOrbGeometry(sym);
    const { rMult, target, tiger } = selectViableTarget(sym, entry, stop, risk, usd);
    const econ = tiger.economics;
    const store = loadStore();
    const held = store.positions.find((p) => p.ticker === sym);

    return {
      symbol: sym,
      curr_price: px,
      verdict: held ? "HOLD" : tiger.approved ? "BUY" : "HOLD",
      verdict_color: held ? "amber" : tiger.approved ? "jade" : "amber",
      verdict_action: held ? "MAINTAIN POSITION" : tiger.approved ? `ACTIONABLE BUY (${rMult}R FRACTIONAL)` : "STAND ASIDE (FEE GATE)",
      confidence: tiger.approved ? 82 : 55,
      is_approved: tiger.approved && !held,
      approved_reason: econ.reason,
      is_held: Boolean(held),
      shares_held: held ? held.shares : 0,
      entry: { status: "triggered", price: entry, or_high: orHigh, or_low: orLow, or_width: Math.round((orHigh - orLow) * 100) / 100 },
      plan: { symbol: sym, entry, stop, target, target_r: rMult, risk_per_share: risk, reward_risk: rMult, setup: "orb", flat_by: "15:55" },
      timemachine: { target_win_pct: rMult === 3 ? 26.4 : 36.8, stop_loss_pct: rMult === 3 ? 51.2 : 42.1, neither_pct: 21.1, avg_expectancy_r: 0.145, replays: 10000 },
      sizing: { usd_amount: Math.round(tiger.shares * entry * 100) / 100, shares: tiger.shares, cost: Math.round(tiger.shares * entry * 100) / 100, max_loss: Math.round(tiger.shares * risk * 100) / 100, available_cash: store.cash, is_fractional: tiger.is_fractional },
      tiger_economics: econ,
      risk_gate: { passed: tiger.approved, checks: [{ rule: "Tiger NZ Net Profit >= $0.05", passed: tiger.approved, detail: econ.reason }] },
      gemini_news: {
        sentiment: "Neutral",
        verdict: tiger.approved ? "BUY" : "HOLD",
        catalyst_status: "PASS",
        danger_flag: false,
        confidence: 78,
        premarket_change: 1.85,
        summary: `${sym} simulated with live Tiger Brokers NZ fractional fee & ${rMult}R net-profit verification.`,
        plain_english: {
          headline: `${sym} fractional setup (${tiger.shares.toFixed(4)} sh) verified against $${econ.round_trip_fee.toFixed(2)} Tiger NZ round-trip fee.`,
          what_happened: `Static GitHub Pages demo active. Break-even win rate after fees is ${econ.breakeven_win_rate_pct.toFixed(1)}%. Connect PocketServer (start.py) for live Yahoo/SEC/Gemini streams.`,
          risk_explained: `Max stop loss incl. $${econ.round_trip_fee.toFixed(2)} round-trip fees is $${econ.net_loss_at_stop.toFixed(2)} (under $1.50 limit).`,
          target_explained: `${rMult}R target $${target.toFixed(2)} yields +$${econ.gross_profit.toFixed(2)} gross / +$${econ.expected_net_profit.toFixed(2)} net after fees.`,
          action_plan: `Click Buy ($25) to test fractional execution, or compare $50 / $150 order sizes to see how Tiger NZ's $1.00 fee cap reduces fee drag.`,
        },
        model_used: "GitHub Pages Static Simulator",
      },
      tiger_broker_spec: {
        symbol: sym,
        limit_price: entry,
        stop_loss: stop,
        take_profit: target,
        shares: tiger.shares,
        clipboard_text: `TIGER BROKERS NZ ORDER SPEC\nSymbol: ${sym} (US)\nQty: ${tiger.shares.toFixed(4)} sh (Fractional)\nEntry: $${entry.toFixed(2)} | Stop: $${stop.toFixed(2)} | Target (${rMult}R): $${target.toFixed(2)}\nRound-Trip Fee: $${econ.round_trip_fee.toFixed(2)} | Est. Net Profit: +$${econ.expected_net_profit.toFixed(2)}`,
      },
      skills_analysis: [
        { id: "trader-scanner", name: "trader-scanner", title: "Market Liquidity & Volume", status: "PASS", badge: "PASS", badge_color: "jade", metric: `Price: $${px.toFixed(2)} (>= $5.00)`, verdict: "APPROVED", details: "Passes $5.00 liquidity floor." },
        { id: "trader-entry", name: "trader-entry", title: "Opening Range Breakout", status: "PASS", badge: "CONFIRMED", badge_color: "jade", metric: `OR: $${orLow.toFixed(2)} - $${orHigh.toFixed(2)}`, verdict: `TRIGGERED @ $${entry.toFixed(2)}`, details: "Simulated 5m closed-bar ORB breakout." },
        { id: "trader-exit", name: "trader-exit", title: `Midpoint Stop & ${rMult}R Target`, status: "PASS", badge: `${rMult}.00:1 R:R`, badge_color: "jade", metric: `Stop $${stop.toFixed(2)} | ${rMult}R $${target.toFixed(2)}`, verdict: `${rMult}.00:1 REWARD:RISK`, details: `Selected ${rMult}R target so gross reward (+$${econ.gross_profit.toFixed(2)}) clears Tiger NZ round-trip fee ($${econ.round_trip_fee.toFixed(2)}).` },
        { id: "trader-budget", name: "trader-budget", title: "Tiger NZ Fractional Sizing", status: tiger.approved ? "PASS" : "BLOCKED", badge: `${tiger.shares.toFixed(4)} SH`, badge_color: tiger.approved ? "jade" : "crimson", metric: `RT Fee: $${econ.round_trip_fee.toFixed(2)} | Net: +$${econ.expected_net_profit.toFixed(2)} | BE: ${econ.breakeven_win_rate_pct.toFixed(1)}%`, verdict: tiger.approved ? "NET PROFITABLE" : "REJECTED", details: econ.reason },
      ],
      approved_stocks: buildApprovedList(usd),
    };
  }

  function buildSnapshot(store) {
    const { nzTimeStr } = nzNowStrings();
    return {
      clock: { is_open: false, nz_time_str: nzTimeStr, next_open: "Opens 03:30 AM NZDT (GitHub Pages Demo)" },
      telemetry: {
        cash: store.cash,
        trades_today: store.trades.filter((t) => t.side === "BUY").length,
        max_trades: 4,
        risk_today: 0,
        max_daily_loss: 6.0,
        open_positions_count: store.positions.length,
        paper_mode: true,
        auto_scan_enabled: store.autoScan,
        universe_count: 5925,
      },
      portfolio: { cash: store.cash, positions: store.positions },
      prices: { prices: PRICES },
      watchlist: {
        hits: Object.keys(PRICES).slice(0, 8).map((s) => ({
          symbol: s,
          name: NAMES[s] || s,
          price: PRICES[s],
          setups: ["orb"],
          signal: "BUY",
          signal_label: "BUY (2R/3R FRAC)",
          signal_color: "jade",
          approved: true,
        })),
      },
      alerts: { rules: [] },
      trades_summary: buildTradesSummary(store),
    };
  }

  function buildChartCandles(symbol, tf) {
    const sym = (symbol || "TSLA").toUpperCase();
    const { px, orLow, orHigh, entry, stop, risk } = buildOrbGeometry(sym);
    const { target } = selectViableTarget(sym, entry, stop, risk, 25);
    const prev = Math.round(px * 0.982 * 100) / 100;
    const candles = [];
    let cur = prev;
    const count = 36;
    const nowSec = Math.floor(Date.now() / 1000);
    for (let i = 0; i < count; i++) {
      const wave = Math.sin(i * 0.65) * px * 0.003;
      const drift = (px - prev) / count;
      const o = Math.round(cur * 100) / 100;
      const c = i === count - 1 ? px : Math.round((o + drift + wave) * 100) / 100;
      const h = Math.round((Math.max(o, c) + px * 0.002) * 100) / 100;
      const l = Math.round((Math.min(o, c) - px * 0.002) * 100) / 100;
      candles.push({ time: nowSec - (count - i) * 300, label: `${i + 1}`, open: o, high: h, low: l, close: c, volume: 25000 + i * 750 });
      cur = c;
    }
    return {
      success: true,
      symbol: sym,
      timeframe: tf || "1D",
      current_price: px,
      prev_close: prev,
      change_usd: Math.round((px - prev) * 100) / 100,
      change_pct: Math.round(((px - prev) / prev) * 10000) / 100,
      is_positive: px >= prev,
      levels: { entry, stop, target, or_high: orHigh, or_low: orLow },
      candles,
    };
  }

  function jsonResponse(obj, status = 200) {
    return new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json" } });
  }

  const origFetch = window.fetch.bind(window);
  window.fetch = async function (input, init) {
    const urlStr = typeof input === "string" ? input : input.url;
    if (!urlStr || !urlStr.startsWith("/api/")) {
      return origFetch(input, init);
    }
    const url = new URL(urlStr, window.location.origin);
    const path = url.pathname;
    const store = loadStore();

    if (path === "/api/state" || path === "/api/config") {
      return jsonResponse(buildSnapshot(store));
    }
    if (path === "/api/pipeline") {
      return jsonResponse({ success: true, pipeline: buildPipeline(url.searchParams.get("symbol"), url.searchParams.get("usd")) });
    }
    if (path === "/api/pipeline/approved") {
      return jsonResponse({ success: true, approved_stocks: buildApprovedList(25) });
    }
    if (path === "/api/chart/data") {
      return jsonResponse(buildChartCandles(url.searchParams.get("symbol"), url.searchParams.get("tf")));
    }
    if (path === "/api/news") {
      const sym = (url.searchParams.get("symbols") || "TSLA").split(",")[0];
      return jsonResponse({
        success: true,
        data: {
          items: [
            { title: `${sym} intraday volume & ORB telemetry active (GitHub Pages Demo)`, ticker: sym, time: new Date().toISOString(), tags: ["tiger-nz", "fractional"], link: "#" },
          ],
          moves: [{ ticker: sym, price: PRICES[sym] || 100, pct: 1.85, moving: false }],
        },
      });
    }
    if (path === "/api/trades") {
      return jsonResponse(buildTradesSummary(store));
    }
    if (path === "/api/scan") {
      return jsonResponse({ success: true, watchlist: buildSnapshot(store).watchlist });
    }
    if (path === "/api/auto-scan") {
      const body = init && init.body ? JSON.parse(init.body) : {};
      store.autoScan = body.enabled !== undefined ? Boolean(body.enabled) : !store.autoScan;
      saveStore(store);
      return jsonResponse({ success: true, auto_scan_enabled: store.autoScan });
    }
    if (path === "/api/universe/search") {
      const q = (url.searchParams.get("q") || "").toUpperCase();
      const matches = Object.keys(PRICES)
        .filter((s) => !q || s.includes(q) || (NAMES[s] || "").toUpperCase().includes(q))
        .map((s) => ({ symbol: s, name: NAMES[s] || s }));
      return jsonResponse({ matches });
    }
    if (path === "/api/demo/buy") {
      const body = JSON.parse(init.body || "{}");
      const sym = (body.symbol || "TSLA").toUpperCase();
      const px = Number(body.price || PRICES[sym] || 100);
      const usd = Number(body.usd_amount || 25);
      const stop = Number(body.stop || Math.round(px * 0.98 * 100) / 100);
      const target = Number(body.target || Math.round((px + 2 * (px - stop)) * 100) / 100);
      const ev = evaluateTigerPlan(sym, px, stop, target, usd, 1.5, 0.05);
      if (!ev.approved) {
        return jsonResponse({ success: false, error: ev.economics.reason }, 400);
      }
      const sh = ev.shares;
      const fee = ev.economics.buy_fee;
      const totalCost = Math.round((sh * px + fee) * 100) / 100;
      if (store.cash < totalCost) {
        return jsonResponse({ success: false, error: `Insufficient cash ($${store.cash.toFixed(2)} < $${totalCost.toFixed(2)})` }, 400);
      }
      store.cash = Math.round((store.cash - totalCost) * 100) / 100;
      const pos = store.positions.find((p) => p.ticker === sym);
      const lot = { id: `${sym}-${Date.now()}`, shares: sh, cost: totalCost, entry_price: px, stop_price: stop, target_price: target, tiger_fee: fee };
      if (pos) {
        pos.shares = Math.round((pos.shares + sh) * 10000) / 10000;
        pos.lots.push(lot);
      } else {
        store.positions.push({ ticker: sym, shares: sh, lots: [lot] });
      }
      const { nzTimeStr } = nzNowStrings();
      store.trades.unshift({
        id: `TRD-${Date.now()}`,
        timestamp_nzdt: nzTimeStr,
        symbol: sym,
        side: "BUY",
        shares: sh,
        price: px,
        cost: totalCost,
        tiger_fee: fee,
        realized_pnl: 0,
        status: "OPEN",
        notes: `Fractional ORB Entry (${sh.toFixed(4)} sh, Tiger NZ Fee: $${fee.toFixed(2)})`,
      });
      saveStore(store);
      return jsonResponse({
        success: true,
        message: `Bought ${sh.toFixed(4)} ${sym} @ $${px.toFixed(2)} (Tiger NZ fee $${fee.toFixed(2)}, total $${totalCost.toFixed(2)})`,
        state: buildSnapshot(store),
      });
    }
    if (path === "/api/demo/sell") {
      const body = JSON.parse(init.body || "{}");
      const sym = (body.symbol || "").toUpperCase();
      const idx = store.positions.findIndex((p) => !sym || p.ticker === sym);
      if (idx === -1) return jsonResponse({ success: false, error: "No open position found." }, 400);
      const pos = store.positions[idx];
      const pct = Number(body.percent || 100);
      const sellSh = Math.min(pos.shares, Math.round(pos.shares * (pct / 100) * 10000) / 10000);
      const px = Number(body.price || PRICES[pos.ticker] || 100);
      const lotCost = pos.lots.reduce((a, l) => a + Number(l.cost || 0), 0);
      const basis = Math.round((lotCost / pos.shares) * sellSh * 100) / 100;
      const fee = calcTigerNZFee("SELL", sellSh, px, false).total_fee;
      const netProc = Math.round((sellSh * px - fee) * 100) / 100;
      const pnl = Math.round((netProc - basis) * 100) / 100;
      store.cash = Math.round((store.cash + netProc) * 100) / 100;
      pos.shares = Math.round((pos.shares - sellSh) * 10000) / 10000;
      if (pos.shares <= 0.0001) store.positions.splice(idx, 1);
      const { nzTimeStr } = nzNowStrings();
      store.trades.unshift({
        id: `TRD-${Date.now()}`,
        timestamp_nzdt: nzTimeStr,
        symbol: pos.ticker,
        side: "SELL",
        shares: sellSh,
        price: px,
        cost: basis,
        tiger_fee: fee,
        proceeds: netProc,
        realized_pnl: pnl,
        status: "CLOSED",
        exit_reason: pnl >= 0 ? "Target Profit Taken" : "Stop / Flatten Exit",
      });
      saveStore(store);
      return jsonResponse({
        success: true,
        message: `Sold ${sellSh.toFixed(4)} ${pos.ticker} @ $${px.toFixed(2)} (Net $${netProc.toFixed(2)}, Tiger NZ fee $${fee.toFixed(2)})`,
        state: buildSnapshot(store),
      });
    }
    if (path === "/api/demo/cash") {
      const body = JSON.parse(init.body || "{}");
      const amt = Number(body.amount || 200);
      if (body.action === "add") {
        store.cash = Math.round((store.cash + amt) * 100) / 100;
      } else {
        store.cash = Math.round(amt * 100) / 100;
        store.starting_cash = store.cash;
        store.positions = [];
        store.trades = [];
      }
      saveStore(store);
      return jsonResponse({ success: true, cash: store.cash, message: `Demo cash updated to $${store.cash.toFixed(2)} USD`, state: buildSnapshot(store) });
    }
    if (path === "/api/report/send") {
      const summary = buildTradesSummary(store);
      const { nzDate } = nzNowStrings();
      const pnl = summary.summary.total_realized_pnl;
      return jsonResponse({
        success: true,
        dispatched: true,
        recipient: "khanalnischal2075@gmail.com",
        message: `Daily market close statement compiled for khanalnischal2075@gmail.com! (In live trading, your local Python station automatically delivers this via Resend at 09:55 AM NZDT).`,
        data: {
          nz_date: nzDate,
          starting_cash: store.starting_cash,
          current_balance: store.cash,
          total_realized_pnl: pnl,
          today_realized_pnl: pnl,
          total_fees: summary.summary.total_tiger_fees,
          today_trades_count: store.trades.length,
        },
      });
    }
    return jsonResponse({ success: true });
  };

  window.WebSocket = function () {
    const sock = { readyState: 1, close: function () {}, send: function () {} };
    setTimeout(() => {
      if (typeof sock.onopen === "function") sock.onopen({});
      if (typeof sock.onmessage === "function") {
        sock.onmessage({ data: JSON.stringify({ type: "init_state", state: buildSnapshot(loadStore()) }) });
      }
    }, 50);
    return sock;
  };
})();
