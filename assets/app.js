/* Shared rendering helpers for the Nifty 50 board (index.html) and the
   F&O sector board (sectors.html). Both pages import this file, so the tile,
   day-range, index-card and movers components cannot drift apart. */

const POLL_MS = 30000;
const STALE_MS = 20 * 60 * 1000; // flag if the data file hasn't updated in 20 min

/* Per-stock colour scale (shared by both boards so a colour means the
   same % move everywhere). */
function bucket(pct){
  if(pct === null || pct === undefined) return 'b-na';
  if(pct >= 3) return 'b-strong-gain';
  if(pct >= 2) return 'b-gain-3';
  if(pct >= 1) return 'b-gain-2';
  if(pct > 0)  return 'b-gain-1';
  if(pct === 0) return 'b-flat';
  if(pct > -1) return 'b-loss-1';
  if(pct > -2) return 'b-loss-2';
  return 'b-strong-loss';
}

/* Sector averages are far smaller in magnitude than single-stock moves, so
   they get their own finer scale. Same palette, different thresholds. */
function sectorBucket(pct){
  if(pct === null || pct === undefined) return 'b-na';
  if(pct >= 1.5)  return 'b-strong-gain';
  if(pct >= 0.75) return 'b-gain-3';
  if(pct >= 0.25) return 'b-gain-2';
  if(pct > 0)     return 'b-gain-1';
  if(pct === 0)   return 'b-flat';
  if(pct > -0.25) return 'b-loss-1';
  if(pct > -0.75) return 'b-loss-2';
  if(pct > -1.5)  return 'b-loss-3';
  return 'b-strong-loss';
}

function fmtPrice(p){
  return p === null || p === undefined ? 'N/A' : '₹' + p.toLocaleString('en-IN', {minimumFractionDigits:2, maximumFractionDigits:2});
}
function fmtPct(p){
  if(p === null || p === undefined) return '—';
  const sign = p >= 0 ? '+' : '';
  return sign + p.toFixed(2) + '%';
}
function fmtCompact(p){
  return p === null || p === undefined ? '—' : p.toLocaleString('en-IN', { maximumFractionDigits: 0 });
}
function nseUrl(ticker){
  const symbol = ticker.replace(/\.NS$/, '');
  return `https://www.nseindia.com/get-quotes/equity?symbol=${encodeURIComponent(symbol)}`;
}
function slug(s){
  return s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
}

function dayRangeBar(r){
  if(r.dayLow === null || r.dayLow === undefined || r.dayHigh === null || r.dayHigh === undefined || r.dayHigh <= r.dayLow || r.price === null){
    return '';
  }
  let pos = (r.price - r.dayLow) / (r.dayHigh - r.dayLow) * 100;
  pos = Math.min(100, Math.max(0, pos));
  return `
    <div class="day-range">
      <div class="track"><div class="dot" style="left:${pos.toFixed(1)}%"></div></div>
      <div class="labels"><span>${fmtCompact(r.dayLow)}</span><span>${fmtCompact(r.dayHigh)}</span></div>
    </div>
  `;
}

/* A name trading ex a corporate action. The raw print is an artefact - the
   share count or the company changed overnight - so the tile is LABELLED
   rather than left to read as a catastrophic loss. A split or bonus has an
   exact ratio from its announced terms, so the % shown is the real
   like-for-like move; a demerger has no such ratio, so it reads NA. */
function caTag(r){
  if(!r.ca) return '';
  const what = /split/i.test(r.ca.what) ? 'ex-split'
             : /bonus/i.test(r.ca.what) ? 'ex-bonus' : 'ex-demerger';
  return `<div class="ca-tag${r.ca.adjusted ? '' : ' na'}">${what}${r.ca.adjusted ? ' · adj' : ''}</div>`;
}
function caTitle(r){
  if(!r.ca) return '';
  return ` · Ex ${r.ca.what} (${r.ca.date}). Raw print ${fmtPct(r.ca.rawPct)} is an artefact; `
    + (r.ca.adjusted
        ? 'shown adjusted for the announced ratio, which is the real move.'
        : 'a demerger has no like-for-like change, so this reads NA today.');
}

/* One stock tile: name, price, % change, day-range bar, click through to NSE. */

/* Elapsed tenure for the week/month bars, set by whichever board supplies it.
   The sector board does not, and its rows carry no week/month block either,
   so the same tileHtml quietly renders the day bar alone there. */
let TENURE = null;
function setTenure(t){ TENURE = t || null; }

/* Week and month ranges as ONE nested bar, under the unchanged day bar.
   The outer band is the month so far, the brighter band inside it the week so
   far, and the dot is the live price -- so you read at a glance where today
   sits inside both. Both ranges cover only the sessions that have happened,
   which is why the caption carries how many: a month range on the 2nd and on
   the 28th are not the same kind of number, and nothing on the tile used to
   say which one you were looking at. */
function periodBar(r){
  const m = r.month, w = r.week;
  if(!m || !w || r.price === null || m.high <= m.low) return '';
  const span = m.high - m.low;
  const pos = v => Math.max(0, Math.min(100, (v - m.low) / span * 100));
  const wl = pos(w.low), wr = 100 - pos(w.high);
  const t = TENURE || {};
  const cap = (t.week && t.month)
    ? `W ${t.week.elapsed}/${t.week.total} M ${t.month.elapsed}/${t.month.total}`
    : '';
  const tip = cap
    ? `Week ${fmtPrice(w.low)}–${fmtPrice(w.high)} · Month ${fmtPrice(m.low)}–${fmtPrice(m.high)}`
      + ` · sessions so far / weekdays in the period (NSE holidays are not excluded from the total)`
    : '';
  return `
    <div class="per-range" title="${tip}">
      <div class="per-track">
        <div class="per-m"></div>
        <div class="per-w" style="left:${wl.toFixed(1)}%;right:${wr.toFixed(1)}%"></div>
        <div class="per-dot" style="left:${pos(r.price).toFixed(1)}%"></div>
      </div>
      <div class="per-cap"><span>${fmtCompact(m.low)}</span><span class="ten">${cap}</span><span>${fmtCompact(m.high)}</span></div>
    </div>
  `;
}

function tileHtml(r){
  const pctText = (r.ca && !r.ca.adjusted) ? 'NA' : fmtPct(r.pct);
  return `
    <a class="tile ${bucket(r.pct)}${r.cashOnly ? ' cash-only' : ''}${r.ca ? ' ex-ca' : ''}" href="${nseUrl(r.ticker)}" target="_blank" rel="noopener noreferrer" title="${r.full ? r.full + ' · ' : ''}Day range: ${fmtPrice(r.dayLow)} – ${fmtPrice(r.dayHigh)}${r.cashOnly ? ' · cash only, no F&O' : ''}${caTitle(r)} · View on NSE">
      <div class="name">${r.name}${r.ca ? '<span class="adj-star" title="price history adjusted for a corporate action">*</span>' : ''}</div>
      ${r.full && r.full !== r.name ? `<div class="full">${r.full}</div>` : ''}
      <div class="figures">
        <div class="price">${fmtPrice(r.price)}</div>
        <div class="pct">${pctText}</div>
      </div>
      ${caTag(r)}
      ${dayRangeBar(r)}
      ${periodBar(r)}
    </a>
  `;
}

function indexCardHtml(displayName, idx){
  if(!idx || idx.price === undefined || idx.price === null){
    return `<div class="index-card"><div class="index-card-head"><span class="idx-name">${displayName}</span></div><span style="color:var(--text-dim);font-size:12px;">No data</span></div>`;
  }
  const up = idx.pct >= 0;
  const headHtml = `
    <div class="index-card-head">
      <span class="idx-name">${displayName}</span>
      <span class="idx-figures">
        <span class="idx-price">${idx.price.toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2})}</span>
        <span class="idx-delta ${up ? 'up':'down'}">${up?'+':''}${idx.pct.toFixed(2)}% (${up?'+':''}${idx.pts.toFixed(1)} pts)</span>
      </span>
    </div>
  `;

  let rangeHtml = '';
  if(idx.dayLow !== null && idx.dayLow !== undefined && idx.dayHigh !== null && idx.dayHigh !== undefined && idx.dayHigh > idx.dayLow){
    let pos = (idx.price - idx.dayLow) / (idx.dayHigh - idx.dayLow);
    pos = Math.min(0.94, Math.max(0.06, pos));
    const leftExpr = `calc(44px + (100% - 88px) * ${pos.toFixed(4)})`;
    rangeHtml = `
      <div class="range-visual">
        <div class="track-line"></div>
        <div class="end-pill low">${idx.dayLow.toLocaleString('en-IN',{maximumFractionDigits:0})}</div>
        <div class="end-pill high">${idx.dayHigh.toLocaleString('en-IN',{maximumFractionDigits:0})}</div>
        <div class="cur-stem" style="left:${leftExpr}"></div>
        <div class="cur-pill" style="left:${leftExpr}">${idx.price.toLocaleString('en-IN',{maximumFractionDigits:2})}</div>
        <div class="cur-dot" style="left:${leftExpr}"></div>
      </div>
    `;
  }
  return `<div class="index-card">${headHtml}${rangeHtml}</div>`;
}

function moversList(items, field){
  return items.map(r => `
    <div class="mover-row">
      <div class="mover-top">
        <span class="m-name">${r.name}${r.full && r.full !== r.name ? `<span class="m-full">${r.full}</span>` : ''}</span>
        <span class="m-price">${fmtPrice(r.price)}</span>
        <span class="m-pct">${fmtPct(r[field])}</span>
      </div>
      ${dayRangeBar(r)}
    </div>
  `).join('');
}

function renderLegend(elId){
  const stops = [
    ['b-strong-loss','≤ -2%'], ['b-loss-2','-1.5%'], ['b-loss-1','-0.5%'],
    ['b-flat','0%'], ['b-gain-1','+0.5%'], ['b-gain-2','+1.5%'], ['b-strong-gain','≥ +3%'],
  ];
  const el = document.getElementById(elId);
  if(el) el.innerHTML = stops.map(([cls,lbl]) =>
    `<div class="chip ${cls}"></div><span class="lbl">${lbl}</span>`
  ).join('');
}

function setStatus(text, stale){
  const t = document.getElementById('statusText');
  const tag = document.getElementById('statusTag');
  if(t) t.textContent = text;
  if(tag) tag.classList.toggle('stale', !!stale);
}

/* Poll `dataFile` every POLL_MS and hand the parsed payload to `renderFn`. */
function startPolling(dataFile, renderFn){
  async function poll(){
    try{
      const resp = await fetch(dataFile + '?t=' + Date.now(), { cache: 'no-store' });
      if(!resp.ok) throw new Error('HTTP ' + resp.status);
      const data = await resp.json();
      renderFn(data);

      const generated = new Date(data.generatedAt);
      const ageMs = Date.now() - generated.getTime();
      const ageMin = Math.round(ageMs / 60000);
      const timeStr = generated.toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', second: '2-digit' });
      const stale = ageMs > STALE_MS;
      setStatus(`Updated ${timeStr} IST · ${ageMin < 1 ? 'just now' : ageMin + 'm ago'}${stale ? ' (stale)' : ''}`, stale);
    }catch(e){
      setStatus(`Could not reach ${dataFile} — retrying…`, true);
    }
  }
  poll();
  setInterval(poll, POLL_MS);
}

/* Floating "back to top" button. Created from here so both boards get it and
   neither can drift. Appears once you are past the first screenful, sits clear
   of the left-aligned sector headings, and honours reduced-motion. */

/* The board-wide breadth line. Both boards show the SAME 750-name count now:
   this board's own 235 F&O names and the sector board's were two different
   answers to one question, and on 2026-10-09 they disagreed outright -- 188
   up / 46 down against 353 / 391 at the same moment. One number, and it is
   the wider one. */
function setBreadthHeader(doc){
  const el = document.getElementById('breadthTag');
  if(!el) return;
  const pts = (doc && doc.points) || [];
  if(!pts.length){ el.textContent = ''; return; }
  const [, adv, dec] = pts[pts.length - 1];
  el.textContent = `${adv} advancing · ${dec} declining of ${doc.total} (NSE 750)`;
}

/* ── Floating breadth tracker ──────────────────────────────────────────────
   Draws the intraday advance/decline series written by fetch_data.py. The
   y-axis is labelled with the day's own high and low rather than a fixed
   scale, which is what makes a flat-looking pair of lines readable: on a
   quiet day the whole range may be twenty names wide.

   Polled separately from the board. A missing or empty file is a normal
   state -- before the first append of a session there is nothing to draw --
   so it says so instead of rendering an empty chart. */
const BF_OPEN = 9 * 60 + 15;

function bfTime(mins){
  return String(Math.floor(mins / 60)).padStart(2, '0') + ':' +
         String(mins % 60).padStart(2, '0');
}

function bfChart(pts){
  const W = 252, H = 86, PADL = 30, PADR = 4, PADV = 7;
  const xs = pts.map(p => p[0]);
  const lo = Math.min(...pts.flatMap(p => [p[1], p[2]]));
  const hi = Math.max(...pts.flatMap(p => [p[1], p[2]]));
  // A single point, or a dead-flat day, would divide by zero.
  const span = (hi - lo) || 1;
  const x0 = BF_OPEN, x1 = Math.max(...xs, BF_OPEN + 1);
  const px = m => PADL + (W - PADL - PADR) * (m - x0) / (x1 - x0);
  const py = v => PADV + (H - 2 * PADV) * (1 - (v - lo) / span);
  const line = i => pts.map(p => px(p[0]).toFixed(1) + ',' + py(p[i]).toFixed(1)).join(' ');
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
    <rect x="${PADL}" y="0" width="${W - PADL - PADR}" height="${H}" fill="var(--panel-2)"/>
    <polyline points="${line(1)}" fill="none" stroke="var(--b-strong-gain)" stroke-width="1.6"
              stroke-linejoin="round" stroke-linecap="round"/>
    <polyline points="${line(2)}" fill="none" stroke="var(--b-strong-loss)" stroke-width="1.6"
              stroke-linejoin="round" stroke-linecap="round"/>
    <text x="${PADL - 4}" y="${py(hi) + 3}" text-anchor="end" font-size="9"
          font-family="IBM Plex Mono, monospace" fill="var(--text-dim)">${hi}</text>
    <text x="${PADL - 4}" y="${py(lo) + 3}" text-anchor="end" font-size="9"
          font-family="IBM Plex Mono, monospace" fill="var(--text-dim)">${lo}</text>
  </svg>`;
}

function renderBreadth(doc){
  const el = document.getElementById('breadthFloat');
  const body = document.getElementById('bfBody');
  if(!el || !body) return;
  const pts = (doc && doc.points) || [];
  el.hidden = false;
  if(!pts.length){
    body.innerHTML = `<div class="bf-empty">No readings yet today — the series starts at 09:15 IST.</div>`;
    return;
  }
  const last = pts[pts.length - 1];
  body.innerHTML = `
    <div class="bf-counts">
      <div class="bf-cell up"><div class="bf-lbl">Advancing</div><div class="bf-num">${last[1]}</div></div>
      <div class="bf-cell dn"><div class="bf-lbl">Declining</div><div class="bf-num">${last[2]}</div></div>
    </div>
    <div class="bf-chart">${bfChart(pts)}</div>
    <div class="bf-axis"><span>09:15</span><span>${bfTime(last[0])}</span></div>
    <div class="bf-note">of ${doc.total} names across NSE ranks 1–750 — wider than this board's 235, still not all of NSE</div>`;
}

function initBreadthFloat(){
  // Built from here, like the back-to-top button, so BOTH boards get the same
  // tracker and neither can drift from the other.
  const el = document.createElement('div');
  el.className = 'breadth-float';
  el.id = 'breadthFloat';
  el.innerHTML = '<div class="bf-head" id="bfHead">'
    + '<span class="bf-title">Market breadth</span>'
    + '<span class="bf-caret" id="bfCaret">&#9662;</span></div>'
    + '<div class="bf-body" id="bfBody"></div>';
  el.hidden = true;
  document.body.appendChild(el);
  const head = el.querySelector('#bfHead');
  const caret = el.querySelector('#bfCaret');
  // Remembered per viewer only; it is a convenience, never state anything
  // else depends on, so a blocked localStorage must not break the panel.
  // Starts collapsed on a phone, where expanded it would cover a third of the
  // table before the viewer has asked for it. A stored choice always wins.
  let collapsed = window.matchMedia('(max-width:560px)').matches;
  try{
    const saved = localStorage.getItem('bfCollapsed');
    if(saved !== null) collapsed = saved === '1';
  }catch(e){}
  const paint = () => {
    el.classList.toggle('collapsed', collapsed);
    if(caret) caret.textContent = collapsed ? '▸' : '▾';
  };
  head.addEventListener('click', () => {
    collapsed = !collapsed;
    try{ localStorage.setItem('bfCollapsed', collapsed ? '1' : '0'); }catch(e){}
    paint();
  });
  paint();

  async function pull(){
    try{
      // Written by the 44 EMA board's own sweep, which already holds all 750
      // prices. Same origin on Pages, so no CORS and no copy to drift.
      const r = await fetch('../nifty-ema-board/data/breadth_today.json?t=' + Date.now(), { cache: 'no-store' });
      if(!r.ok) throw new Error('HTTP ' + r.status);
      const doc = await r.json();
      renderBreadth(doc);
      setBreadthHeader(doc);
    }catch(e){
      renderBreadth(null);
      setBreadthHeader(null);
    }
  }
  pull();
  setInterval(pull, 30000);
}

function initBackToTop(showAfter = 400){
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'to-top';
  btn.setAttribute('aria-label', 'Back to top');
  btn.title = 'Back to top';
  btn.innerHTML = '<span aria-hidden="true">&#8593;</span> Top';
  document.body.appendChild(btn);

  btn.addEventListener('click', () => {
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    window.scrollTo({ top: 0, behavior: reduce ? 'auto' : 'smooth' });
  });

  let shown = null;
  function sync(){
    const show = window.scrollY > showAfter;
    if(show !== shown){
      shown = show;
      btn.classList.toggle('visible', show);
    }
  }
  sync();
  window.addEventListener('scroll', sync, { passive: true });
  window.addEventListener('resize', sync, { passive: true });

  // The board renders after its data arrives. If the browser restored a scroll
  // position on reload, that happens while the document is still short and no
  // scroll event follows - so re-check whenever the page height changes.
  if(typeof ResizeObserver !== 'undefined'){
    new ResizeObserver(sync).observe(document.body);
  }
}

/* Shown only while a name is actually trading ex a corporate action, so the
   board carries no standing caveat on the ~364 days a year when none is. */
function renderCaNote(rows){
  const el = document.getElementById('caNote');
  if(!el) return;
  const hits = (rows || []).filter(r => r && r.ca);
  if(!hits.length){ el.hidden = true; el.innerHTML = ''; return; }
  el.hidden = false;
  el.innerHTML = '<strong>Trading ex a corporate action today.</strong> '
    + hits.map(r => {
        const base = `<strong>${r.name}</strong> — ex ${r.ca.what} (${r.ca.date}), `
          + `raw print ${fmtPct(r.ca.rawPct)}`;
        return base + (r.ca.adjusted
          ? `, shown adjusted to <strong>${fmtPct(r.pct)}</strong> using the announced ratio.`
          : `, shown as <strong>NA</strong>: a demerger changes the company itself, so there`
            + ` is no like-for-like change to quote, and the name is left out of its sector average.`);
      }).join(' ')
    + ' The raw figure is an artefact of the share count or the company changing overnight, not a move. '
    + 'Large moves that are <em>not</em> a listed corporate action are never rewritten.';
}
