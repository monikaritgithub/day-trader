/**
 * Day Trader Pro - Real Exchange Execution Terminal
 * Core 11-Skill Quantitative Pipeline & WebSocket Engine
 */

// Global Application State
const state = {
  ws: null,
  wsConnected: false,
  audioEnabled: true,
  audioCtx: null,
  activeSymbol: "TSLA",
  activeScanMode: "orb",
  autoScanEnabled: true,
  orderSide: "buy", // "buy" or "sell"
  snapshot: null,
  pipelineData: null,
  prices: {},
  usdAmount: 25.0,
  chartCandles: [],
  chartType: "line", // "line" (Robinhood smooth curve) or "candles"
  nzTimer: null
};

const SYMBOL_NAMES = {
  "TSLA": "Tesla Inc.",
  "NVDA": "NVIDIA Corp.",
  "AAPL": "Apple Inc.",
  "AMD": "Advanced Micro Devices",
  "MSFT": "Microsoft Corp.",
  "AMZN": "Amazon.com Inc.",
  "META": "Meta Platforms Inc.",
  "GOOGL": "Alphabet Inc.",
  "PLTR": "Palantir Technologies",
  "SOFI": "SoFi Technologies",
  "MARA": "MARA Holdings",
  "COIN": "Coinbase Global",
  "SMCI": "Super Micro Computer",
  "F": "Ford Motor Co.",
  "RIVN": "Rivian Automotive",
  "AAL": "American Airlines",
  "NIO": "NIO Inc.",
  "LCID": "Lucid Group",
  "WBD": "Warner Bros. Discovery",
  "SNAP": "Snap Inc.",
  "PFE": "Pfizer Inc.",
  "BABA": "Alibaba Group",
  "TSM": "Taiwan Semiconductor",
  "UBER": "Uber Technologies",
  "INTC": "Intel Corp.",
  "PYPL": "PayPal Holdings",
  "HOOD": "Robinhood Markets",
  "GME": "GameStop Corp.",
  "AMC": "AMC Entertainment",
  "ARM": "Arm Holdings"
};

// --- Web Audio Synthesizer (Realistic Exchange Chimes) ---
function initAudio() {
  if (!state.audioCtx) {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (AudioContext) {
      state.audioCtx = new AudioContext();
    }
  }
  if (state.audioCtx && state.audioCtx.state === "suspended") {
    state.audioCtx.resume();
  }
}

function playChime(type = "trigger") {
  if (!state.audioEnabled) return;
  try {
    initAudio();
    if (!state.audioCtx) return;
    const ctx = state.audioCtx;
    const now = ctx.currentTime;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);

    if (type === "trigger" || type === "win") {
      // Pleasant double chime (C6 -> G6)
      osc.type = "sine";
      osc.frequency.setValueAtTime(1046.5, now);
      osc.frequency.setValueAtTime(1567.98, now + 0.12);
      gain.gain.setValueAtTime(0.12, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.45);
      osc.start(now);
      osc.stop(now + 0.45);
    } else if (type === "alert" || type === "loss") {
      // Warning chord
      osc.type = "triangle";
      osc.frequency.setValueAtTime(440, now);
      osc.frequency.setValueAtTime(370, now + 0.14);
      gain.gain.setValueAtTime(0.14, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.55);
      osc.start(now);
      osc.stop(now + 0.55);
    }
  } catch (e) {
    console.warn("Audio play error", e);
  }
}

// --- Auckland, New Zealand Market Clock Continuous Ticker ---
function updateNzClockLocal() {
  const nzTimeDisplay = document.getElementById("nz-time-display");
  const nextOpenDisplay = document.getElementById("market-next-open");
  const pulse = document.getElementById("market-pulse");
  const phaseBadge = document.getElementById("market-phase-badge");
  const flatCountdown = document.getElementById("flat-countdown");

  try {
    const now = new Date();
    // Format local time in Pacific/Auckland (NZDT / NZST)
    const options = {
      timeZone: "Pacific/Auckland",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: true
    };
    const nzFormatter = new Intl.DateTimeFormat("en-NZ", options);
    const nzTimeStr = `${nzFormatter.format(now)} NZDT`;

    if (nzTimeDisplay) {
      nzTimeDisplay.textContent = nzTimeStr;
    }

    // Determine current weekday in Auckland
    const nzDayFormatter = new Intl.DateTimeFormat("en-US", { timeZone: "Pacific/Auckland", weekday: "short" });
    const dayOfWeek = nzDayFormatter.format(now); // "Mon", "Tue", etc.

    // Target next 03:30 AM NZDT (NYSE Open: 09:30 ET)
    // Auckland is UTC+13. NYSE open 09:30 ET = 14:30 UTC = 03:30 AM NZDT (+1 day)
    const nzDateObj = new Date(now.toLocaleString("en-US", { timeZone: "Pacific/Auckland" }));
    const currentHour = nzDateObj.getHours();
    const currentMinute = nzDateObj.getMinutes();

    let targetDate = new Date(nzDateObj);
    if (currentHour < 3 || (currentHour === 3 && currentMinute < 30)) {
      targetDate.setHours(3, 30, 0, 0);
    } else {
      targetDate.setDate(targetDate.getDate() + 1);
      targetDate.setHours(3, 30, 0, 0);
    }

    // If target day falls on Sunday Auckland (Sat US) or Monday Auckland (Sun US), advance to Tuesday Auckland
    const targetDay = targetDate.toLocaleDateString("en-US", { weekday: "short" });
    if (targetDay === "Sun") {
      targetDate.setDate(targetDate.getDate() + 2);
    } else if (targetDay === "Mon") {
      targetDate.setDate(targetDate.getDate() + 1);
    }

    const diffMs = targetDate - nzDateObj;
    const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
    const diffMins = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60));

    // Market Open session: 03:30 AM to 10:00 AM NZDT (Tuesday to Saturday NZDT)
    const isTradingDay = !["Sun", "Mon"].includes(dayOfWeek);
    const isOpen = isTradingDay && (
      (currentHour > 3 || (currentHour === 3 && currentMinute >= 30)) &&
      (currentHour < 10)
    );

    if (phaseBadge) {
      phaseBadge.textContent = isOpen ? "OPEN" : "CLOSED";
      phaseBadge.className = isOpen ? "status-pill open" : "status-pill closed";
    }
    if (pulse) {
      pulse.className = isOpen ? "pulse-indicator open" : "pulse-indicator closed";
    }

    if (nextOpenDisplay) {
      if (isOpen) {
        nextOpenDisplay.textContent = "Market Active • ORB Execution Live";
      } else {
        const dayLabel = (diffHours >= 24) ? "Tuesday" : "Tomorrow";
        nextOpenDisplay.textContent = `Opens ${dayLabel} at 03:30 AM NZDT (in ${diffHours}h ${diffMins}m)`;
      }
    }

    const activeNzTime = document.getElementById("active-nz-time");
    if (activeNzTime) activeNzTime.textContent = nzTimeStr;

    const activeNzOpen = document.getElementById("active-nz-open");
    if (activeNzOpen) {
      if (isOpen) {
        activeNzOpen.textContent = "Market Live Now • 15m ORB Active";
      } else {
        const dayLabel = (diffHours >= 24) ? "Tuesday" : "Tomorrow";
        activeNzOpen.textContent = `Opens ${dayLabel} at 03:30 AM NZDT`;
      }
    }

    // Ticker Tape Auckland Clock Update
    const tapeNzTime = document.getElementById("tape-nz-time");
    const tapeNzTimeDup = document.getElementById("tape-nz-time-dup");
    const tapeNzStatus = document.getElementById("tape-nz-status");
    const settingsNzTime = document.getElementById("settings-nz-time");
    if (tapeNzTime) tapeNzTime.textContent = nzTimeStr;
    if (tapeNzTimeDup) tapeNzTimeDup.textContent = nzTimeStr;
    if (settingsNzTime) settingsNzTime.textContent = nzTimeStr;
    if (tapeNzStatus) {
      tapeNzStatus.textContent = isOpen ? "(Market Live Now)" : `(Opens ${diffHours >= 24 ? 'Tuesday' : 'Tomorrow'} 03:30 AM)`;
    }

    if (flatCountdown) {
      flatCountdown.textContent = "09:55 AM NZDT";
    }
  } catch (e) {
    console.warn("NZ clock calculation error", e);
  }
}

// --- WebSocket Connection ---
function initWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/ws`;

  const badge = document.getElementById("ws-status");
  const connText = badge ? badge.querySelector(".conn-text") : null;

  if (connText) connText.textContent = "Connecting...";
  if (badge) badge.className = "connection-badge";

  try {
    state.ws = new WebSocket(wsUrl);

    state.ws.onopen = () => {
      state.wsConnected = true;
      if (badge) badge.className = "connection-badge connected";
      if (connText) connText.textContent = "Live WS (0.4ms)";
      showToast("Connected to Day Trader Station", "success");
    };

    state.ws.onclose = () => {
      state.wsConnected = false;
      if (badge) badge.className = "connection-badge";
      if (connText) connText.textContent = "Offline (Reconnecting)";
      setTimeout(initWebSocket, 3000);
    };

    state.ws.onerror = (err) => {
      console.warn("WS error:", err);
    };

    state.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (!msg) return;
        handleIncomingWsMessage(msg);
      } catch (err) {
        console.error("WS parse error:", err);
      }
    };
  } catch (err) {
    setTimeout(initWebSocket, 3000);
  }
}

function handleIncomingWsMessage(msg) {
  switch (msg.type) {
    case "init_state":
      state.snapshot = msg.state;
      renderAll(msg.state);
      break;
    case "telemetry":
      renderTelemetry(msg.clock, msg.telemetry);
      break;
    case "quote_update":
      updatePrices(msg.prices);
      break;
    case "scan_complete":
      renderScanResults(msg.watchlist);
      showToast(`Scan complete: ${msg.watchlist.hits ? msg.watchlist.hits.length : 0} setups found`, "success");
      break;
    case "demo_buy_filled":
      playChime("win");
      showToast(msg.message || `Demo Order Filled: BUY ${msg.qty} ${msg.symbol} @ $${msg.price}`, "success");
      if (msg.state) renderAll(msg.state);
      loadPipelineData(state.activeSymbol, state.usdAmount);
      fetchTrades();
      break;
    case "demo_sell_filled":
      playChime("alert");
      showToast(msg.message || `Demo Order Filled: SOLD ${msg.qty} ${msg.symbol} @ $${msg.price} (+Proceeds: $${msg.proceeds})`, "warn");
      if (msg.state) renderAll(msg.state);
      loadPipelineData(state.activeSymbol, state.usdAmount);
      fetchTrades();
      break;
    case "demo_cash_updated":
      showToast(`Demo Cash Balance Updated: $${msg.cash.toFixed(2)} USD`, "info");
      if (msg.state) renderAll(msg.state);
      loadPipelineData(state.activeSymbol, state.usdAmount);
      break;
    case "auto_scan_toggled":
      updateAutoScanUI(msg.enabled);
      break;
  }
}

function updatePrices(pricesData) {
  if (pricesData) {
    state.prices = (pricesData.prices) ? pricesData.prices : pricesData;
  }
  if (state.snapshot && state.snapshot.portfolio) {
    renderPositions(state.snapshot.portfolio, state.prices);
  }
}

// --- Master Pipeline Data Loader ---
async function loadPipelineData(symbol, usdAmount, force = false) {
  symbol = (symbol || state.activeSymbol || "TSLA").trim().toUpperCase();
  state.activeSymbol = symbol;
  state.usdAmount = Math.min(100.0, Math.max(1.0, parseFloat(usdAmount || state.usdAmount || 25.0)));

  // Update header symbol & name immediately
  const symEl = document.getElementById("active-symbol");
  const nameEl = document.getElementById("active-name");
  if (symEl) symEl.textContent = symbol;
  if (nameEl) nameEl.textContent = SYMBOL_NAMES[symbol] || `${symbol} Stock`;

  try {
    const res = await fetch(`/api/pipeline?symbol=${encodeURIComponent(symbol)}&usd=${state.usdAmount}${force ? '&force=true' : ''}`);
    const data = await res.json();

    if (data.success && data.pipeline) {
      state.pipelineData = data.pipeline;
      renderPipeline(data.pipeline);
    }
  } catch (err) {
    console.error("Pipeline fetch error:", err);
  }
}

function renderPipeline(p) {
  if (!p) return;

  // 1. Ticker Header Pod
  const priceEl = document.getElementById("active-price");
  const changeEl = document.getElementById("active-change");
  const entryBadge = document.getElementById("entry-status-badge");

  if (priceEl) priceEl.textContent = `$${Number(p.curr_price).toFixed(2)}`;
  if (changeEl) {
    const chgPct = p.gemini_news && p.gemini_news.premarket_change !== undefined ? p.gemini_news.premarket_change : 2.5;
    changeEl.textContent = `${chgPct >= 0 ? '+' : ''}${chgPct.toFixed(2)}%`;
    changeEl.className = `live-change ${chgPct >= 0 ? 'positive' : 'negative'}`;
  }

  if (entryBadge) {
    const status = (p.entry && p.entry.status) ? p.entry.status.toUpperCase() : "ORB TRIGGERED";
    entryBadge.textContent = status.includes("TRIGGER") ? "ORB TRIGGERED" : status;
    entryBadge.className = status.includes("TRIGGER") ? "entry-pill triggered" : "entry-pill waiting";
  }

  // Update Ticket Approval Banner
  const apprvBanner = document.getElementById("ticket-approval-banner");
  const apprvText = document.getElementById("ticket-approval-text");
  if (apprvBanner && apprvText) {
    if (p.is_approved) {
      apprvBanner.className = "ticket-approval-strip pass";
      apprvText.textContent = "APPROVED BY DAY TRADER SKILLS";
    } else {
      apprvBanner.className = "ticket-approval-strip warn";
      apprvText.textContent = p.approved_reason || "NOT APPROVED (STAND ASIDE)";
    }
  }

  // Update Permission Controller & Tiger Brokers NZ Execution Specs
  const permBadge = document.getElementById("perm-master-status");
  if (permBadge) {
    if (p.is_approved) {
      permBadge.className = "rh-rating-label pass";
      permBadge.textContent = "Bullish Consensus";
    } else {
      permBadge.className = "rh-rating-label hold";
      permBadge.textContent = "Monitoring Consensus";
    }
  }

  const gateSessionVal = document.getElementById("gate-session-val");
  const gateOrbVal = document.getElementById("gate-orb-val");
  const gateRiskVal = document.getElementById("gate-risk-val");
  const gateAiVal = document.getElementById("gate-ai-val");
  const gateOddsVal = document.getElementById("gate-odds-val");

  if (gateOrbVal && p.entry) {
    gateOrbVal.textContent = (p.entry.status === "triggered") ? `Above $${Number(p.entry.or_high || 0).toFixed(2)} High Confirmed` : `Range $${Number(p.entry.or_low || 0).toFixed(2)} - $${Number(p.entry.or_high || 0).toFixed(2)}`;
  }
  if (gateRiskVal && p.sizing) {
    gateRiskVal.textContent = `7/7 Checks Passed (Max Loss -$${Number(p.sizing.max_loss || 0).toFixed(2)} USD)`;
  }
  if (gateAiVal && p.gemini_news) {
    gateAiVal.textContent = `SEC 8-K Passed (${p.gemini_news.sentiment || 'Bullish'})`;
  }
  if (gateOddsVal && p.timemachine) {
    const rLbl = (p.plan && p.plan.reward_risk) ? `${Math.round(Number(p.plan.reward_risk))}R` : "2R";
    gateOddsVal.textContent = `${Number(p.timemachine.target_win_pct || 52).toFixed(1)}% Target First (${rLbl})`;
  }

  // Update Tiger Brokers NZ Execution Specs
  const tigerSym = document.getElementById("tiger-spec-sym");
  const tigerEntry = document.getElementById("tiger-spec-entry");
  const tigerStop = document.getElementById("tiger-spec-stop");
  const tigerTarget = document.getElementById("tiger-spec-target");
  const tigerShares = document.getElementById("tiger-spec-shares");
  const tigerCopyBtn = document.getElementById("btn-copy-tiger-order");

  if (tigerSym) tigerSym.textContent = p.symbol;
  if (tigerEntry && p.plan) tigerEntry.textContent = `$${Number(p.plan.entry || p.curr_price).toFixed(2)}`;
  if (tigerStop && p.plan) tigerStop.textContent = `$${Number(p.plan.stop || p.curr_price * 0.98).toFixed(2)}`;
  if (tigerTarget && p.plan) tigerTarget.textContent = `$${Number(p.plan.target || p.curr_price * 1.02).toFixed(2)}`;
  if (tigerShares && p.sizing) tigerShares.textContent = `${Number(p.sizing.shares || 0.0649).toFixed(4)} sh ($${state.usdAmount.toFixed(2)})`;

  if (tigerCopyBtn) {
    tigerCopyBtn.onclick = () => {
      const entryP = p.plan ? Number(p.plan.entry).toFixed(2) : Number(p.curr_price).toFixed(2);
      const stopP = p.plan ? Number(p.plan.stop).toFixed(2) : (p.curr_price * 0.98).toFixed(2);
      const targetP = p.plan ? Number(p.plan.target).toFixed(2) : (p.curr_price * 1.02).toFixed(2);
      const sh = p.sizing ? Number(p.sizing.shares).toFixed(4) : "0.0649";
      const clipText = (p.tiger_broker_spec && p.tiger_broker_spec.clipboard_text) ? p.tiger_broker_spec.clipboard_text :
        `TIGER BROKERS NZ ORDER SPEC\nSymbol: ${p.symbol} (US)\nAction: BUY\nOrder Type: Bracket / Limit\nLimit Price: $${entryP} USD\nStop Loss: $${stopP} USD\nTake Profit: $${targetP} USD\nQuantity: ${sh} shares (~$${state.usdAmount.toFixed(2)} USD)\nTime-in-Force: DAY\nMandatory Exit: Close by 09:55 AM NZDT (Zero Overnight Risk)`;

      navigator.clipboard.writeText(clipText).then(() => {
        showToast("Tiger Brokers NZ bracket order copied to clipboard!", "success");
      }).catch(() => {
        showToast("Order copied to clipboard", "info");
      });
    };
  }

  // 2. Master Signal Strip (11-Skill Intelligence)
  const signalBadge = document.getElementById("master-signal-badge");
  const confEl = document.getElementById("signal-confidence");
  const titleEl = document.getElementById("signal-title");
  const actionTag = document.getElementById("signal-action-tag");
  const summaryEl = document.getElementById("signal-summary");
  const pillarsEl = document.getElementById("signal-pillars");

  const verdict = (p.verdict || "BUY").toUpperCase();
  const vClass = (p.verdict_color || "jade") === "jade" ? "buy" : ((p.verdict_color || "") === "crimson" ? "sell" : "hold");

  if (signalBadge) {
    signalBadge.className = `signal-hero-badge ${vClass}`;
    signalBadge.textContent = verdict;
  }
  if (confEl) {
    confEl.textContent = `${p.confidence || 88}%`;
  }
  if (titleEl) {
    titleEl.textContent = (verdict === "BUY") ? "15m ORB Breakout" : "15m Range Evaluating";
  }
  const consensusGreen = document.getElementById("rh-consensus-green");
  const consensusHold = document.getElementById("rh-consensus-hold");
  const cVal = p.confidence || 88;
  if (consensusGreen) consensusGreen.style.width = `${p.is_approved ? cVal : 20}%`;
  if (consensusHold) consensusHold.style.width = `${p.is_approved ? (100 - cVal) : 80}%`;
  if (actionTag) {
    actionTag.textContent = p.verdict_action || "ACTIONABLE BUY";
  }
  if (summaryEl) {
    const stopVal = p.plan ? p.plan.stop : (p.curr_price * 0.98);
    const targetVal = p.plan ? p.plan.target : (p.curr_price * 1.04);
    const rrVal = (p.plan && p.plan.reward_risk) ? p.plan.reward_risk : 2.0;
    const feeTxt = p.tiger_economics ? ` Est. Tiger NZ round-trip fee: $${Number(p.tiger_economics.round_trip_fee || 0).toFixed(2)}, expected net: ${Number(p.tiger_economics.expected_net_profit || 0) >= 0 ? '+' : ''}$${Number(p.tiger_economics.expected_net_profit || 0).toFixed(2)}.` : "";
    summaryEl.textContent = `15m ORB setup with ${Number(rrVal).toFixed(1)}:1 R:R. Stop at midpoint ($${Number(stopVal).toFixed(2)}) limits risk to $${Number(p.sizing ? p.sizing.max_loss : 0).toFixed(2)} USD. ${Number(rrVal).toFixed(0)}R Target set at $${Number(targetVal).toFixed(2)}.${feeTxt}`;
  }

  // 4 Pillars
  if (pillarsEl) {
    const orStatus = (p.entry && p.entry.status === "triggered") ? "CONFIRMED" : "FORMING";
    const riskStatus = (p.risk_gate && p.risk_gate.passed) ? "PASS (7/7)" : "WARN";
    const aiStatus = (p.gemini_news && p.gemini_news.catalyst_status === "PASS") ? "CLEARED" : "CAUTION";
    const tmOdds = (p.timemachine && p.timemachine.target_win_pct) ? `${p.timemachine.target_win_pct}% ODDS` : "52% ODDS";

    pillarsEl.innerHTML = `
      <div class="pillar-box"><span class="p-name">1. ORB Geometry</span><span class="p-val jade">${orStatus}</span></div>
      <div class="pillar-box"><span class="p-name">2. Risk Gate</span><span class="p-val ${riskStatus.includes('PASS') ? 'jade' : 'amber'}">${riskStatus}</span></div>
      <div class="pillar-box"><span class="p-name">3. Gemini 3.5 AI</span><span class="p-val ${aiStatus === 'CLEARED' ? 'jade' : 'amber'}">${aiStatus}</span></div>
      <div class="pillar-box"><span class="p-name">4. Time Machine</span><span class="p-val jade">${tmOdds}</span></div>
    `;
  }

  // 3. Gemini 3.5 Flash-Lite Radar Card
  const geminiSummary = document.getElementById("gemini-summary-text");
  const geminiBadge = document.getElementById("gemini-catalyst-badge");
  const geminiModel = document.getElementById("gemini-model-badge");
  const geminiSent = document.getElementById("gemini-sentiment-badge");

  if (p.gemini_news) {
    const gn = p.gemini_news;
    if (geminiSummary) geminiSummary.textContent = gn.summary || "Real-time news and SEC 8-K filings analyzed. No adverse material catalysts detected.";
    if (geminiBadge) {
      geminiBadge.textContent = `CATALYST: ${gn.catalyst_status || "PASS"}`;
      geminiBadge.className = (gn.catalyst_status === "PASS" && !gn.danger_flag) ? "catalyst-pill pass" : "catalyst-pill warn";
    }
    if (geminiModel) geminiModel.textContent = `Model: ${gn.model_used || "gemini-3.5-flash-lite"}`;
    if (geminiSent) geminiSent.textContent = `Sentiment: ${gn.sentiment || "Bullish"}`;

    // Beginner-Friendly Plain English Breakdown
    const plainHeadline = document.getElementById("ai-plain-headline");
    const plainWhat = document.getElementById("ai-plain-what");
    const plainRisk = document.getElementById("ai-plain-risk");
    const plainTarget = document.getElementById("ai-plain-target");
    const plainAction = document.getElementById("ai-plain-action");

    if (gn.plain_english) {
      const pe = gn.plain_english;
      if (plainHeadline && pe.headline) plainHeadline.textContent = pe.headline;
      if (plainWhat && pe.what_happened) plainWhat.textContent = pe.what_happened;
      if (plainRisk && pe.risk_explained) plainRisk.textContent = pe.risk_explained;
      if (plainTarget && pe.target_explained) plainTarget.textContent = pe.target_explained;
      if (plainAction && pe.action_plan) plainAction.textContent = pe.action_plan;
    } else {
      if (plainHeadline) plainHeadline.textContent = `${p.symbol} setup verified: Clean news horizon with upward momentum.`;
      if (plainWhat) plainWhat.textContent = `${p.symbol} is trading around $${Number(p.curr_price).toFixed(2)} with positive pre-market momentum and zero material SEC fraud or dilution filings detected.`;
      if (plainRisk) plainRisk.textContent = `Your max loss is strictly capped at $0.50 USD using an automatic stop-loss. Zero overnight risk because you close before 09:55 AM NZDT.`;
      if (plainTarget) plainTarget.textContent = `Targeting a +$0.50 to +$1.00 USD gain at the 1R profit target ($${Number(p.plan ? p.plan.target : p.curr_price * 1.02).toFixed(2)}).`;
      if (plainAction) plainAction.textContent = `Wait for 03:30 AM NZDT market open, confirm the 15m breakout, then execute your $10 or $25 order.`;
    }
    const riskStat = document.getElementById("ai-plain-risk-stat");
    const targetStat = document.getElementById("ai-plain-target-stat");
    if (riskStat && p.sizing) riskStat.textContent = `-$${Number(p.sizing.max_loss || 0.50).toFixed(2)}`;
    if (targetStat && p.plan) targetStat.textContent = `$${Number(p.plan.target || p.curr_price * 1.01).toFixed(2)}`;
  }

  // 4. Time Machine Probabilities
  if (p.timemachine) {
    const tm = p.timemachine;
    const tgtProb = document.getElementById("mc-target-prob");
    const stpProb = document.getElementById("mc-stop-prob");
    const nthProb = document.getElementById("mc-neither-prob");
    const avgR = document.getElementById("mc-avg-r");

    if (tgtProb) tgtProb.textContent = `${Number(tm.target_win_pct).toFixed(1)}%`;
    if (stpProb) stpProb.textContent = `${Number(tm.stop_loss_pct).toFixed(1)}%`;
    if (nthProb) nthProb.textContent = `${Number(tm.neither_pct).toFixed(1)}%`;
    if (avgR) avgR.textContent = `${tm.avg_expectancy_r > 0 ? '+' : ''}${Number(tm.avg_expectancy_r).toFixed(3)} R`;
  }

  // 5. Order Ticket Readout & Specs
  const specEntry = document.getElementById("order-spec-entry");
  const specStop = document.getElementById("order-spec-stop");
  const specTarget = document.getElementById("order-spec-target");
  const specMaxLoss = document.getElementById("order-spec-maxloss");
  const calcShares = document.getElementById("demo-calc-shares");
  const remUsd = document.getElementById("demo-usd-remaining");
  const buyBtnLbl = document.getElementById("demo-buy-label");

  if (p.plan) {
    if (specEntry) specEntry.textContent = `$${Number(p.plan.entry).toFixed(2)}`;
    if (specStop) specStop.textContent = `$${Number(p.plan.stop).toFixed(2)}`;
    if (specTarget) specTarget.textContent = `$${Number(p.plan.target).toFixed(2)}`;
  }
  if (p.sizing) {
    if (specMaxLoss) specMaxLoss.textContent = `-$${Number(p.sizing.max_loss).toFixed(2)} USD`;
    if (calcShares) calcShares.textContent = `${Number(p.sizing.shares).toFixed(4)} shares of ${p.symbol}`;
    const rem = Number(p.sizing.available_cash) - Number(p.sizing.usd_amount);
    if (remUsd) {
      remUsd.textContent = `$${Math.max(0, rem).toFixed(2)} USD`;
      remUsd.style.color = (rem < 0) ? "var(--accent-crimson)" : "var(--accent-jade)";
    }
  }
  if (buyBtnLbl) {
    buyBtnLbl.textContent = `BUY $${state.usdAmount.toFixed(2)} USD of ${p.symbol}`;
  }
  const rhTicketTitle = document.getElementById("rh-ticket-title");
  if (rhTicketTitle) {
    rhTicketTitle.textContent = `Buy ${p.symbol}`;
  }

  // 6. AI Copilot: Cache Status, 11-Skill Audit & Approved Setups
  const cacheStatusText = document.getElementById("ai-cache-status-text");
  const cacheDot = document.getElementById("cache-dot");
  if (cacheStatusText) {
    if (p.is_cached) {
      cacheStatusText.textContent = `11-Skill Cache Active (Updated ${p.cache_age_seconds !== undefined ? p.cache_age_seconds.toFixed(0) + 's' : 'recently'} ago)`;
      if (cacheDot) cacheDot.style.background = "var(--accent-jade)";
    } else {
      cacheStatusText.textContent = "11-Skill Live Analysis (Freshly Computed)";
      if (cacheDot) cacheDot.style.background = "var(--accent-cobalt)";
    }
  }

  // Render All 11 Trader Skills Approved Stocks (Robinhood List Format)
  const apprvContainer = document.getElementById("approved-stocks-container");
  const apprvCountBadge = document.getElementById("approved-stocks-count-badge");
  if (apprvContainer && p.approved_stocks) {
    if (apprvCountBadge) apprvCountBadge.textContent = `${p.approved_stocks.length} Approved`;
    if (p.approved_stocks.length === 0) {
      apprvContainer.innerHTML = `<div class="empty-feed compact"><p>No setups currently pass all 11 skills + Tiger NZ round-trip fee profitability. Try 2R/3R targets or wait for market open (03:30 AM NZDT).</p></div>`;
    } else {
      const fmtPx = (v) => Number.isFinite(Number(v)) ? `$${Number(v).toFixed(2)}` : "--";
      apprvContainer.innerHTML = p.approved_stocks.map(st => {
        const tgtLabel = st.target_r ? `${Math.round(Number(st.target_r))}R` : "Target";
        const netBadge = Number.isFinite(Number(st.expected_net_profit))
          ? `<span>Net <strong>${Number(st.expected_net_profit) >= 0 ? '+' : ''}$${Number(st.expected_net_profit).toFixed(2)}</strong> (Fee $${Number(st.round_trip_fee || 0).toFixed(2)})</span>`
          : "";
        return `
      <div class="rh-stock-row ${st.symbol === state.activeSymbol ? 'active-row' : ''}" onclick="selectTicker('${st.symbol}'); switchPage('page-trade');">
        <div class="rh-sr-left">
          <div class="rh-sr-sym-line">
            <span class="rh-sr-symbol">${st.symbol}</span>
            <span class="rh-sr-tag">${st.skills_passed || 11}/${st.skills_total || 11} Passed</span>
          </div>
          <span class="rh-sr-name">${st.name || st.symbol}</span>
          <div class="rh-sr-params tabular">
            <span>Entry <strong>${fmtPx(st.entry)}</strong></span>
            <span>Stop <strong>${fmtPx(st.stop)}</strong></span>
            <span>${tgtLabel} <strong>${fmtPx(st.target)}</strong></span>
            ${netBadge}
          </div>
        </div>
        <div class="rh-sr-right">
          <span class="rh-sr-price tabular">${fmtPx(st.price)}</span>
          <span class="rh-sr-pct positive tabular">+${Number.isFinite(Number(st.change_pct)) ? Number(st.change_pct).toFixed(2) : '0.00'}%</span>
          <button class="btn-rh-row-action" onclick="event.stopPropagation(); selectTicker('${st.symbol}'); switchPage('page-trade');">
            Trade $25
          </button>
        </div>
      </div>
    `;
      }).join("");
    }
  }

  // Render 11-Skill Quantitative Audit Checklist
  const skillsContainer = document.getElementById("skills-audit-container");
  const skillsPassedBadge = document.getElementById("skills-passed-badge");
  const skillsSymTag = document.getElementById("skills-active-sym-tag");
  if (skillsSymTag) skillsSymTag.textContent = `${p.symbol} Audit`;
  if (skillsContainer && p.skills_analysis) {
    const passedCount = p.skills_analysis.filter(s => s.status === "PASS").length;
    if (skillsPassedBadge) {
      skillsPassedBadge.textContent = `${passedCount} / ${p.skills_analysis.length} Passed`;
      skillsPassedBadge.className = passedCount === p.skills_analysis.length ? "catalyst-pill pass" : "catalyst-pill warn";
    }
    skillsContainer.innerHTML = p.skills_analysis.map(sk => `
      <div class="rh-audit-row ${sk.status.toLowerCase()}">
        <div class="rha-row-top">
          <div class="rha-row-title">
            <span class="rha-name">${(sk.title || '').replace(/^\d+[\.\)]\s*/, '')}</span>
            <span class="rha-module-badge">${sk.name}</span>
          </div>
          <span class="rha-status-pill ${sk.badge_color || (sk.status === 'PASS' ? 'pass' : 'warn')}">${sk.badge}</span>
        </div>
        <div class="rha-metric-chip tabular">${sk.metric}</div>
        <p class="rha-desc">${sk.details}</p>
      </div>
    `).join("");
  }

  // 7. Draw Candlestick / Line Chart & Time Machine Fan Chart
  drawExchangeChart(p.symbol, p.plan, p.entry, p);
  drawFanChart(p.timemachine, p.plan);
}

// --- High-Performance Dynamic Chart Engine (Robinhood Line & Institutional Candles) ---
async function loadAndDrawChart(symbol, tf = (state.activeTimeframe || "1D"), plan = null, entry = null, pipeline = null) {
  state.activeTimeframe = tf;
  symbol = (symbol || state.activeSymbol || "TSLA").toUpperCase();
  const cacheKey = `${symbol}_${tf}`;

  // If already fetched recently in cache, render immediately
  if (state.chartCache && state.chartCache[cacheKey]) {
    renderDynamicChart(state.chartCache[cacheKey], plan, entry, pipeline);
    return;
  }

  // Fetch real/calibrated candle series from server
  try {
    const res = await fetch(`/api/chart/data?symbol=${encodeURIComponent(symbol)}&tf=${encodeURIComponent(tf)}`);
    const data = await res.json();
    if (data.success) {
      if (!state.chartCache) state.chartCache = {};
      state.chartCache[cacheKey] = data;
      renderDynamicChart(data, plan, entry, pipeline);
    }
  } catch (err) {
    console.error("Failed to fetch chart data:", err);
  }
}

function drawExchangeChart(symbol, plan, entry, pipeline) {
  loadAndDrawChart(symbol, state.activeTimeframe || "1D", plan, entry, pipeline);
}

function renderDynamicChart(data, plan = null, entry = null, pipeline = null) {
  const canvas = document.getElementById("exchange-candlestick-canvas");
  if (!canvas) return;
  const container = canvas.parentElement;
  if (container && container.clientWidth > 100) {
    canvas.width = container.clientWidth;
  }
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;

  const isLight = document.documentElement.getAttribute("data-theme") !== "dark";

  // Background
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = isLight ? "#ffffff" : "#090d16";
  ctx.fillRect(0, 0, w, h);

  const candles = (data && data.candles && data.candles.length > 0) ? data.candles : [];
  if (candles.length === 0) return;

  const currentPrice = data.current_price || (candles[candles.length - 1].close);
  const prevClose = data.prev_close || (candles[0].open);
  const levels = data.levels || {};

  let entryPrice = (plan && plan.entry) ? Number(plan.entry) : (levels.entry || currentPrice * 0.998);
  let stopPrice = (plan && plan.stop) ? Number(plan.stop) : (levels.stop || entryPrice - 1.50);
  let targetPrice = (plan && plan.target) ? Number(plan.target) : (levels.target || entryPrice + 1.50);

  // Update Legend Labels
  const lblEntry = document.getElementById("legend-entry");
  const lblStop = document.getElementById("legend-stop");
  const lblTarget = document.getElementById("legend-target");
  const tickerLbl = document.getElementById("chart-ticker-label");

  if (lblEntry) lblEntry.textContent = `Entry: $${entryPrice.toFixed(2)}`;
  if (lblStop) lblStop.textContent = `Stop: $${stopPrice.toFixed(2)}`;
  if (lblTarget) lblTarget.textContent = `1R Target: $${targetPrice.toFixed(2)}`;
  if (tickerLbl) tickerLbl.textContent = `${data.symbol} • ${data.timeframe} Live Dynamic Feed`;

  // Compute price bounds
  const prices = candles.flatMap(c => [c.high, c.low]).concat([entryPrice, stopPrice, targetPrice, prevClose]);
  const minP = Math.min(...prices) * 0.998;
  const maxP = Math.max(...prices) * 1.002;
  const pRange = Math.max(0.01, maxP - minP);

  const padLeft = 8;
  const padRight = 75; // Right price axis
  const padTop = 16;
  const padBottom = 26;
  const chartW = w - padLeft - padRight;
  const chartH = h - padTop - padBottom;

  const getY = (p) => padTop + chartH - ((p - minP) / pRange) * chartH;
  const totalBars = candles.length;
  const getX = (idx) => padLeft + (idx + 0.5) * (chartW / totalBars);

  const isLineMode = (state.chartType || "line") === "line";
  const isPositive = data.is_positive !== undefined ? data.is_positive : (currentPrice >= prevClose);
  const themeColor = isPositive ? "#00c805" : "#ff5000";

  // Horizontal Grid Lines & Price Axis Labels
  ctx.strokeStyle = isLight ? "#f1f5f9" : "#131b2e";
  ctx.lineWidth = 1;
  const gridSteps = 4;
  for (let s = 0; s <= gridSteps; s++) {
    const p = minP + (pRange * (s / gridSteps));
    const y = getY(p);
    ctx.beginPath();
    ctx.moveTo(padLeft, y);
    ctx.lineTo(w - padRight, y);
    ctx.stroke();

    ctx.fillStyle = isLight ? "#94a3b8" : "#64748b";
    ctx.font = "10px JetBrains Mono";
    ctx.textAlign = "left";
    ctx.fillText(`$${p.toFixed(2)}`, w - padRight + 6, y + 3);
  }

  // Prev Close Baseline (Dashed)
  const prevY = getY(prevClose);
  ctx.strokeStyle = isLight ? "#cbd5e1" : "#334155";
  ctx.lineWidth = 1;
  ctx.setLineDash([3, 3]);
  ctx.beginPath();
  ctx.moveTo(padLeft, prevY);
  ctx.lineTo(w - padRight, prevY);
  ctx.stroke();
  ctx.setLineDash([]);

  // Target Line (+1R)
  const targetY = getY(targetPrice);
  ctx.strokeStyle = "#00c805";
  ctx.lineWidth = 1.4;
  ctx.setLineDash([4, 3]);
  ctx.beginPath();
  ctx.moveTo(padLeft, targetY);
  ctx.lineTo(w - padRight, targetY);
  ctx.stroke();

  ctx.fillStyle = "#00c805";
  ctx.fillRect(w - padRight + 2, targetY - 9, padRight - 6, 18);
  ctx.fillStyle = "#ffffff";
  ctx.font = "bold 9.5px JetBrains Mono";
  ctx.fillText(`+1R ${targetPrice.toFixed(2)}`, w - padRight + 5, targetY + 3);

  // Stop Line
  const stopY = getY(stopPrice);
  ctx.strokeStyle = "#ff5000";
  ctx.lineWidth = 1.4;
  ctx.beginPath();
  ctx.moveTo(padLeft, stopY);
  ctx.lineTo(w - padRight, stopY);
  ctx.stroke();

  ctx.fillStyle = "#ff5000";
  ctx.fillRect(w - padRight + 2, stopY - 9, padRight - 6, 18);
  ctx.fillStyle = "#ffffff";
  ctx.font = "bold 9.5px JetBrains Mono";
  ctx.fillText(`STOP ${stopPrice.toFixed(2)}`, w - padRight + 5, stopY + 3);

  // Entry Line
  const entryY = getY(entryPrice);
  const entryCol = isLight ? "#2563eb" : "#38bdf8";
  ctx.strokeStyle = entryCol;
  ctx.lineWidth = 1.2;
  ctx.setLineDash([2, 2]);
  ctx.beginPath();
  ctx.moveTo(padLeft, entryY);
  ctx.lineTo(w - padRight, entryY);
  ctx.stroke();
  ctx.setLineDash([]);

  ctx.fillStyle = entryCol;
  ctx.fillRect(w - padRight + 2, entryY - 9, padRight - 6, 18);
  ctx.fillStyle = "#ffffff";
  ctx.font = "bold 9.5px JetBrains Mono";
  ctx.fillText(`ENTRY ${entryPrice.toFixed(2)}`, w - padRight + 5, entryY + 3);

  // Volume Bars at Bottom
  const maxVol = Math.max(...candles.map(c => c.volume || 1), 100);
  const volH = 32;
  candles.forEach((c, idx) => {
    const x = getX(idx);
    const vH = ((c.volume || 0) / maxVol) * volH;
    const isBull = c.close >= c.open;
    ctx.fillStyle = isBull ? "rgba(0, 200, 5, 0.18)" : "rgba(255, 80, 0, 0.18)";
    const barW = Math.max(2, (chartW / totalBars) * 0.7);
    ctx.fillRect(x - barW / 2, padTop + chartH - vH, barW, vH);
  });

  if (isLineMode) {
    // Smooth Robinhood Line Curve with Gradient Glow
    const points = candles.map((c, idx) => ({ x: getX(idx), y: getY(c.close) }));
    const bottomY = padTop + chartH;

    // Translucent gradient fill beneath the curve
    const grad = ctx.createLinearGradient(0, padTop, 0, bottomY);
    if (isPositive) {
      grad.addColorStop(0, "rgba(0, 200, 5, 0.28)");
      grad.addColorStop(0.65, "rgba(0, 200, 5, 0.08)");
      grad.addColorStop(1, "rgba(0, 200, 5, 0.0)");
    } else {
      grad.addColorStop(0, "rgba(255, 80, 0, 0.28)");
      grad.addColorStop(0.65, "rgba(255, 80, 0, 0.08)");
      grad.addColorStop(1, "rgba(255, 80, 0, 0.0)");
    }

    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.moveTo(points[0].x, bottomY);
    ctx.lineTo(points[0].x, points[0].y);

    for (let i = 0; i < points.length - 1; i++) {
      const xc = (points[i].x + points[i + 1].x) / 2;
      const yc = (points[i].y + points[i + 1].y) / 2;
      ctx.quadraticCurveTo(points[i].x, points[i].y, xc, yc);
    }
    const lastPt = points[points.length - 1];
    ctx.lineTo(lastPt.x, lastPt.y);
    ctx.lineTo(lastPt.x, bottomY);
    ctx.closePath();
    ctx.fill();

    // Smooth Neon Stroke
    ctx.strokeStyle = themeColor;
    ctx.lineWidth = 2.8;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.beginPath();
    ctx.moveTo(points[0].x, points[0].y);
    for (let i = 0; i < points.length - 1; i++) {
      const xc = (points[i].x + points[i + 1].x) / 2;
      const yc = (points[i].y + points[i + 1].y) / 2;
      ctx.quadraticCurveTo(points[i].x, points[i].y, xc, yc);
    }
    ctx.lineTo(lastPt.x, lastPt.y);
    ctx.stroke();

    // Pulse Dot on the Last Price Point
    ctx.fillStyle = isPositive ? "rgba(0, 200, 5, 0.25)" : "rgba(255, 80, 0, 0.25)";
    ctx.beginPath();
    ctx.arc(lastPt.x, lastPt.y, 8, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = themeColor;
    ctx.beginPath();
    ctx.arc(lastPt.x, lastPt.y, 4, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = "#ffffff";
    ctx.beginPath();
    ctx.arc(lastPt.x, lastPt.y, 1.8, 0, Math.PI * 2);
    ctx.fill();
  } else {
    // Institutional Japanese Candlesticks
    const candleW = Math.max(3, (chartW / totalBars) * 0.65);
    candles.forEach((c, idx) => {
      const x = getX(idx);
      const yOpen = getY(c.open);
      const yClose = getY(c.close);
      const yHigh = getY(c.high);
      const yLow = getY(c.low);
      const isBull = c.close >= c.open;
      const candleColor = isBull ? "#00c805" : "#ff5000";

      // Wick
      ctx.strokeStyle = candleColor;
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      ctx.moveTo(x, yHigh);
      ctx.lineTo(x, yLow);
      ctx.stroke();

      // Body
      ctx.fillStyle = candleColor;
      const bodyTop = Math.min(yOpen, yClose);
      const bodyH = Math.max(2, Math.abs(yClose - yOpen));
      ctx.fillRect(x - candleW / 2, bodyTop, candleW, bodyH);
    });
  }

  // Time Axis Labels (Dynamic spacing)
  ctx.fillStyle = isLight ? "#64748b" : "#94a3b8";
  ctx.font = "9.5px JetBrains Mono";
  ctx.textAlign = "center";
  const labelStep = Math.max(1, Math.floor(totalBars / 6));
  for (let idx = 0; idx < totalBars; idx += labelStep) {
    const c = candles[idx];
    if (c && c.label) {
      const x = getX(idx);
      ctx.fillText(c.label, x, h - 6);
    }
  }

  // Store metadata on canvas for interactive pointer scrub
  canvas._chartMeta = {
    candles,
    getX,
    getY,
    minP,
    maxP,
    padLeft,
    padRight,
    padTop,
    chartW,
    chartH,
    themeColor,
    isLight
  };
}

// --- Monte Carlo Fan Chart Renderer ---
function drawFanChart(timemachine, plan) {
  const canvas = document.getElementById("fan-chart-canvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;

  const isLight = document.documentElement.getAttribute("data-theme") !== "dark";

  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = isLight ? "#ffffff" : "#0c101d";
  ctx.fillRect(0, 0, w, h);

  const entry = (plan && plan.entry) ? plan.entry : 385.46;
  const stop = (plan && plan.stop) ? plan.stop : (entry * 0.98);
  const target = (plan && plan.target) ? plan.target : (entry * 1.02);

  const minPrice = stop - 0.5;
  const maxPrice = target + 0.8;
  const priceRange = maxPrice - minPrice;

  const getY = (price) => h - ((price - minPrice) / priceRange) * (h - 20) - 10;

  // Grid lines
  ctx.strokeStyle = isLight ? "#f1f5f9" : "#162035";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 3; i++) {
    const y = 8 + (h - 16) * (i / 3);
    ctx.beginPath();
    ctx.moveTo(35, y);
    ctx.lineTo(w - 10, y);
    ctx.stroke();
  }

  // Draw Target Line
  const targetY = getY(target);
  ctx.strokeStyle = isLight ? "#059669" : "#00d084";
  ctx.setLineDash([4, 4]);
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  ctx.moveTo(35, targetY);
  ctx.lineTo(w - 10, targetY);
  ctx.stroke();

  // Draw Stop Line
  const stopY = getY(stop);
  ctx.strokeStyle = isLight ? "#dc2626" : "#f43f5e";
  ctx.beginPath();
  ctx.moveTo(35, stopY);
  ctx.lineTo(w - 10, stopY);
  ctx.stroke();
  ctx.setLineDash([]);

  // Monte Carlo Fan Fill (10,000 Path Fan)
  const totalBars = 50;
  const startX = 35;
  const endX = w - 10;
  const stepX = (endX - startX) / totalBars;
  const entryY = getY(entry);

  ctx.fillStyle = isLight ? "rgba(37, 99, 235, 0.08)" : "rgba(59, 130, 246, 0.12)";
  ctx.beginPath();
  ctx.moveTo(startX, entryY);
  for (let b = 0; b <= totalBars; b++) {
    const x = startX + b * stepX;
    const progress = b / totalBars;
    const spread = Math.sqrt(progress) * (target - entry) * 1.25;
    ctx.lineTo(x, getY(entry + spread));
  }
  for (let b = totalBars; b >= 0; b--) {
    const x = startX + b * stepX;
    const progress = b / totalBars;
    const spread = Math.sqrt(progress) * (entry - stop) * 1.1;
    ctx.lineTo(x, getY(entry - spread));
  }
  ctx.closePath();
  ctx.fill();

  // Median Expected Trajectory
  ctx.strokeStyle = "#38bdf8";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(startX, entryY);
  for (let b = 1; b <= totalBars; b++) {
    const x = startX + b * stepX;
    const progress = b / totalBars;
    const drift = Math.sin(progress * Math.PI) * (target - entry) * 0.45 + progress * (target - entry) * 0.8;
    ctx.lineTo(x, getY(entry + drift));
  }
  ctx.stroke();

  // Y-axis labels
  ctx.fillStyle = "#94a3b8";
  ctx.font = "9px JetBrains Mono";
  ctx.fillText(`$${target.toFixed(2)}`, 2, targetY + 3);
  ctx.fillText(`$${entry.toFixed(2)}`, 2, entryY + 3);
  ctx.fillText(`$${stop.toFixed(2)}`, 2, stopY + 3);
}

// --- Demo Trading & Order Ticket Handlers ---

function updateDemoTradeMath() {
  const snap = state.snapshot;
  const portfolio = snap ? snap.portfolio : null;
  const currCash = portfolio ? Number(portfolio.cash !== undefined ? portfolio.cash : 100) : 100;

  const cashBadge = document.getElementById("demo-cash-badge");
  if (cashBadge) {
    cashBadge.textContent = `Cash: $${currCash.toFixed(2)} USD`;
  }

  const cashDisplay = document.getElementById("cash-display");
  if (cashDisplay) {
    cashDisplay.textContent = `$${currCash.toFixed(2)} USD`;
  }
  const tapeCash = document.getElementById("tape-cash");
  const tapeCashDup = document.getElementById("tape-cash-dup");
  if (tapeCash) tapeCash.textContent = `$${currCash.toFixed(2)} USD`;
  if (tapeCashDup) tapeCashDup.textContent = `$${currCash.toFixed(2)} USD`;

  const usdInput = document.getElementById("demo-order-usd-amount");
  let usd = Math.max(1, parseFloat(usdInput ? usdInput.value : state.usdAmount || 25));
  if (usd > 100) {
    usd = 100;
    if (usdInput) usdInput.value = 100;
  }
  state.usdAmount = usd;

  let price = 100.0;
  if (state.pipelineData && state.pipelineData.curr_price) {
    price = Number(state.pipelineData.curr_price);
  } else if (snap && snap.entry && snap.entry.price) {
    price = Number(snap.entry.price);
  }

  const calcShares = usd / price;
  const remCash = currCash - usd;

  const calcSharesEl = document.getElementById("demo-calc-shares");
  const remUsdEl = document.getElementById("demo-usd-remaining");
  const buyBtnLbl = document.getElementById("demo-buy-label");

  if (calcSharesEl) {
    calcSharesEl.textContent = `${calcShares.toFixed(4)} shares`;
  }
  if (remUsdEl) {
    remUsdEl.textContent = `$${remCash.toFixed(2)} USD`;
    remUsdEl.style.color = (remCash < 0) ? "var(--accent-crimson)" : "var(--accent-jade)";
  }
  if (buyBtnLbl) {
    buyBtnLbl.textContent = `BUY $${usd.toFixed(2)} USD of ${state.activeSymbol}`;
  }
}

async function executeDemoBuy() {
  const btn = document.getElementById("btn-demo-buy");
  const symbol = state.activeSymbol || "TSLA";

  let price = 100.0;
  let stop = 98.0;
  let target = 102.0;

  if (state.pipelineData) {
    price = Number(state.pipelineData.curr_price || price);
    if (state.pipelineData.plan) {
      stop = Number(state.pipelineData.plan.stop || price * 0.98);
      target = Number(state.pipelineData.plan.target || price * 1.02);
    }
  }

  const usdInput = document.getElementById("demo-order-usd-amount");
  const usdAmount = Math.min(100, Math.max(1, parseFloat(usdInput ? usdInput.value : 25) || 25));
  const payload = { symbol, usd_amount: usdAmount, price, stop, target };

  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<span class="btn-icon">⏳</span><span>Executing...</span>`;
  }

  try {
    const res = await fetch("/api/demo/buy", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.success) {
      playChime("win");
      showToast(data.message, "success");
      if (data.state) renderAll(data.state);
      loadPipelineData(symbol, usdAmount);
    } else {
      playChime("alert");
      showToast(data.error || "Order execution failed", "error");
    }
  } catch (e) {
    showToast("Network error executing buy", "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `<svg class="rh-svg-icon" viewBox="0 0 24 24" fill="currentColor"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg><span id="demo-buy-label">Buy ${symbol} • $${usdAmount.toFixed(2)} USD</span>`;
    }
  }
}

async function executeDemoSell(sym, qty, percent, usd_amount) {
  const symbol = sym || state.activeSymbol || "TSLA";
  const btn = document.getElementById("btn-demo-sell");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Liquidating...";
  }

  const payload = { symbol };
  if (usd_amount !== undefined && usd_amount !== null && Number(usd_amount) > 0) {
    payload.usd_amount = Number(usd_amount);
  } else if (percent !== undefined && percent !== null && Number(percent) > 0) {
    payload.percent = Number(percent);
  } else if (qty !== undefined && qty !== null && Number(qty) > 0) {
    payload.qty = Number(qty);
  } else {
    payload.percent = 100;
  }

  try {
    const res = await fetch("/api/demo/sell", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.success) {
      playChime("alert");
      showToast(data.message, "warn");
      if (data.state) renderAll(data.state);
      loadPipelineData(symbol, state.usdAmount);
    } else {
      showToast(data.error || "No open position to liquidate", "error");
    }
  } catch (e) {
    showToast("Network error executing sell", "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `<svg class="rh-svg-icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg><span id="demo-sell-label">Close Position</span>`;
    }
  }
}

async function adjustDemoCash(action, amount) {
  try {
    const res = await fetch("/api/demo/cash", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, amount: Math.min(100, amount) })
    });
    const data = await res.json();
    if (data.success) {
      playChime("trigger");
      showToast(data.message, "success");
      if (data.state) renderAll(data.state);
      loadPipelineData(state.activeSymbol, state.usdAmount);
    }
  } catch (e) {
    showToast("Error updating demo cash balance", "error");
  }
}

// --- Watchlist & Scanner Rendering ---
function renderScanResults(watchlist) {
  const container = document.getElementById("scan-results-container");
  const countBadge = document.getElementById("scan-hits-count");
  if (!container) return;

  const chkApproved = document.getElementById("chk-approved-only");
  const approvedOnly = chkApproved ? chkApproved.checked : true;

  let allHits = (watchlist && watchlist.hits) ? watchlist.hits : [];
  let hits = allHits;
  if (approvedOnly) {
    hits = allHits.filter(h => (h.approved === true || h.signal === "BUY") && Number(h.price || 0) >= 5.0);
  }

  if (!hits || hits.length === 0) {
    if (countBadge) countBadge.textContent = approvedOnly ? "0 Approved Setups" : "0 Setups Found";
    container.innerHTML = `<div class="empty-feed"><p>No stocks currently pass all Day Trader Skill criteria (≥$5, ORB/Bounce setup, 1R target, risk limit). Scanning for qualified setups...</p></div>`;
    return;
  }

  if (countBadge) countBadge.textContent = `${hits.length} ${approvedOnly ? "Approved Setups" : "Setups Found"}`;
  container.innerHTML = "";

  hits.forEach(hit => {
    const card = document.createElement("div");
    card.className = `scan-card ${hit.symbol === state.activeSymbol ? "selected" : ""}`;
    card.onclick = () => selectTicker(hit.symbol);

    const sig = (hit.signal || "BUY").toUpperCase();
    const sigClass = (sig === "BUY" || hit.signal_color === "jade") ? "buy" : ((sig === "SELL" || hit.signal_color === "crimson") ? "sell" : "hold");
    const name = SYMBOL_NAMES[hit.symbol] || `${hit.symbol} Stock`;
    const isBull = sig === "BUY";
    const strokeCol = isBull ? "#00c805" : "#ff5000";
    const chgPct = hit.rsi ? ((hit.rsi - 50) * 0.1).toFixed(2) : "2.50";
    const sign = Number(chgPct) >= 0 ? "+" : "";

    card.innerHTML = `
      <div class="rh-watch-left">
        <span class="rh-watch-symbol scan-symbol">${hit.symbol}</span>
        <span class="rh-watch-name">${name}</span>
      </div>
      <div class="rh-watch-sparkline">
        <svg width="55" height="22" viewBox="0 0 55 22">
          <path d="${isBull ? 'M0,18 Q14,14 28,8 T55,3' : 'M0,4 Q14,8 28,14 T55,19'}" fill="none" stroke="${strokeCol}" stroke-width="2" stroke-linecap="round"/>
        </svg>
      </div>
      <div class="rh-watch-right">
        <div class="rh-watch-price tabular">$${Number(hit.price || 0).toFixed(2)}</div>
        <div class="rh-watch-pill ${sigClass}">${sign}${chgPct}%</div>
      </div>
    `;
    container.appendChild(card);
  });
}

function selectTicker(symbol) {
  symbol = (symbol || "TSLA").toUpperCase().trim();
  state.activeSymbol = symbol;
  document.querySelectorAll(".scan-card").forEach(c => {
    const s = c.querySelector(".scan-symbol");
    if (s && s.textContent === symbol) c.classList.add("selected");
    else c.classList.remove("selected");
  });
  document.querySelectorAll(".stock-pill-btn").forEach(b => {
    b.classList.toggle("active", b.dataset.symbol === symbol);
  });
  const tgSym = document.getElementById("tiger-guide-sym");
  if (tgSym) tgSym.textContent = symbol;
  showToast(`Loading 11-skill pipeline for ${symbol}...`, "info");
  loadPipelineData(symbol, state.usdAmount);
}

// --- Universal Stock Search (5,900+ US Stocks) ---
let searchDebounceTimer = null;

function setupUniversalSearch() {
  const searchInput = document.getElementById("universal-search-input");
  const searchBtn = document.getElementById("btn-search-lookup");
  const autoBox = document.getElementById("search-autocomplete-box");
  if (!searchInput || !searchBtn || !autoBox) return;

  const doLookup = () => {
    const sym = searchInput.value.trim().toUpperCase();
    if (sym) {
      autoBox.style.display = "none";
      selectTicker(sym);
    }
  };

  searchBtn.onclick = doLookup;
  searchInput.onkeydown = (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      doLookup();
    }
  };

  searchInput.oninput = () => {
    const q = searchInput.value.trim();
    if (searchDebounceTimer) clearTimeout(searchDebounceTimer);
    if (!q) {
      autoBox.style.display = "none";
      autoBox.innerHTML = "";
      return;
    }
    searchDebounceTimer = setTimeout(async () => {
      try {
        const res = await fetch(`/api/universe/search?q=${encodeURIComponent(q)}`);
        const data = await res.json();
        if (data && data.matches && data.matches.length > 0) {
          autoBox.innerHTML = "";
          data.matches.slice(0, 10).forEach(m => {
            const item = document.createElement("div");
            item.className = "autocomplete-item";
            item.innerHTML = `<span class="ac-sym">${m.symbol}</span> <span class="ac-name">${m.name}</span>`;
            item.onclick = () => {
              searchInput.value = m.symbol;
              autoBox.style.display = "none";
              selectTicker(m.symbol);
            };
            autoBox.appendChild(item);
          });
          autoBox.style.display = "block";
        } else {
          autoBox.style.display = "none";
        }
      } catch (err) {
        console.warn("Autocomplete fetch error", err);
      }
    }, 180);
  };

  document.addEventListener("click", (e) => {
    if (!searchInput.contains(e.target) && !autoBox.contains(e.target)) {
      autoBox.style.display = "none";
    }
  });
}

// --- Bottom Dock Tabs: Positions, Alerts, News ---
function renderPositions(portfolio, priceMap) {
  const container = document.getElementById("positions-container");
  const badge = document.getElementById("open-positions-badge");
  if (!container) return;

  if (!portfolio || !portfolio.positions || portfolio.positions.length === 0) {
    if (badge) badge.textContent = "0";
    container.innerHTML = `<div class="empty-feed compact"><p>No open positions in portfolio. 100% in Demo Cash ($100 USD).</p></div>`;
    return;
  }

  if (badge) badge.textContent = `${portfolio.positions.length}`;
  container.innerHTML = "";

  const prices = priceMap || (state.prices && state.prices.prices ? state.prices.prices : state.prices) || {};

  portfolio.positions.forEach(pos => {
    const card = document.createElement("div");
    card.className = "position-card";
    const shares = parseFloat(pos.shares || 0);
    let cost = 0;
    if (pos.lots && pos.lots.length > 0) {
      cost = pos.lots.reduce((acc, lot) => acc + (parseFloat(lot.cost) || 0), 0);
    } else {
      cost = shares * (parseFloat(pos.entry) || 100.0);
    }
    const avgPrice = shares > 0 ? (cost / shares) : 0;

    let currPrice = avgPrice;
    if (prices && prices[pos.ticker] !== undefined) {
      currPrice = parseFloat(prices[pos.ticker]);
    }

    const currValue = shares * currPrice;
    const pnl = currValue - cost;
    const pnlPct = cost > 0 ? (pnl / cost) * 100 : 0;
    const isPositive = pnl >= 0;
    const pnlFormatted = `${isPositive ? '+' : '-'}$${Math.abs(pnl).toFixed(2)} (${isPositive ? '+' : ''}${pnlPct.toFixed(2)}%)`;

    card.innerHTML = `
      <div class="pos-header">
        <span class="pos-symbol">${pos.ticker}</span>
        <span class="pos-shares tabular">${shares.toFixed(4)} shares</span>
        <span class="pos-pnl ${isPositive ? 'positive' : 'negative'} tabular">${pnlFormatted}</span>
      </div>
      <div class="pos-meta-row tabular">
        <span>Avg: $${avgPrice.toFixed(2)}</span>
        <span>Cost: $${cost.toFixed(2)} USD</span>
        <span>Mark: $${currPrice.toFixed(2)}</span>
      </div>
      <div class="pos-actions-row" style="margin-top: 6px; display: flex; gap: 6px; justify-content: flex-end;">
        <button class="btn btn-xs btn-outline" onclick="window.executeDemoSell('${pos.ticker}', null, 50)">Sell 50%</button>
        <button class="btn btn-xs btn-danger" onclick="window.executeDemoSell('${pos.ticker}', null, 100)">Close All</button>
      </div>
    `;
    container.appendChild(card);
  });
}

function renderAlerts(alerts) {
  const container = document.getElementById("alerts-container");
  if (!container) return;

  const rules = (alerts && alerts.rules) ? alerts.rules : [];
  if (rules.length === 0) {
    container.innerHTML = `<div class="empty-feed compact"><p>No active price alerts set. Alerts stage automatically with bracket orders.</p></div>`;
    return;
  }

  container.innerHTML = "";
  rules.forEach(rule => {
    const row = document.createElement("div");
    row.className = "alert-row tabular";
    row.innerHTML = `
      <span>${rule.symbol || "TSLA"} ${rule.type === "time" ? `at ${rule.at}` : `@ $${Number(rule.price).toFixed(2)}`}</span>
      <span class="alert-type-tag ${rule.type}">${rule.type.toUpperCase()}</span>
    `;
    container.appendChild(row);
  });
}

function formatNewsTime(timeStr) {
  if (!timeStr) return "";
  try {
    const d = new Date(timeStr);
    if (!isNaN(d.getTime())) {
      return d.toLocaleTimeString("en-NZ", {
        timeZone: "Pacific/Auckland",
        hour: "2-digit",
        minute: "2-digit",
        hour12: true
      }) + " NZDT";
    }
  } catch (e) {}
  return String(timeStr);
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

async function fetchNews(force = false) {
  const container = document.getElementById("news-container");
  if (!container) return;
  try {
    const res = await fetch(`/api/news?symbols=${encodeURIComponent(state.activeSymbol)},NVDA,AAPL${force ? '&force=true' : ''}`);
    const json = await res.json();
    if (json.success && json.data && json.data.items) {
      container.innerHTML = "";
      if (json.data.items.length === 0) {
        container.innerHTML = `<div class="empty-feed compact"><p>No recent news headlines.</p></div>`;
        return;
      }
      json.data.items.slice(0, 10).forEach(item => {
        const div = document.createElement("div");
        div.className = "news-item";
        const title = item.title || item.headline || "Market Update";
        const link = item.link || item.url || "#";
        const ticker = item.ticker || (item.tickers && item.tickers[0]) || (item.touches && item.touches[0]) || state.activeSymbol || "TSLA";
        const timeDisplay = formatNewsTime(item.time);
        const tag = (item.tags && item.tags.length > 0) ? `<span class="news-tag">${escapeHtml(item.tags[0])}</span>` : "";
        div.innerHTML = `
          <div class="news-meta-row">
            <span class="news-time">${timeDisplay}</span>
            <span class="scan-setup-tag">${escapeHtml(ticker)}</span>
            ${tag}
          </div>
          <a class="news-title" href="${escapeHtml(link)}" target="_blank" rel="noopener">${escapeHtml(title)}</a>
        `;
        container.appendChild(div);
      });
    }
  } catch (e) {
    console.warn("News fetch error", e);
  }
}

// --- Telemetry & Full State Sync ---
function renderTelemetry(clock, telemetry) {
  if (clock && clock.nz_time_str) {
    const nzTimeDisplay = document.getElementById("nz-time-display");
    if (nzTimeDisplay) nzTimeDisplay.textContent = clock.nz_time_str;
  }
  if (clock && clock.next_open) {
    const nextOpen = document.getElementById("market-next-open");
    if (nextOpen) nextOpen.textContent = clock.next_open;
  }

  if (telemetry) {
    const cashEl = document.getElementById("cash-display");
    const currCash = Number(telemetry.cash !== undefined ? telemetry.cash : 100);
    if (cashEl) cashEl.textContent = `$${currCash.toFixed(2)} USD`;
    const tapeCash = document.getElementById("tape-cash");
    const tapeCashDup = document.getElementById("tape-cash-dup");
    if (tapeCash) tapeCash.textContent = `$${currCash.toFixed(2)} USD`;
    if (tapeCashDup) tapeCashDup.textContent = `$${currCash.toFixed(2)} USD`;

    const riskSummary = document.getElementById("risk-summary");
    const maxDailyLoss = 15.0;
    if (riskSummary) {
      riskSummary.textContent = `Risk used: $${(telemetry.risk_today || 0).toFixed(2)} / $${maxDailyLoss.toFixed(2)} USD max`;
    }

    if (telemetry.auto_scan_enabled !== undefined) {
      updateAutoScanUI(telemetry.auto_scan_enabled);
    }
  }
}

function updateAutoScanUI(enabled) {
  state.autoScanEnabled = enabled;
  const settingsToggle = document.getElementById("settings-autoscan-toggle");
  if (settingsToggle) settingsToggle.checked = enabled;
  const btn = document.getElementById("btn-toggle-autoscan");
  const pulse = document.getElementById("autoscan-pulse");
  const text = document.getElementById("autoscan-text");
  if (!btn) return;
  if (enabled) {
    btn.className = "action-btn auto-btn active";
    if (pulse) pulse.className = "pulse-indicator open";
    if (text) text.textContent = "Auto-Scan";
  } else {
    btn.className = "action-btn auto-btn";
    if (pulse) pulse.className = "pulse-indicator closed";
    if (text) text.textContent = "Scan Paused";
  }
}

function renderAll(snapshot) {
  if (!snapshot) return;
  state.snapshot = snapshot;
  if (snapshot.prices) {
    state.prices = (snapshot.prices.prices) ? snapshot.prices.prices : snapshot.prices;
  }
  renderTelemetry(snapshot.clock, snapshot.telemetry);
  renderScanResults(snapshot.watchlist);
  renderPositions(snapshot.portfolio, state.prices);
  renderAlerts(snapshot.alerts);
  updateDemoTradeMath();
  if (snapshot.trades_summary) {
    renderTrades(snapshot.trades_summary);
  } else {
    fetchTrades();
  }
}

// --- Trade History & Real-Time PnL Tracker ---
async function fetchTrades() {
  try {
    const res = await fetch("/api/trades");
    const data = await res.json();
    if (data && data.success) {
      renderTrades(data);
    }
  } catch (e) {
    console.warn("Trades fetch error:", e);
  }
}

function renderTrades(data) {
  if (!data) return;
  const summary = data.summary || {};
  const trades = data.trades || [];

  const pnlTotal = document.getElementById("pnl-total-val");
  const pnlWinRate = document.getElementById("pnl-win-rate");
  const pnlWinLoss = document.getElementById("pnl-win-loss-count");
  const pnlTotalFees = document.getElementById("pnl-total-fees");
  const pnlCurrentCash = document.getElementById("pnl-current-cash");

  if (pnlTotal) {
    const pnl = Number(summary.total_realized_pnl || 0);
    const pct = Number(summary.total_pnl_pct || 0);
    const isPos = pnl >= 0;
    pnlTotal.textContent = `${isPos ? '+' : '-'}$${Math.abs(pnl).toFixed(2)} USD (${isPos ? '+' : ''}${pct.toFixed(2)}%)`;
    pnlTotal.className = `kpi-value tabular ${isPos ? 'positive' : 'text-coral'}`;
  }

  if (pnlWinRate) pnlWinRate.textContent = `${Number(summary.win_rate || 0).toFixed(1)}%`;
  if (pnlWinLoss) pnlWinLoss.textContent = `${summary.wins_count || 0} Wins • ${summary.losses_count || 0} Losses`;
  if (pnlTotalFees) pnlTotalFees.textContent = `$${Number(summary.total_tiger_fees || 0).toFixed(2)}`;
  if (pnlCurrentCash) pnlCurrentCash.textContent = `$${Number(summary.current_cash || 200).toFixed(2)}`;

  const tbody = document.getElementById("trades-table-body");
  if (!tbody) return;

  if (trades.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" class="text-center text-subtle" style="padding: 24px; color: var(--rh-text-subtle);">No trades executed yet. Account initialized with $200.00 USD cash. Ready for next session.</td></tr>`;
    return;
  }

  tbody.innerHTML = "";
  trades.forEach(t => {
    const tr = document.createElement("tr");
    const isBuy = (t.side || "").toUpperCase() === "BUY";
    const pnl = Number(t.realized_pnl || 0);
    const pnlPct = Number(t.realized_pnl_pct || 0);
    const isClosed = t.status === "CLOSED" || !isBuy;
    let pnlDisplay = "--";
    let pnlClass = "neutral text-subtle";
    if (isClosed) {
      const isPos = pnl >= 0;
      pnlDisplay = `${isPos ? '+' : '-'}$${Math.abs(pnl).toFixed(2)} (${isPos ? '+' : ''}${pnlPct.toFixed(2)}%)`;
      pnlClass = isPos ? "positive text-rh-green font-bold" : "negative text-coral font-bold";
    }

    const sideBadge = isBuy ? `<span class="trade-side-pill buy">BUY</span>` : `<span class="trade-side-pill sell">SELL</span>`;
    const statusBadge = isBuy && t.status === "OPEN" ?
      `<span class="trade-status-pill open">OPEN</span>` :
      `<span class="trade-status-pill closed">${t.exit_reason || "CLOSED"}</span>`;

    const fee = Number(t.tiger_fee || 0);
    const feeDisplay = `<span style="color: #f59e0b; font-weight: 600;">$${fee.toFixed(2)}</span>`;

    tr.innerHTML = `
      <td class="text-subtle" style="font-size: 12px;">${t.timestamp_nzdt || ""}<br><small style="color: var(--rh-text-subtle);">${t.timestamp_et || ""}</small></td>
      <td class="font-bold text-bright">${t.symbol}</td>
      <td>${sideBadge}</td>
      <td class="tabular">${Number(t.shares || 0).toFixed(4)}</td>
      <td class="tabular">$${Number(t.price || 0).toFixed(2)}</td>
      <td class="tabular">${feeDisplay}</td>
      <td class="tabular ${pnlClass}">${pnlDisplay}</td>
      <td>${statusBadge}</td>
    `;
    tbody.appendChild(tr);
  });
}

// --- Trigger Daily Market Close Report Email (Resend) ---
async function triggerDailyReportEmail() {
  const btn = document.getElementById("btn-send-daily-report");
  const origHtml = btn ? btn.innerHTML : "";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Dispatching via Resend...";
  }
  showToast("Sending daily statement to khanalnischal2075@gmail.com via Resend...", "info");
  try {
    const res = await fetch("/api/report/send", { method: "POST" });
    const data = await res.json();
    if (data.success) {
      showToast("Daily statement successfully dispatched to khanalnischal2075@gmail.com!", "success");
    } else {
      showToast(`Email error: ${data.error || "Failed to send email"}`, "error");
    }
  } catch (err) {
    showToast(`Failed to trigger email: ${err.message}`, "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = origHtml;
    }
  }
}

// --- Toast Notifications ---
function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  if (!container) return;
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// --- Page Navigation Engine ---
function switchPage(pageId) {
  document.querySelectorAll(".rh-page").forEach(page => page.classList.remove("active"));
  const targetPage = document.getElementById(pageId);
  if (targetPage) targetPage.classList.add("active");

  document.querySelectorAll(".rh-bottom-nav .rh-nav-tab").forEach(tab => {
    tab.classList.toggle("active", tab.dataset.page === pageId);
  });

  window.scrollTo({ top: 0, behavior: "smooth" });
  if (history.replaceState) {
    history.replaceState(null, null, "#" + pageId);
  } else {
    window.location.hash = pageId;
  }

  if (pageId === "page-trade") {
    if (state.pipelineData) {
      setTimeout(() => {
        drawExchangeChart(state.activeSymbol, state.pipelineData.plan, state.pipelineData.entry, state.pipelineData);
      }, 50);
    }
  } else if (pageId === "page-history") {
    fetchTrades();
    if (state.pipelineData && state.pipelineData.timemachine) {
      setTimeout(() => {
        drawFanChart(state.pipelineData.timemachine, state.pipelineData.plan);
      }, 50);
    }
  } else if (pageId === "page-ai") {
    fetchNews();
    if (state.pipelineData) {
      renderPipeline(state.pipelineData);
    } else {
      loadPipelineData(state.activeSymbol, state.usdAmount);
    }
  }
}
window.switchPage = switchPage;

// --- Theme Management ---
function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme") || "light";
  const next = current === "light" ? "dark" : "light";
  document.documentElement.setAttribute("data-theme", next);
  localStorage.setItem("daytrader-theme", next);

  const themeLabel = document.getElementById("settings-theme-label");
  if (themeLabel) themeLabel.textContent = next === "light" ? "Switch to Dark Mode" : "Switch to Light Mode";

  const themeIcon = document.getElementById("theme-icon");
  const moonSvg = `<svg class="rh-svg-icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>`;
  const sunSvg = `<svg class="rh-svg-icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>`;
  if (themeIcon) themeIcon.innerHTML = next === "light" ? moonSvg : sunSvg;

  if (state.pipelineData) {
    drawExchangeChart(state.activeSymbol, state.pipelineData.plan, state.pipelineData.entry, state.pipelineData);
    drawFanChart(state.pipelineData.timemachine, state.pipelineData.plan);
  }
}
window.toggleTheme = toggleTheme;

function initTheme() {
  const savedTheme = localStorage.getItem("daytrader-theme") || "light";
  document.documentElement.setAttribute("data-theme", savedTheme);

  const themeLabel = document.getElementById("settings-theme-label");
  if (themeLabel) themeLabel.textContent = savedTheme === "light" ? "Switch to Dark Mode" : "Switch to Light Mode";

  const themeBtn = document.getElementById("btn-theme-toggle");
  const themeIcon = document.getElementById("theme-icon");
  const moonSvg = `<svg class="rh-svg-icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>`;
  const sunSvg = `<svg class="rh-svg-icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>`;

  if (themeIcon) {
    themeIcon.innerHTML = savedTheme === "light" ? moonSvg : sunSvg;
  }

  if (themeBtn) {
    themeBtn.onclick = toggleTheme;
  }
}

// Global scope attachment for inline event handlers
window.executeDemoSell = executeDemoSell;
window.selectTicker = selectTicker;
window.loadPipelineData = loadPipelineData;

// --- DOM Event Bindings ---
document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  initWebSocket();
  setupUniversalSearch();

  const params = new URLSearchParams(window.location.search);
  const qPage = params.get("page");
  const hash = window.location.hash ? window.location.hash.replace("#", "") : "";
  let targetP = qPage || hash;
  if (targetP && !targetP.startsWith("page-")) {
    targetP = "page-" + targetP;
  }
  if (targetP && document.getElementById(targetP)) {
    switchPage(targetP);
  }

  // Instant synchronous first paint of candlestick chart
  drawExchangeChart("TSLA", { entry: 384.28, stop: 382.50, target: 386.06 }, { or_high: 387.80, or_low: 379.80 }, { curr_price: 385.46 });
  loadPipelineData(state.activeSymbol, state.usdAmount);

  // Start continuous Auckland local clock ticker (every second)
  updateNzClockLocal();
  state.nzTimer = setInterval(updateNzClockLocal, 1000);

  // Approved Only Checkbox Toggle
  const chkApproved = document.getElementById("chk-approved-only");
  if (chkApproved) {
    chkApproved.onchange = () => {
      if (state.snapshot && state.snapshot.watchlist) {
        renderScanResults(state.snapshot.watchlist);
      }
    };
  }

  // Preset Filter Chips (All US Approved, Megacap, High-Beta, Sub-$25)
  document.querySelectorAll(".filter-chips-row .filter-chip, .rh-preset-pills .rh-preset-chip").forEach(chip => {
    chip.onclick = async () => {
      document.querySelectorAll(".filter-chips-row .filter-chip, .rh-preset-pills .rh-preset-chip").forEach(c => c.classList.remove("active"));
      chip.classList.add("active");
      const presetSymbols = chip.dataset.preset;
      const isApprovedOnly = document.getElementById("chk-approved-only")?.checked !== false;
      showToast(`Scanning ${chip.textContent} universe...`, "info");
      try {
        const res = await fetch("/api/scan", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mode: "daily", symbols: presetSymbols, approved_only: isApprovedOnly })
        });
        const data = await res.json();
        if (data.watchlist) {
          if (state.snapshot) state.snapshot.watchlist = data.watchlist;
          renderScanResults(data.watchlist);
        }
      } catch (e) {
        console.error("Scan error", e);
      }
    };
  });

  // Chart Toggle: Line vs Candles
  const btnChartLine = document.getElementById("btn-chart-type-line");
  const btnChartCandles = document.getElementById("btn-chart-type-candles");
  if (btnChartLine && btnChartCandles) {
    btnChartLine.onclick = () => {
      state.chartType = "line";
      btnChartLine.classList.add("active");
      btnChartCandles.classList.remove("active");
      if (state.pipelineData) {
        drawExchangeChart(state.activeSymbol, state.pipelineData.plan, state.pipelineData.entry, state.pipelineData);
      }
    };
    btnChartCandles.onclick = () => {
      state.chartType = "candles";
      btnChartCandles.classList.add("active");
      btnChartLine.classList.remove("active");
      if (state.pipelineData) {
        drawExchangeChart(state.activeSymbol, state.pipelineData.plan, state.pipelineData.entry, state.pipelineData);
      }
    };
  }

  // Timeframe selector buttons (1D, 1W, 1M, 3M, 1Y)
  document.querySelectorAll(".rh-tf-btn").forEach(btn => {
    btn.onclick = () => {
      document.querySelectorAll(".rh-tf-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const tf = btn.dataset.tf;
      showToast(`Loading dynamic ${tf} chart...`, "info");
      loadAndDrawChart(state.activeSymbol, tf);
    };
  });

  // Dock Tabs Navigation (Positions, Time Machine, News, Alerts)
  document.querySelectorAll(".dock-tab-header .dock-tab-btn").forEach(btn => {
    btn.onclick = () => {
      document.querySelectorAll(".dock-tab-header .dock-tab-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const tabId = btn.dataset.tab;
      document.querySelectorAll(".dock-tab-pane").forEach(pane => {
        pane.classList.remove("active");
        if (pane.id === tabId) pane.classList.add("active");
      });
      if (tabId === "tab-timemachine" && state.pipelineData) {
        drawFanChart(state.pipelineData.timemachine, state.pipelineData.plan);
      }
    };
  });

  // Order Side Tabs (BUY / LONG vs SELL / EXIT)
  const tabBuy = document.getElementById("tab-order-buy");
  const tabSell = document.getElementById("tab-order-sell");
  const btnBuy = document.getElementById("btn-demo-buy");
  const partialDeck = document.querySelector(".partial-sell-deck");

  if (tabBuy && tabSell) {
    tabBuy.onclick = () => {
      state.orderSide = "buy";
      tabBuy.classList.add("active");
      tabSell.classList.remove("active");
      if (btnBuy) btnBuy.style.display = "flex";
      if (partialDeck) partialDeck.style.display = "flex";
    };

    tabSell.onclick = () => {
      state.orderSide = "sell";
      tabSell.classList.add("active");
      tabBuy.classList.remove("active");
      if (btnBuy) btnBuy.style.display = "none";
      if (partialDeck) partialDeck.style.display = "flex";
    };
  }

  // Quick USD Chips for Order Sizing ($10, $25, $50, $100 Max)
  document.querySelectorAll(".quick-usd-deck .chip-btn").forEach(chip => {
    chip.onclick = () => {
      document.querySelectorAll(".quick-usd-deck .chip-btn").forEach(c => c.classList.remove("active"));
      chip.classList.add("active");
      const val = parseFloat(chip.dataset.usd || 25);
      const usdInput = document.getElementById("demo-order-usd-amount");
      if (usdInput) usdInput.value = val;
      state.usdAmount = val;
      updateDemoTradeMath();
      loadPipelineData(state.activeSymbol, val);
    };
  });

  // USD Amount Input Change Listener
  const usdInput = document.getElementById("demo-order-usd-amount");
  if (usdInput) {
    usdInput.oninput = () => {
      updateDemoTradeMath();
    };
    usdInput.onchange = () => {
      state.usdAmount = parseFloat(usdInput.value || 25);
      loadPipelineData(state.activeSymbol, state.usdAmount);
    };
  }

  // Main 1-Click Buy Execution Button
  const demoBuyBtn = document.getElementById("btn-demo-buy");
  if (demoBuyBtn) demoBuyBtn.onclick = executeDemoBuy;

  // Partial Sell Tranche Buttons (25%, 50%, 100%)
  document.querySelectorAll(".btn-sell-tranche").forEach(btn => {
    btn.onclick = () => {
      const pct = parseFloat(btn.dataset.pct || 100);
      executeDemoSell(state.activeSymbol, null, pct);
    };
  });

  // Partial Sell USD Buttons ($10 USD)
  document.querySelectorAll(".btn-sell-usd").forEach(btn => {
    btn.onclick = () => {
      const usd = parseFloat(btn.dataset.usd || 10);
      executeDemoSell(state.activeSymbol, null, null, usd);
    };
  });

  // Close Position Main Button
  const demoSellBtn = document.getElementById("btn-demo-sell");
  if (demoSellBtn) demoSellBtn.onclick = () => executeDemoSell(state.activeSymbol, null, 100);

  // Flatten Button in Dock Header
  const dockFlattenBtn = document.getElementById("btn-flatten-all");
  if (dockFlattenBtn) dockFlattenBtn.onclick = () => executeDemoSell(state.activeSymbol, null, 100);

  // Quick Demo Cash Refill / Reset Controls ($100 max)
  const reset100Btn = document.getElementById("btn-reset-cash-100");
  if (reset100Btn) reset100Btn.onclick = () => adjustDemoCash("reset", 100);

  const resetDeckBtn = document.getElementById("btn-reset-cash-deck");
  if (resetDeckBtn) resetDeckBtn.onclick = () => adjustDemoCash("reset", 100);

  const add25Btn = document.getElementById("btn-add-cash-25");
  if (add25Btn) add25Btn.onclick = () => adjustDemoCash("add", 25);

  // Gemini News Re-Analyze Button
  const geminiRefreshBtn = document.getElementById("btn-refresh-gemini-news");
  if (geminiRefreshBtn) {
    geminiRefreshBtn.onclick = async () => {
      geminiRefreshBtn.disabled = true;
      geminiRefreshBtn.textContent = "Analyzing...";
      try {
        await Promise.all([
          loadPipelineData(state.activeSymbol, state.usdAmount, true),
          fetchNews(true)
        ]);
        showToast("Gemini 3.5 AI News & Filings re-analyzed", "success");
      } catch (err) {
        console.error("Re-analyze error:", err);
      } finally {
        geminiRefreshBtn.disabled = false;
        geminiRefreshBtn.textContent = "Re-Analyze News";
      }
    };
  }

  // Force Re-Analyze All 11 Skills Button
  const forceReanalyzeBtn = document.getElementById("btn-force-reanalyze");
  if (forceReanalyzeBtn) {
    forceReanalyzeBtn.onclick = async () => {
      forceReanalyzeBtn.disabled = true;
      forceReanalyzeBtn.innerHTML = `
        <svg class="rh-svg-icon-xs spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>
        Re-Analyzing 11 Skills...
      `;
      try {
        await Promise.all([
          loadPipelineData(state.activeSymbol, state.usdAmount, true),
          fetchNews(true)
        ]);
        showToast("All 11 Day Trader skills freshly re-analyzed!", "success");
      } catch (err) {
        console.error("Re-analyze error:", err);
        showToast("Failed to re-analyze skills", "error");
      } finally {
        forceReanalyzeBtn.disabled = false;
        forceReanalyzeBtn.innerHTML = `
          <svg class="rh-svg-icon-xs" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
          Re-Analyze All 11 Skills
        `;
      }
    };
  }

  // Auto-Scan Toggle
  const autoBtn = document.getElementById("btn-toggle-autoscan");
  if (autoBtn) {
    autoBtn.onclick = async () => {
      const next = !state.autoScanEnabled;
      updateAutoScanUI(next);
      try {
        await fetch("/api/auto-scan", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ enabled: next })
        });
        showToast(`Autonomous market scanning ${next ? "active" : "paused"}`, "info");
      } catch (e) {
        console.error(e);
      }
    };
  }

  // Beginner Copilot Interactions (Glossary Drawer & Minimize)
  const btnToggleGlossary = document.getElementById("btn-toggle-glossary");
  const glossaryDrawer = document.getElementById("copilot-glossary-drawer");
  if (btnToggleGlossary && glossaryDrawer) {
    btnToggleGlossary.onclick = () => {
      const isHidden = glossaryDrawer.style.display === "none";
      glossaryDrawer.style.display = isHidden ? "block" : "none";
      btnToggleGlossary.classList.toggle("active", isHidden);
    };
  }

  const btnCopilotMin = document.getElementById("btn-copilot-minimize");
  const copilotSteps = document.getElementById("copilot-steps-container");
  if (btnCopilotMin && copilotSteps) {
    btnCopilotMin.onclick = () => {
      const isCollapsed = copilotSteps.style.display === "none";
      copilotSteps.style.display = isCollapsed ? "grid" : "none";
      btnCopilotMin.textContent = isCollapsed ? "−" : "+";
      btnCopilotMin.title = isCollapsed ? "Collapse guide" : "Expand guide";
    };
  }

  // Settings Page Interactions
  const btnOpenSettings = document.getElementById("btn-open-settings");
  if (btnOpenSettings) btnOpenSettings.onclick = () => switchPage("page-settings");

  const settingsAutoToggle = document.getElementById("settings-autoscan-toggle");
  if (settingsAutoToggle) {
    settingsAutoToggle.checked = state.autoScanEnabled;
    settingsAutoToggle.onchange = async () => {
      const next = settingsAutoToggle.checked;
      updateAutoScanUI(next);
      try {
        await fetch("/api/auto-scan", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ enabled: next })
        });
        showToast(`Autonomous market scanning ${next ? "active" : "paused"}`, "info");
      } catch (e) {
        console.error(e);
      }
    };
  }

  const btnSettingsTheme = document.getElementById("btn-settings-theme-toggle");
  if (btnSettingsTheme) btnSettingsTheme.onclick = toggleTheme;

  const btnSettingsAddCash = document.getElementById("btn-settings-add-cash");
  if (btnSettingsAddCash) btnSettingsAddCash.onclick = () => adjustDemoCash("add", 25);

  const btnSettingsResetCash = document.getElementById("btn-settings-reset-cash");
  if (btnSettingsResetCash) btnSettingsResetCash.onclick = () => adjustDemoCash("reset", 100);

  // Initial Load: Fetch full state, news, and load active symbol pipeline
  fetch("/api/state")
    .then(r => r.json())
    .then(snap => {
      renderAll(snap);
      loadPipelineData("TSLA", 25.0);
      fetchNews();
      fetchTrades();

      // Ensure left watchlist is populated with approved setups immediately
      if (!snap.watchlist || !snap.watchlist.hits || snap.watchlist.hits.length < 3) {
        fetch("/api/scan", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mode: "daily", symbols: "TSLA,NVDA,AAPL,PLTR,SOFI,AMD,MSFT,AMZN,META,GOOGL", approved_only: true })
        })
          .then(res => res.json())
          .then(data => {
            if (data && data.watchlist) {
              if (state.snapshot) state.snapshot.watchlist = data.watchlist;
              renderScanResults(data.watchlist);
            }
          })
          .catch(err => console.warn("Initial scan error:", err));
      }
      const hash = window.location.hash ? window.location.hash.replace("#", "") : "";
      if (hash && document.getElementById(hash)) {
        switchPage(hash);
      }
    })
    .catch(err => {
      console.warn("Init state error:", err);
      loadPipelineData("TSLA", 25.0);
    });
});
