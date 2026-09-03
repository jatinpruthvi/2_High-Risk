"""Dependency-free live dashboard for the paper trading runner.

Serves two endpoints from a ThreadingHTTPServer:

    /            self-contained HTML page (inline CSS/JS, no CDN)
    /state.json  current JSON snapshot from the runner

The page auto-refreshes every few seconds and renders: live chains with
bid/ask per strike, candidate ranking with grades/scores/reasons, the open
position with unrealized P&L and exit-policy state, closed trade history,
realized P&L, and an equity curve (inline SVG). All rendering is vanilla JS.
"""
from __future__ import annotations

import json
import math
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable


def _json_safe(value: Any) -> Any:
    """Recursively replace non-finite floats with None so the served state is
    valid strict JSON (Python's json.dumps emits bare Infinity/NaN otherwise,
    which the browser JSON.parse rejects)."""
    if isinstance(value, float):
        return None if not math.isfinite(value) else value
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value

PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Paper Trading Dashboard</title>
<style>
  :root { --bg:#0f1419; --panel:#1a222b; --border:#2a3542; --text:#dbe4ee; --muted:#8fa1b3;
          --green:#3ecf8e; --red:#f4686a; --amber:#f2c14e; --blue:#58a6ff; }
  * { box-sizing:border-box; }
  body { background:var(--bg); color:var(--text); font:14px/1.45 -apple-system, "Segoe UI", Roboto, sans-serif; margin:0; padding:16px; }
  h1 { font-size:20px; margin:0 0 4px; }
  h2 { font-size:15px; margin:18px 0 8px; border-bottom:1px solid var(--border); padding-bottom:6px; }
  .sub { color:var(--muted); font-size:12px; margin-bottom:12px; }
  .cards { display:flex; flex-wrap:wrap; gap:10px; margin-bottom:6px; }
  .card { background:var(--panel); border:1px solid var(--border); border-radius:8px; padding:10px 14px; min-width:150px; }
  .card .k { color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.04em; }
  .card .v { font-size:18px; font-weight:600; margin-top:2px; }
  .pos { color:var(--green); } .neg { color:var(--red); }
  table { border-collapse:collapse; width:100%; font-size:12px; background:var(--panel); border-radius:8px; overflow:hidden; }
  th, td { padding:5px 8px; border-bottom:1px solid var(--border); text-align:right; white-space:nowrap; }
  th { background:#212b36; color:var(--muted); font-weight:600; }
  td:first-child, th:first-child { text-align:left; }
  tr:hover td { background:#202a35; }
  .open { background:#13231d !important; } .open:hover td { background:#163129 !important; }
  .badge { display:inline-block; padding:1px 7px; border-radius:10px; font-size:11px; font-weight:600; }
  .b-A { background:#143d2a; color:var(--green); } .b-B { background:#3d3314; color:var(--amber); }
  .b-C { background:#3d1f14; color:var(--amber); } .b-Reject { background:#3d1414; color:var(--red); }
  .reasons { color:var(--muted); font-size:11px; max-width:320px; white-space:normal; }
  .pill { display:inline-block; background:#212b36; border:1px solid var(--border); border-radius:12px; padding:2px 10px; margin:2px 4px 2px 0; font-size:12px; }
  .note { color:var(--muted); font-size:11px; margin-top:14px; }
  .err { color:var(--red); }
  .muted { color:var(--muted); }
  #equity svg { background:var(--panel); border:1px solid var(--border); border-radius:8px; width:100%; height:140px; }
  .chain-grid { display:flex; flex-wrap:wrap; gap:10px; }
  .chain-panel { background:var(--panel); border:1px solid var(--border); border-radius:8px; padding:8px; min-width:300px; flex:1; }
  .chain-panel h3 { margin:0 0 6px; font-size:13px; }
  .strike-row { display:grid; grid-template-columns:1fr 1fr 40px 1fr 1fr; gap:4px; font-size:11px; padding:2px 0; border-bottom:1px solid #1d2733; }
  .strike-row.head { color:var(--muted); font-size:10px; }
</style>
</head>
<body>
  <h1>Paper Trading Dashboard</h1>
  <div class="sub" id="sub">connecting…</div>
  <div id="override" class="err" style="display:none;background:#3d1414;border:1px solid var(--red);border-radius:8px;padding:8px 12px;margin-bottom:10px;font-weight:600">⚠ PAPER-ONLY CONFIG OVERRIDES ACTIVE — these do NOT affect uploads/PARAMETERS.json. Do not treat these results as live-parameter evidence.</div>
  <div class="cards">
    <div class="card"><div class="k">Mode</div><div class="v" id="mode">—</div></div>
    <div class="card"><div class="k">Market</div><div class="v" id="market"></div></div>
    <div class="card"><div class="k">CAS monitor</div><div class="v" id="cas-monitor">-</div></div>
    <div class="card"><div class="k">Evidence quality</div><div class="v" id="evidence-quality">-</div></div>
    <div class="card"><div class="k">Opportunity flow</div><div class="v" id="opportunity-flow">-</div></div>
    <div class="card"><div class="k">Learning pipeline</div><div class="v" id="learning-pipeline">-</div></div>
    <div class="card"><div class="k">Data quorum</div><div class="v" id="data-quorum">-</div></div>
    <div class="card"><div class="k">Current equity</div><div class="v" id="capital">—</div></div>
    <div class="card"><div class="k">Realized P&amp;L</div><div class="v" id="pnl">—</div></div>
    <div class="card"><div class="k">Trades today</div><div class="v" id="trades">—</div></div>
    <div class="card"><div class="k">Win rate</div><div class="v" id="winrate">—</div></div>
    <div class="card"><div class="k">Net P&amp;L avg</div><div class="v" id="avgpnl">—</div></div>
  </div>
  <div id="err" class="err"></div>
  <div id="schedule" class="note"></div>
  <div id="breakout" class="note"></div>
  <div id="experimental" class="note"></div>
  <div id="fyers-health" class="note"></div>
  <div id="no-trade-alpha" class="note"></div>
  <div id="paper-calibration" class="note"></div>

  <h2>Open Position</h2>
  <div id="open">no open position</div>

  <h2>Candidates</h2>
  <div id="cands">waiting for cycle…</div>

  <h2>Qualified Opportunities (paper-only)</h2>
  <div class="note">Qualified candidates are shown even when capacity, daily risk, or ranking prevents a paper position.</div>
  <div id="qualified">no qualified opportunities recorded</div>

  <h2>Live Chains</h2>
  <div class="chain-grid" id="chains"></div>

  <h2>Equity Curve (realized P&amp;L)</h2>
  <div id="equity"></div>

  <h2>Closed Trades</h2>
  <div id="closed">no closed trades yet</div>

  <div class="note" id="note"></div>

<script>
const $ = (id) => document.getElementById(id);
const fmt = (v, d=2) => v == null ? '—' : Number(v).toLocaleString('en-IN', {maximumFractionDigits: d, minimumFractionDigits: d});
const cls = (v) => (v > 0 ? 'pos' : (v < 0 ? 'neg' : ''));
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

function render(st) {
  const lastCycle = st.last_cycle || 'not published yet';
  const provenanceNote = st.note || 'No paper-runner provenance note published';
  $('sub').textContent = `started ${st.started_at || '—'} · session ${st.session_id || '—'} · last cycle ${lastCycle} · ${provenanceNote}`;
  $('mode').textContent = st.mode || 'UNKNOWN';
  $('market').textContent = st.market_open ? 'OPEN' : 'CLOSED';
  $('capital').textContent = '₹' + fmt(st.capital, 0);
  $('pnl').textContent = '₹' + fmt(st.realized_pnl, 0);
  $('pnl').className = cls(st.realized_pnl);
  const trades = st.closed_trades || [];
  const wins = trades.filter(t => t.net_pnl > 0).length;
  const tradesToday = Number.isFinite(Number(st.trades_today)) ? Number(st.trades_today) : trades.length;
  $('trades').textContent = tradesToday;
  $('winrate').textContent = trades.length ? (100*wins/trades.length).toFixed(0) + '%' : '—';
  $('avgpnl').textContent = trades.length ? '₹' + fmt(trades.reduce((a,t)=>a+t.net_pnl,0)/trades.length, 0) : '—';
  const cycleStartedMs = st.cycle_started_at ? Date.parse(st.cycle_started_at) : NaN;
  const cycleAgeSeconds = Number.isFinite(cycleStartedMs)
    ? Math.max(0, Math.floor((Date.now() - cycleStartedMs) / 1000))
    : null;
  const cycleAgeText = cycleAgeSeconds == null
    ? 'elapsed time unavailable'
    : `${Math.floor(cycleAgeSeconds / 60)}m ${cycleAgeSeconds % 60}s elapsed`;
  const cycleError = st.cycle_in_progress
    ? `Live Fyers cycle in progress (${cycleAgeText}); awaiting the next completed snapshot.`
    : (st.last_error || st.error || st.preview_error || (
      st.market_open === false && !st.last_cycle
        ? 'No live paper cycle is available yet; the market is closed or the runner is still initializing.'
        : 'The paper runner did not publish an error detail for the last cycle.'
    ));
  const errEl = $('err');
  if (st.last_cycle_ok) {
    errEl.textContent = '';
    errEl.style.display = 'none';
  } else {
    errEl.textContent = 'Paper-cycle status: ' + cycleError;
    errEl.style.display = 'block';
  }
  const schedule = (st.underlyings && st.underlyings._paper_schedule) || {};
  const deferred = Array.isArray(schedule.deferred) ? schedule.deferred.length : 0;
  const selected = Array.isArray(schedule.selected) ? schedule.selected.length : 0;
  const audits = Array.isArray(schedule.audit_lane) ? schedule.audit_lane.length : 0;
  const opportunities = Array.isArray(schedule.opportunity_lane) ? schedule.opportunity_lane.length : 0;
  $('schedule').textContent = schedule.mode
    ? `Scheduler: ${schedule.mode} · selected ${selected} · opportunity ${opportunities} · audit ${audits} · deferred ${deferred} · max audit age ${schedule.max_full_audit_cycles ?? '—'} cycles`
    : 'Scheduler metadata not published yet';
  const cas = (st.underlyings && st.underlyings._cas_monitor) || st.cas_monitor || {};
  $('cas-monitor').textContent = cas.status
     ? `CAS ${cas.status} - ${cas.phase || '-'} - observed ${cas.observed_legs ?? 0} legs - anomalies ${cas.anomaly_events ?? 0} - ${cas.paper_only ? 'research-only' : 'CHECK CONFIG'}`
     : 'CAS monitor not published yet';
  const evidence = st.evidence_analytics || {};
  const integrity = evidence.session_integrity || {};
  const totalEvidence = evidence.total || {};
  $('evidence-quality').textContent = `${integrity.status || 'UNKNOWN'} - ${totalEvidence.sample_size ?? 0}/${evidence.min_sample_for_calibration ?? 30} trades - ${totalEvidence.status || 'WARMUP'}`;
  const flow = st.opportunity_heartbeat || {};
  $('opportunity-flow').textContent = `${flow.status || 'UNKNOWN'} - ${flow.evaluated ?? 0} eval / ${flow.eligible ?? 0} eligible / ${flow.data_invalid ?? 0} invalid`;
  const learning = st.opportunity_learning || {};
  $('learning-pipeline').textContent = `${learning.armed_candidates ?? 0} armed / ${learning.active_candidates ?? 0} active / ${learning.forward_outcome_records ?? 0} outcomes`;
  const quorum = st.data_quorum || {};
  const stages = quorum.stages || {};
  $('data-quorum').textContent = `${quorum.status || 'UNKNOWN'} - ${stages.data_health ?? 0}/${stages.total ?? 0} health / ${stages.quote ?? 0}/${stages.total ?? 0} quote / ${stages.top_book ?? 0}/${stages.total ?? 0} book`;
  const breakout =
(st.underlyings && st.underlyings._gate_breakout) || {};
  const breakoutNames = Array.isArray(breakout.breakout_underlyings) ? breakout.breakout_underlyings.join(', ') : '';
  $('breakout').textContent = breakout.enabled
    ? `Gate breakout: ${breakoutNames || 'none'} · metric ${breakout.metric || '—'} · lookback ${breakout.lookback_seconds ?? '—'}s · selected ${breakout.selected_underlying || 'none'}`
    : 'Gate breakout selector not published yet';
  const experimental = (st.underlyings && st.underlyings._experimental_impulse_breakout) || {};
  const statusCounts = experimental.status_counts || {};
  const statusText = Object.entries(statusCounts).map(([k,v]) => `${k}:${v}`).join(', ');
  $('experimental').textContent = experimental.enabled
    ? `Experimental ${experimental.label || 'IMPULSE_BREAKOUT'}: ${experimental.status || '—'} · raw signals ${experimental.raw_signal_count ?? 0} · selected ${experimental.selected_underlying || 'none'} · cost ${experimental.cost_model_valid ? 'validated' : 'unvalidated'} · ${statusText || 'no observations'}`
    : 'Experimental impulse-breakout lane not published';
  const fh = st.fyers_request_health || {};
  $('fyers-health').textContent = fh.requests == null
    ? 'Fyers request-health metadata not published yet'
    : `Fyers request health: ${fh.requests} requests | ${fh.successes || 0} successes | ${fh.errors || 0} errors | ${fh.rate_limit_hits || 0} rate-limit hits | ${fh.retries || 0} retries | pacing ${fmt(fh.min_interval_seconds,2)}s`;
  const nta = (st.underlyings && st.underlyings._no_trade_alpha) || {};
  $('no-trade-alpha').textContent = nta.status
    ? `No-Trade Alpha (${nta.research_only ? 'research-only' : '—'}): ${nta.status} · observed ${nta.observed_rows ?? 0} · unavailable ${nta.unavailable_rows ?? 0} · saved-loss ${(nta.saved_loss_rate == null ? '—' : (100*nta.saved_loss_rate).toFixed(1)+'%')} · missed-winner ${(nta.missed_winner_rate == null ? '—' : (100*nta.missed_winner_rate).toFixed(1)+'%')} · avg forward R ${fmt(nta.average_forward_r,2)}`
    : 'No-Trade Alpha metadata not published yet';
  const pc = (st.underlyings && st.underlyings._paper_calibration) || {};
  $('paper-calibration').textContent = pc.enabled
    ? `Paper calibration (research-only): ${pc.status || '—'} · evaluated ${pc.evaluated_candidates ?? 0} · safe ${pc.safe_candidates ?? 0} · selected ${pc.selected_underlying || 'none'} ${pc.selected_side || ''} · cap ${pc.thresholds?.score ?? '—'} score / ${pc.thresholds?.premium_elasticity_proxy ?? '—'} proxy elasticity / ${pc.thresholds?.expected_required_ratio ?? '—'} expected-required · costs ${pc.cost_model_valid ? 'validated' : 'unvalidated'}`
    : 'Paper calibration lane not published';
  const ov = $('override');
  if (st.paper_overrides_active) {
    ov.style.display = 'block';
    ov.textContent = '⚠ PAPER-ONLY CONFIG OVERRIDES ACTIVE: ' + JSON.stringify(st.active_overrides) + ' — uploads/PARAMETERS.json is NOT modified. Not valid evidence for live parameters.';
  } else {
    ov.style.display = 'none';
  }
  renderOpen(st.open_position, st.open_positions || []);
  renderCands((st.underlyings && st.underlyings._candidates) || []);
  renderQualified(st.qualified_opportunities || []);
  renderChains(st.underlyings || {});
  renderEquity(st.equity || []);
  renderClosed(trades);
}

function renderOpen(primary, positions) {
  const el = $('open');
  const rows = Array.isArray(positions) && positions.length ? positions : (primary ? [primary] : []);
  if (!rows.length) { el.textContent = 'no open paper positions'; return; }
  let total = 0;
  let html = '<div class="card open" style="min-width:100%"><div class="v" style="font-size:14px">' +
    `<span class="pill">open paper positions: ${rows.length}</span>`;
  for (const p of rows) {
    const uPoints = p.unrealized_points ?? ((p.last != null && p.entry != null) ? p.last - p.entry : null);
    const uPnl = p.unrealized_pnl ?? uPoints;
    total += Number(uPnl || 0);
    const pol = p.exit_policy || {};
    const bits = [
      `${esc(p.underlying || '')} ${esc(p.side || '—')} ${fmt(p.strike,0)} @ ${fmt(p.entry)}`,
      `last ${fmt(p.last)}`,
      `uPnL <span class="${cls(uPnl)}">₹${fmt(uPnl, 0)}</span> (${fmt(uPoints,1)} pts)`,
      `stop ${fmt(p.stop_points,1)} pts · target ${fmt(p.target_points,1)} pts`,
      `elapsed ${p.elapsed_sec}s / ${p.max_duration_sec}s`,
      `MFE ${fmt(p.mfe_points,1)} · MAE ${fmt(p.mae_points,1)} · bars ${p.bars}`,
      `mode: ${esc(p.entry_mode || 'CANONICAL')}${p.entry_mode === 'PAPER_CALIBRATION' ? ' · research-only' : ''}`,
      `policy: be@${pol.breakeven_trigger_r}R trail@${pol.trail_trigger_r}R/${pol.trail_distance_r}R lossCut@${pol.losing_time_stop_fraction} vts@${pol.vol_time_stop_fraction||0} slip@${pol.stop_exit_slippage_frac||0}`,
    ];
    html += '<div class="v" style="font-size:14px;margin-top:8px">' + bits.map(b=>`<span class="pill">${b}</span>`).join('') + '</div>';
  }
  html += `<div class="v" style="font-size:14px;margin-top:8px"><span class="pill">aggregate unrealized P&L: <span class="${cls(total)}">₹${fmt(total,0)}</span></span></div></div>`;
  el.innerHTML = html;
}

function renderQualified(rows) {
  const el = $('qualified');
  if (!rows.length) { el.textContent = 'no qualified opportunities recorded'; return; }
  const head = ['time','underlying','side','strike','lane','status','score','bid','ask','reason'];
  let html = '<table><tr>' + head.map(h => '<th>' + esc(h) + '</th>').join('') + '</tr>';
  for (const r of rows.slice(-200).reverse()) {
    html += '<tr>' + [r.ts, r.underlying, r.side, fmt(r.strike, 0), r.lane, r.status, fmt(r.score, 1), fmt(r.bid, 2), fmt(r.ask, 2), r.reason].map(v => '<td>' + esc(v) + '</td>').join('') + '</tr>';
  }
  el.innerHTML = html + '</table>';
}

function renderCands(rows) {
  const el = $('cands');
  if (!rows.length) { el.textContent = 'no candidates evaluated yet'; return; }
  const head = ['underlying','side','strike','expiry','grade','score','threshold','eligible','decision','CQ','elas','conv','exec','conf','regime','dir','bid/ask','reasons'];
  let h = '<table><tr>' + head.map(c=>`<th>${c}</th>`).join('') + '</tr>';
  for (const r of rows) {
    const grade = String(r.grade ?? '—');
    const gradeCls = 'b-' + grade.replace('+','').trim();
    h += `<tr><td>${esc(r.underlying)}</td><td>${esc(r.side)}</td><td>${fmt(r.strike,0)}</td><td>${esc(r.expiry)}</td>` +
      `<td><span class="badge ${gradeCls}">${esc(grade)}</span></td>` +
      `<td>${fmt(r.score,1)}</td><td>${fmt(r.threshold,1)}</td><td>${r.eligible?'✓':'✗'}</td><td>${esc(r.decision)}</td>` +
      `<td>${fmt(r.contract_quality,1)}</td><td>${fmt(r.premium_elasticity,2)}</td><td>${fmt(r.convexity,1)}</td>` +
      `<td>${fmt(r.execution,1)}</td><td>${fmt(r.confidence,1)}</td><td>${fmt(r.regime_fit,1)}</td><td>${fmt(r.direction,1)}</td>` +
      `<td>${fmt(r.bid,1)}/${fmt(r.ask,1)}</td><td class="reasons">${esc(r.reasons)}</td></tr>`;
  }
  el.innerHTML = h + '</table>';
}

function renderChains(uds) {
  const el = $('chains');
  el.innerHTML = '';
  for (const [und, d] of Object.entries(uds)) {
    if (und.startsWith('_')) continue;
    if (d.error) {
      const ch = d.chain_health || {};
      const reason = ch.reason_code ? ` [${esc(ch.reason_code)}]` : '';
      el.innerHTML += `<div class="chain-panel"><h3>${esc(und)}</h3><span class="err">${esc(d.error)}${reason}</span><div class="muted" style="font-size:11px;margin-top:5px">fail-closed: ${ch.fail_closed === false ? 'no' : 'yes'}</div></div>`;
      continue;
    }
    let rows = `<div class="strike-row head"><span>Strike</span><span>CE bid/ask</span><span></span><span>PE bid/ask</span><span>spot ${fmt(d.spot,1)}</span></div>`;
    for (const s of (d.strikes || [])) {
      const ce = s.ce ? fmt(s.ce.bid,1)+' / '+fmt(s.ce.ask,1) : '—';
      const pe = s.pe ? fmt(s.pe.bid,1)+' / '+fmt(s.pe.ask,1) : '—';
      const marker = s.atm ? '◄' : '';
      rows += `<div class="strike-row"><span>${fmt(s.strike,0)} ${marker}</span><span>${ce}</span><span></span><span>${pe}</span><span></span></div>`;
    }
    const dh = d.depth_health || {};
    const failures = Array.isArray(dh.failure_reasons) ? dh.failure_reasons.slice(0, 2).join('; ') : (dh.last_error || '');
    const depthReason = failures ? ` · reason ${esc(failures)}` : '';
    const depth = `depth ${esc(dh.status || '—')} ${dh.successful_legs ?? 0}/${dh.requested_legs ?? 0} · 5L ${dh.five_level_legs ?? 0} · 429 ${dh.rate_limit_errors ?? 0}${depthReason}`;
    const meta = `VIX ${d.vix!=null?fmt(d.vix,1):'—'} · exp ${esc(d.expiry)} · dte ${fmt(d.dte,1)} · dir ${fmt(d.direction,0)} · TQ ${fmt(d.trade_quality,0)} · host ${fmt(d.hostility,0)} · reqMove ${fmt(d.required_move,0)} · ATR1 ${fmt(d.atr1,2)} · eff ${fmt(d.trend_eff,0)} · ${depth}`;
    el.innerHTML += `<div class="chain-panel"><h3>${esc(und)}</h3><div class="muted" style="font-size:11px;margin-bottom:6px">${meta}</div>${rows}</div>`;
  }
}

function renderEquity(equity) {
  const el = $('equity');
  if (!equity.length) { el.innerHTML = '<span class="muted">no equity data yet</span>'; return; }
  const w = 900, h = 140, pad = 8;
  const min = Math.min(...equity), max = Math.max(...equity), span = (max-min) || 1;
  const pts = equity.map((v,i) => [pad + i*(w-2*pad)/(equity.length-1||1), h-pad - (v-min)/span*(h-2*pad)]);
  const line = pts.map(p=>p.join(',')).join(' ');
  const last = equity[equity.length-1];
  el.innerHTML = `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polyline points="${line}" fill="none" stroke="${last>=0?'#3ecf8e':'#f4686a'}" stroke-width="1.6"/></svg>` +
    `<div class="muted">last realized P&amp;L ₹${fmt(last,0)} · peak ₹${fmt(max,0)} · trough ₹${fmt(min,0)}</div>`;
}

function renderClosed(trades) {
  const el = $('closed');
  if (!trades.length) { el.textContent = 'no closed trades yet'; return; }
  const rev = [...trades].reverse();
  const head = ['#','underlying','side','strike','entry','exit','reason','gross pts','net ₹','hold'];
  let h = '<table><tr>' + head.map(c=>`<th>${c}</th>`).join('') + '</tr>';
  rev.forEach((t,i) => {
    h += `<tr><td>${trades.length-i}</td><td>${esc(t.underlying)}</td><td>${esc(t.side)}</td><td>${fmt(t.strike,0)}</td>` +
      `<td>${fmt(t.entry_fill)}</td><td>${fmt(t.exit_fill)}</td><td>${esc(t.exit_reason)}</td>` +
      `<td class="${cls(t.gross_points)}">${fmt(t.gross_points,1)}</td><td class="${cls(t.net_pnl)}">₹${fmt(t.net_pnl,0)}</td>` +
      `<td>${fmt(t.hold_seconds,0)}s</td></tr>`;
  });
  el.innerHTML = h + '</table>';
}

let tickInFlight = false;
async function tick() {
  if (tickInFlight) return;
  tickInFlight = true;
  try {
    const r = await fetch('state.json', {cache:'no-store'});
    const payload = await r.json();
    if (!r.ok) {
      render({...payload, last_cycle_ok:false});
      return;
    }
    render(payload);
  } catch (e) {
    const errEl = $('err');
    errEl.textContent = 'state fetch failed: ' + e;
    errEl.style.display = 'block';
  } finally {
    tickInFlight = false;
  }
}
tick();
setInterval(tick, 3000);
</script>
</body>
</html>
"""


class DashboardHandler(BaseHTTPRequestHandler):
    snapshot_fn: Callable[[], dict] = lambda: {}

    def _safe_write(self, body: bytes) -> None:
        """Write the body, ignoring client-connection aborts so a single
        dropped dashboard connection cannot take down the whole runner."""
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError):
            return

    def do_GET(self):  # noqa: N802 (stdlib naming)
        path = self.path.split("?", 1)[0]
        if path == "/state.json":
            try:
                payload = _json_safe(self.snapshot_fn())
                body = json.dumps(payload, allow_nan=False).encode("utf-8")
                status = 200
            except Exception as exc:
                body = json.dumps({"error": "snapshot_unavailable", "detail": str(exc), "preview_only": True, "live_execution": "DISABLED"}).encode("utf-8")
                status = 503
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self._safe_write(body)
            return
        if path not in {"/", "/index.html"}:
            body = json.dumps({"error": "not_found", "preview_only": True, "live_execution": "DISABLED"}).encode("utf-8")
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self._safe_write(body)
            return
        body = PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self._safe_write(body)

    def log_message(self, fmt, *args):  # keep the loop output clean
        return


class PaperDashboard:
    def __init__(self, snapshot_fn: Callable[[], dict], host: str = "127.0.0.1", port: int = 8765):
        self.snapshot_fn = snapshot_fn
        self.host = host
        self.port = port
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> str:
        handler = type("Handler", (DashboardHandler,), {"snapshot_fn": staticmethod(self.snapshot_fn)})
        self._server = ThreadingHTTPServer((self.host, self.port), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return f"http://{self.host}:{self.port}"

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
