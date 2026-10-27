/* Builds portfolios the way app.html does, runs polaris-engine.js on them, and writes the
   engine's inputs and results to JSON for an independent check (tools/test_engine.py).
   Usage: node engine_cases.js <site folder> <out.json> [cases] */
const fs = require('fs'), path = require('path');
const SITE = path.resolve(process.argv[2] || '..'), OUT = process.argv[3] || 'engine_cases.json', NC = +(process.argv[4] || 40);
global.window = globalThis;
eval(fs.readFileSync(path.join(SITE, 'etf-data.js'), 'utf8'));
eval(fs.readFileSync(path.join(SITE, 'etf-browser-prices.js'), 'utf8'));
const E = require(path.join(SITE, 'polaris-engine.js')), I = E._internal, D = window.POLARIS_DATA;

function allocate(total, shares, minW, maxW) {   /* same as app.html */
  var keys = Object.keys(shares); if (!keys.length) return {}; var sum = keys.reduce((a, k) => a + shares[k], 0), w = {}; keys.forEach(k => w[k] = total * shares[k] / sum);
  for (var it = 0; it < 20; it++) { var fixed = {}, free = [], rest = total; keys.forEach(k => { if (w[k] < minW) fixed[k] = minW; else if (w[k] > maxW) fixed[k] = maxW; else free.push(k); }); Object.keys(fixed).forEach(k => rest -= fixed[k]); if (!Object.keys(fixed).length) break; var fs2 = free.reduce((a, k) => a + shares[k], 0); var nw = {}; Object.keys(fixed).forEach(k => nw[k] = fixed[k]); free.forEach(k => nw[k] = fs2 ? rest * shares[k] / fs2 : 0); var same = keys.every(k => Math.abs(nw[k] - w[k]) < 1e-9); w = nw; if (same) break; }
  var r = {}, acc = 0, order = keys.slice().sort((a, b) => (w[b] - Math.floor(w[b])) - (w[a] - Math.floor(w[a]))); keys.forEach(k => { r[k] = Math.floor(w[k]); acc += r[k]; }); for (var i = 0; acc < total; i++) { r[order[i % order.length]]++; acc++; } return r;
}
const SS = { none: { cas: .25, uss: .4167, ins: .25, ems: .0833 }, canada: { cas: .40, uss: .30, ins: .20, ems: .10 }, global: { cas: .10, uss: .55, ins: .25, ems: .10 } };
const BS = { none: { cab: .5, cst: .25, glb: .25 }, steady: { cab: .35, cst: .45, glb: .20 }, income: { cab: .65, cst: .10, glb: .25 } };
function selection(o) {
  const tier = o.tier, key = (tier === 'high' ? 'h' : 'lm') + '|' + (o.sus ? 1 : 0) + '|' + (o.inc ? 1 : 0) + '|' + (o.cad ? 1 : 0), picks = D.picks[key], H = [];
  const cats = ['cas', 'uss', 'ins', 'ems', 'cab', 'cst', 'glb'].filter(c => !(o.omit || []).includes(c));
  cats.forEach(c => { const id = picks[c], f = D.funds[id], g = D.cats[c].stock ? 'S' : 'B';
    H.push({ id, tk: f.tk, name: f.name, cat: c, grp: g, g0: g, mer: f.mer, cur: f.cur, ph: !!f.ph });
    const s = (o.second || {})[c]; if (s) { const x = D.funds[s]; H.push({ id: s, tk: x.tk, name: x.name, cat: c, grp: g, g0: g, mer: x.mer, cur: x.cur, ph: !!x.ph, c2: x.phcorr || null }); } });
  (o.addons || []).forEach(a => { const t = D.themes.concat(D.extras).find(x => x.id === a.id), f = D.funds[a.id] || {};
    H.push({ id: a.id, tk: t.tk, name: t.label, cat: null, grp: t.group === 'S' ? 'S' : t.group === 'B' ? 'B' : 'O', g0: t.group, fixed: a.w, mer: f.mer != null ? f.mer : t.mer, ret: t.ret, vol: t.vol, ph: !!f.ph }); });
  const band = E.config.band[tier], at = H.filter(h => h.fixed != null).reduce((a, h) => a + h.fixed, 0), as = H.filter(h => h.fixed != null && h.grp === 'S').reduce((a, h) => a + h.fixed, 0);
  const sk = {}, bk = {}; cats.forEach(c => { if (D.cats[c].stock) sk[c] = SS[o.region || 'none'][c]; else bk[c] = BS[o.bond || 'none'][c]; });
  const S = Math.min(100 - at, band[1] - as), cw = Object.assign({}, allocate(S, sk, 5, 40), allocate(100 - at - S, bk, tier === 'high' ? 0 : 5, 40));
  return { holdings: H, tier, amount: 10000, contrib: o.contrib ? { amount: o.contrib, freq: 'monthly' } : null,
    capWeights: H.map(h => h.fixed != null ? h.fixed : (cw[h.cat] || 0) / H.filter(x => x.cat === h.cat).length) };
}
let seed = 7; const R = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; }, pick = a => a[Math.floor(R() * a.length)];
const out = { opt: [], sims: [] };
for (let c = 0; c < NC; c++) {
  const tier = pick(['low', 'mod', 'high']), o = { tier, sus: R() < .25, inc: R() < .25, cad: R() < .25, region: pick(['none', 'canada', 'global']), bond: pick(['none', 'steady', 'income']) };
  const key = (tier === 'high' ? 'h' : 'lm') + '|' + (o.sus ? 1 : 0) + '|' + (o.inc ? 1 : 0) + '|' + (o.cad ? 1 : 0);
  if (R() < .4) { const cs = Object.keys(D.second).filter(k => D.second[k].length), k = pick(cs), cand = D.second[k].filter(id => id !== D.picks[key][k]); if (cand.length) o.second = { [k]: pick(cand) }; }
  if (R() < .5) { const th = D.themes.filter(t => tier === 'high' || t.tier !== 'high'); o.addons = [{ id: pick(th).id, w: pick([5, 10]) }]; if (tier !== 'low' && R() < .5) o.addons.push({ id: 'FBTC CN', w: 5 }); }
  if (R() < .15) o.omit = [pick(['cas', 'ins', 'cst', 'glb'])];
  const inp = selection(o), r = E.run(inp), model = I.buildModel(inp.holdings), K = I.buildConstraints(inp.holdings, tier, []);
  out.opt.push({ tier, mu: model.mu, cov: model.cov, A: K.A, l: K.l, u: K.u, free: K.free, fixed: inp.holdings.map(h => h.fixed != null ? h.fixed / 100 : 0), cap: r.volCap.value,
    minvar: r.stops[0].weights.map(w => w.exact / 100), maxret: r.stops[r.stops.length - 1].weights.map(w => w.exact / 100),
    stops: r.stops.map(s => s.weights.map(w => w.exact / 100)), rounded: r.stops.map(s => s.weights.map(w => w.w)), ms: r.runtimeMs });
}
[['mod', {}], ['high', {}], ['low', { contrib: 200 }]].forEach(([tier, x]) => {
  const inp = selection(Object.assign({ tier }, x)), r = E.run(inp);
  out.sims.push({ tier, amount: inp.amount, contrib: inp.contrib, ids: inp.holdings.map(h => h.id), hist: r.history, blockWeeks: E.config.blockWeeks,
    sc: Object.fromEntries([['minvar', 0], ['middle', r.start], ['maxret', r.stops.length - 1]].map(([k, i]) => { const s = r.stops[i]; return [k, { w: s.weights.map(x => x.w / 100), ret: s.stats.ret, vol: s.stats.vol, h: Object.fromEntries(['mc', 'boot', 'hybrid'].map(m => [m, E.sims(i, m).horizons])) }]; })) });
});
/* What if: revaluing with new amounts must equal a full re-run with those amounts */
(function () {
  const base = selection({ tier: 'mod', contrib: 200, second: { uss: 'XSU CN' }, addons: [{ id: 'ZRE CN', w: 5 }, { id: 'FBTC CN', w: 5 }] });
  const gap = (a, b) => { let g = 0; for (let y = 0; y <= 20; y++) for (const q of ['p5', 'p25', 'p50', 'p75', 'p95', 'put']) g = Math.max(g, Math.abs(a.years[y][q] - b.years[y][q]) / Math.max(1, Math.abs(b.years[y][q]))); return g; };
  const r0 = E.run(base); let same = 0, changed = 0, doubled = 0;
  const ks = [0, 3, 5, 10];
  ks.forEach(k => ['mc', 'boot', 'hybrid'].forEach(m => { same = Math.max(same, gap(E.whatIf({ stop: k, method: m, start: base.amount, contrib: base.contrib }), E.sims(k, m))); }));
  [{ start: 25000, contrib: { amount: 750, freq: 'monthly' }, lumps: [{ amount: 5000, month: 36 }, { amount: 20000, month: 0 }] }, { start: 3000, contrib: { amount: 1000, freq: 'semiannual' }, lumps: [{ amount: 12000, month: 120 }] }, { start: 10000, contrib: null, lumps: [] }].forEach(c => {
    const full = E.run(Object.assign({}, base, { amount: c.start, contrib: c.contrib, lumps: c.lumps }));
    const fullSims = {}; ks.forEach(k => ['mc', 'boot', 'hybrid'].forEach(m => { fullSims[k + m] = E.sims(k, m); }));
    E.run(base);
    ks.forEach(k => ['mc', 'boot', 'hybrid'].forEach(m => {
      const a = E.whatIf({ stop: k, method: m, start: c.start, contrib: c.contrib, lumps: c.lumps }); changed = Math.max(changed, gap(a, fullSims[k + m]));
      const d = E.whatIf({ stop: k, method: m, start: 2 * c.start, contrib: c.contrib && { amount: 2 * c.contrib.amount, freq: c.contrib.freq }, lumps: c.lumps.map(x => ({ amount: 2 * x.amount, month: x.month })) });
      for (let y = 0; y <= 20; y++) doubled = Math.max(doubled, Math.abs(d.years[y].p50 - 2 * a.years[y].p50) / Math.max(1, a.years[y].p50));
    }));
  });
  out.whatif = { same, changed, doubled };
})();
/* Stress test: the crash year should land on the mix's weighted fall, and the crash should lower later outcomes */
out.stress = [['mod', {}], ['high', { addons: [{ id: 'ZRE CN', w: 5 }, { id: 'CGL CN', w: 5 }, { id: 'FBTC CN', w: 5 }, { id: 'XEG CN', w: 5 }] }], ['low', { contrib: 300 }]].map(([tier, x]) => {
  const inp = selection(Object.assign({ tier }, x)); E.run(inp);
  return [0, 5, 10].map(k => { const st = E.stress(k), nm = E.sims(k, st.method);
    return { tier, stop: k, loss: st.loss, yr1: st.sim.oneYear.median, p50: st.sim.horizons[20].p50, p50n: nm.horizons[20].p50, rec: st.recovery.median }; });
}).flat();
fs.writeFileSync(OUT, JSON.stringify(out));
console.log('wrote', OUT, out.opt.length, 'optimizer cases,', out.sims.length, 'simulation cases; average run', (out.opt.reduce((a, b) => a + b.ms, 0) / out.opt.length).toFixed(0), 'ms');
