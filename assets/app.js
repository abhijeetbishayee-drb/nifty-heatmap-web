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

/* One stock tile: name, price, % change, day-range bar, click through to NSE. */
function tileHtml(r){
  return `
    <a class="tile ${bucket(r.pct)}" href="${nseUrl(r.ticker)}" target="_blank" rel="noopener noreferrer" title="Day range: ${fmtPrice(r.dayLow)} – ${fmtPrice(r.dayHigh)} · View on NSE">
      <div class="name">${r.name}</div>
      <div class="figures">
        <div class="price">${fmtPrice(r.price)}</div>
        <div class="pct">${fmtPct(r.pct)}</div>
      </div>
      ${dayRangeBar(r)}
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
        <span class="m-name">${r.name}</span>
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
