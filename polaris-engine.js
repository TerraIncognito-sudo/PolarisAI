/* =====================================================================
   PolarisAI Optimizer and Simulation Engine            polaris-engine.js
   ---------------------------------------------------------------------
   The quantitative core of the Portfolio Builder (step 5).

   Given the client's ETF selection and risk tier it
     1. builds expected returns and a covariance matrix from the fund data
        (etf-data.js: assumptions per category, volatility and correlation
        from about three years of weekly prices),
     2. optimizes the weights along a risk slider of 11 stops:
          - stop 0, Minimum Variance: the lowest-volatility mix
          - stop 10, Maximum Return:  the highest expected return whose volatility
                                      stays at or below the risk tier's cap
          - stops 1-9: evenly spaced volatility targets in between, each with the
                       highest expected return there, smoothed so fund weights
                       change gradually from stop to stop
        Both respect: 5-40% per core category, the tier's Stock ETF band,
        fixed satellite weights, and a minimum for each fund when a
        category is split between two funds,
     3. projects a stop forward with three simulation methods:
          - Monte Carlo: normal weekly returns from the assumed mean and the
                         covariance (lognormal growth)
          - Bootstrap:   replays real weekly returns in random blocks
                         (stationary block bootstrap), so it keeps fat tails,
                         streaks and co-movement, and the last 3 years' means
          - Hybrid:      the bootstrap's real weekly shocks, re-centred on the
                         forward-looking assumed returns
     4. publishes everything to the shared results state:
          window.PolarisResults, plus a 'polaris:results' event on window.
     5. answers "what if I put in more or less?" exactly and instantly with
        PolarisEngine.whatIf(), from each simulated path's monthly growth
        (published as PolarisResults.whatIf, plus a 'polaris:whatif' event).

   Inputs come only from the generated data files (built from the team's
   fund databases by tools/build_etf_data.py):
     window.POLARIS_DATA    etf-data.js            funds, vol, corr, assumptions
     window.POLARIS_PRICES  etf-browser-prices.js  weekly returns (basis points)
   The engine loads etf-browser-prices.js itself when it is needed.

   No dependencies. Runs in the browser and in Node (for tests).
   ===================================================================== */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(root);
  else root.PolarisEngine = factory(root);
})(typeof window !== 'undefined' ? window : globalThis, function (root) {
  'use strict';

  /* ---------- Settings (edit here; documented in tools/UPDATING.md) ---------- */
  var CFG = {
    version: '1.0',
    paths: 2000,              // simulated futures per stop and method
    seed: 20261027,           // fixed seed: same inputs always give the same results
    weeksPerYear: 52,
    maxYears: 20,             // simulate 20 years once; 5- and 10-year views are snapshots of the same paths
    blockWeeks: 6,            // mean block length (weeks) for the stationary bootstrap
    catMin: 5, catMax: 40,    // % of the portfolio in each core category
    catMaxBy: { ems: 15 },    // tighter limits for some categories: emerging markets swing more, so this slice stays small
    pairMin: 3,               // % minimum for each fund when a category has two funds
    band: { low: [20, 40], mod: [50, 70], high: [75, 95] },   // Stock ETF share (incl. stock satellites)
    fallbackCap: { low: 7, mod: 11, high: 15.5 },            // vol cap (%) if the app passes no reference mix
    headline: 'hybrid',       // the method shown on screen; the report compares all three
    stops: 11,                // risk slider: stop 0 = Minimum Variance ... stop 10 = Maximum Return
    startStop: 5,             // where the slider starts (the middle)
    smooth: 4,                // pull of each stop toward the straight blend of the two ends, in units of the
                              // funds' average variance: keeps fund weights changing gradually along the slider
    betaVs: [{ k: 'tsx', id: 'XIC CN', label: 'Canadian stock market (S&P/TSX Composite, via XIC)' }, { k: 'world', id: 'ACWI US', label: 'world stock market (MSCI ACWI, via ACWI, in US dollars)' }],
    /* Stress test (report only): a crash in the first 12 months, by asset class, anchored on past market
       falls. After the crash, markets behave as in the Hybrid method (no extra rebound is assumed). */
    stress: {
      months: 12,
      classes: [
        { k: 'equity', label: 'Equity', shock: -40, anchor: '2008 Global Financial Crisis' },
        { k: 'bond', label: 'Bond', shock: -15, anchor: '2022 rate-hike bond selloff' },
        { k: 'realestate', label: 'Real estate', shock: -35, anchor: '2008 REIT collapse' },
        { k: 'commodity', label: 'Commodity', shock: -50, anchor: 'Oil crash 2020 / broad commodity bear market' },
        { k: 'crypto', label: 'Crypto', shock: -75, anchor: '2022 bitcoin bear market' }
      ],
      /* satellites by fund: real estate, gold and energy/resources follow their own class; bitcoin funds are crypto.
         Keys are fund ids in etf-data.js ('PH:' ids are placeholders not yet in the database). No leveraged funds are offered. */
      byFund: { 'ZRE CN': 'realestate', 'CGL CN': 'commodity', 'XEG CN': 'commodity', 'PH:XEG': 'commodity', 'FBTC CN': 'crypto', 'BTCC/B CN': 'crypto' },
      leverage: {}
    },
    riskFree: { rate: 2.50, asOf: '2026-10-22', label: '3-month Government of Canada treasury bill' },  // for the Sharpe ratio
    pricesUrl: 'etf-browser-prices.js'
  };
  var METHODS = [
    { k: 'mc', name: 'Monte Carlo', short: 'Monte Carlo' },
    { k: 'boot', name: 'Bootstrap', short: 'Bootstrap' },
    { k: 'hybrid', name: 'Hybrid', short: 'Hybrid' }
  ];
  /* Correlation used when the database has no pair (placeholders): by asset group.
     S stocks, B bonds, G gold, C crypto. Same as the builder's earlier rule. */
  var GROUP_CORR = { SS: 0.8, BB: 0.7, BS: 0.1, GS: 0.1, BG: 0.2, GG: 1, CS: 0.3, BC: 0, CG: 0.1, CC: 1 };

  function D() { return root.POLARIS_DATA; }

  /* ===================================================================
     Small linear-algebra helpers (dense, n is small: at most ~20 funds)
     =================================================================== */
  function zeros(n) { var a = new Array(n); for (var i = 0; i < n; i++) a[i] = 0; return a; }
  function mat(n, m) { var a = new Array(n); for (var i = 0; i < n; i++) a[i] = zeros(m); return a; }
  function dot(a, b) { var s = 0; for (var i = 0; i < a.length; i++) s += a[i] * b[i]; return s; }
  function mv(M, x) { var n = M.length, r = zeros(n); for (var i = 0; i < n; i++) r[i] = dot(M[i], x); return r; }
  function mtv(M, y, n) { var r = zeros(n); for (var i = 0; i < M.length; i++) for (var j = 0; j < n; j++) r[j] += M[i][j] * y[i]; return r; }
  function infn(a) { var s = 0; for (var i = 0; i < a.length; i++) s = Math.max(s, Math.abs(a[i])); return s; }
  function cholesky(K) {
    var n = K.length, L = mat(n, n);
    for (var i = 0; i < n; i++) for (var j = 0; j <= i; j++) {
      var s = K[i][j]; for (var k = 0; k < j; k++) s -= L[i][k] * L[j][k];
      if (i === j) { if (s <= 0) s = 1e-14; L[i][i] = Math.sqrt(s); } else L[i][j] = s / L[j][j];
    }
    return L;
  }
  function cholSolve(L, b) {
    var n = L.length, y = zeros(n), x = zeros(n), i, k;
    for (i = 0; i < n; i++) { var s = b[i]; for (k = 0; k < i; k++) s -= L[i][k] * y[k]; y[i] = s / L[i][i]; }
    for (i = n - 1; i >= 0; i--) { var t = y[i]; for (k = i + 1; k < n; k++) t -= L[k][i] * x[k]; x[i] = t / L[i][i]; }
    return x;
  }
  /* Gaussian elimination with partial pivoting (for the small KKT systems in polishing) */
  function gaussSolve(M, b) {
    var n = b.length, A = M.map(function (r) { return r.slice(); }), x = b.slice(), i, j, k;
    for (k = 0; k < n; k++) {
      var p = k, mx = Math.abs(A[k][k]);
      for (i = k + 1; i < n; i++) if (Math.abs(A[i][k]) > mx) { mx = Math.abs(A[i][k]); p = i; }
      if (mx < 1e-18) return null;
      if (p !== k) { var t = A[p]; A[p] = A[k]; A[k] = t; var tb = x[p]; x[p] = x[k]; x[k] = tb; }
      for (i = k + 1; i < n; i++) { var f = A[i][k] / A[k][k]; if (!f) continue; for (j = k; j < n; j++) A[i][j] -= f * A[k][j]; x[i] -= f * x[k]; }
    }
    for (i = n - 1; i >= 0; i--) { var s = x[i]; for (j = i + 1; j < n; j++) s -= A[i][j] * x[j]; x[i] = s / A[i][i]; }
    return x;
  }

  /* ===================================================================
     Convex QP solver:  minimize 1/2 x'Px + q'x  subject to  l <= Ax <= u
     ADMM (the OSQP scheme) with step-size adaptation, then "polishing":
     the constraints found active are solved exactly as equalities, so the
     weights come out exact rather than approximately optimal.
     The factorization does not depend on q, so one solver object handles
     the whole efficient frontier (only q changes), warm-started.
     =================================================================== */
  function QPSolver(P, A, l, u) {
    this.P = P; this.A = A; this.l = l; this.u = u;
    this.n = P.length; this.m = A.length;
    this.sigma = 1e-6; this.alpha = 1.6; this.rho0 = 0.1;
    this.eq = l.map(function (lv, i) { return Math.abs(u[i] - lv) < 1e-12; });
    this.setRho(this.rho0);
    this.x = zeros(this.n); this.z = zeros(this.m); this.y = zeros(this.m);
  }
  QPSolver.prototype.setRho = function (rho) {
    var n = this.n, m = this.m, A = this.A, eq = this.eq;
    this.rho = rho;
    this.rv = eq.map(function (e) { return e ? 1e3 * rho : rho; });
    var K = mat(n, n), i, j, k;
    for (i = 0; i < n; i++) for (j = 0; j < n; j++) K[i][j] = this.P[i][j] + (i === j ? this.sigma : 0);
    for (k = 0; k < m; k++) { var r = this.rv[k], a = A[k]; for (i = 0; i < n; i++) if (a[i]) for (j = 0; j < n; j++) if (a[j]) K[i][j] += r * a[i] * a[j]; }
    this.L = cholesky(K);
  };
  QPSolver.prototype.solve = function (q, opts) {
    opts = opts || {};
    var n = this.n, m = this.m, A = this.A, P = this.P, l = this.l, u = this.u;
    var x = this.x, z = this.z, y = this.y, a = this.alpha, sg = this.sigma;
    var epsA = opts.eps || 1e-10, epsR = opts.epsRel || 1e-9, maxIt = opts.maxIter || 40000, it, i;
    var rp = 1, rd = 1;
    for (it = 1; it <= maxIt; it++) {
      var rv = this.rv, w = zeros(m);
      for (i = 0; i < m; i++) w[i] = rv[i] * z[i] - y[i];
      var rhs = mtv(A, w, n); for (i = 0; i < n; i++) rhs[i] += sg * x[i] - q[i];
      var xt = cholSolve(this.L, rhs), zt = mv(A, xt), xn = zeros(n), zn = zeros(m);
      for (i = 0; i < n; i++) xn[i] = a * xt[i] + (1 - a) * x[i];
      for (i = 0; i < m; i++) {
        var zr = a * zt[i] + (1 - a) * z[i], v = zr + y[i] / rv[i];
        zn[i] = v < l[i] ? l[i] : v > u[i] ? u[i] : v;
        y[i] += rv[i] * (zr - zn[i]);
      }
      x = xn; z = zn;
      if (it % 20 === 0) {
        var Ax = mv(A, x), Px = mv(P, x), Aty = mtv(A, y, n), pr = zeros(m), du = zeros(n);
        for (i = 0; i < m; i++) pr[i] = Ax[i] - z[i];
        for (i = 0; i < n; i++) du[i] = Px[i] + q[i] + Aty[i];
        rp = infn(pr); rd = infn(du);
        var sp = Math.max(infn(Ax), infn(z)), sd = Math.max(infn(Px), infn(Aty), infn(q));
        if (rp <= epsA + epsR * sp && rd <= epsA + epsR * sd) break;
        if (it % 200 === 0) {
          var ratio = Math.sqrt((rp / (sp + 1e-30)) / (rd / (sd + 1e-30) + 1e-30));
          if (isFinite(ratio) && (ratio > 5 || ratio < 0.2)) { this.setRho(Math.min(1e6, Math.max(1e-6, this.rho * ratio))); }
        }
      }
    }
    this.x = x; this.z = z; this.y = y;
    var res = { x: x.slice(), iters: it, rp: rp, rd: rd, polished: false };
    var pol = this.polish(q, x, z, y);
    if (pol) { res.x = pol; res.polished = true; }
    return res;
  };
  QPSolver.prototype.obj = function (q, x) { return 0.5 * dot(x, mv(this.P, x)) + dot(q, x); };
  QPSolver.prototype.feasible = function (x, tol) {
    var Ax = mv(this.A, x);
    for (var i = 0; i < this.m; i++) if (Ax[i] < this.l[i] - tol || Ax[i] > this.u[i] + tol) return false;
    return true;
  };
  QPSolver.prototype.polish = function (q, x, z, y) {
    var n = this.n, m = this.m, A = this.A, P = this.P, l = this.l, u = this.u, rows = [], vals = [], i, j;
    for (i = 0; i < m; i++) {
      var tol = 1e-7 * Math.max(1, Math.abs(z[i]));
      if (this.eq[i]) { rows.push(i); vals.push(l[i]); }
      else if (z[i] - l[i] < tol && y[i] < 1e-12) { rows.push(i); vals.push(l[i]); }
      else if (u[i] - z[i] < tol && y[i] > -1e-12) { rows.push(i); vals.push(u[i]); }
    }
    var k = rows.length, N = n + k, dlt = 1e-11, K = mat(N, N), b = zeros(N);
    for (i = 0; i < n; i++) { for (j = 0; j < n; j++) K[i][j] = P[i][j]; K[i][i] += dlt; b[i] = -q[i]; }
    for (var r = 0; r < k; r++) { var ar = A[rows[r]]; for (j = 0; j < n; j++) { K[n + r][j] = ar[j]; K[j][n + r] = ar[j]; } K[n + r][n + r] = -dlt; b[n + r] = vals[r]; }
    var s = gaussSolve(K, b); if (!s) return null;
    /* two steps of iterative refinement against the unregularized system */
    for (var ref = 0; ref < 2; ref++) {
      var res = zeros(N);
      for (i = 0; i < N; i++) { var t = b[i]; for (j = 0; j < N; j++) { var kij = K[i][j]; if (i === j) kij += i < n ? -dlt : dlt; t -= kij * s[j]; } res[i] = t; }
      var ds = gaussSolve(K, res); if (!ds) break; for (i = 0; i < N; i++) s[i] += ds[i];
    }
    var xp = s.slice(0, n);
    if (!this.feasible(xp, 1e-9)) return null;
    /* the active set must also be optimal: the polished point may not be worse than ADMM's */
    if (this.obj(q, xp) > this.obj(q, x) + 1e-10 * Math.max(1, Math.abs(this.obj(q, x)))) return null;
    return xp;
  };

  /* ===================================================================
     Seeded random numbers (mulberry32) and normal draws (Box-Muller)
     =================================================================== */
  function rng(seed) {
    var s = seed >>> 0;
    return function () { s = (s + 0x6D2B79F5) | 0; var t = Math.imul(s ^ (s >>> 15), 1 | s); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  }
  function normalGen(R) {
    var spare = null;
    return function () {
      if (spare !== null) { var t = spare; spare = null; return t; }
      var u1 = R() || 1e-12, u2 = R(), r = Math.sqrt(-2 * Math.log(u1));
      spare = r * Math.sin(2 * Math.PI * u2); return r * Math.cos(2 * Math.PI * u2);
    };
  }
  function hashStr(s) { var h = 2166136261; for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }

  /* ===================================================================
     Model: expected returns and covariance for the selected holdings
     holding = { id, tk, name, cat (core category key, or null for a
       satellite), grp ('S' | 'B' | 'O' for the stock / bond / alternatives
       totals), g0 ('S','B','G','C' asset group for fallback correlation),
       fixed (percent, satellites only), mer, ret, vol, c2 (estimated
       correlation for a placeholder second fund), ph, cur }
     =================================================================== */
  function buildModel(holdings) {
    var d = D(), n = holdings.length, mu = zeros(n), vol = zeros(n), C = mat(n, n), src = [], i, j;
    holdings.forEach(function (h, i) {
      var r = d.funds[h.id] || {};
      var ret = h.cat ? d.assume.ret[h.cat] : (h.ret != null ? h.ret : 6);
      mu[i] = (ret - (h.mer != null ? h.mer : r.mer || 0)) / 100;              // after fees
      var v = (r.vol != null && !r.ph) ? r.vol : (h.vol != null ? h.vol : (h.cat ? d.assume.fallback_vol[h.cat] : 15) || 15);
      vol[i] = v / 100;
      src.push((r.vol != null && !r.ph) ? 'prices' : 'assumed');
    });
    for (i = 0; i < n; i++) for (j = 0; j < n; j++) C[i][j] = i === j ? 1 : corrPair(holdings[i], holdings[j]);
    var S = mat(n, n);
    for (i = 0; i < n; i++) for (j = 0; j < n; j++) S[i][j] = vol[i] * vol[j] * C[i][j];
    nearestPD(S);
    return { mu: mu, vol: vol, corr: C, cov: S, volSource: src };
  }
  function corrPair(a, b) {
    var d = D();
    if (a.id === b.id) return 1;
    var key = a.id < b.id ? a.id + '|' + b.id : b.id + '|' + a.id;
    if (d.corr[key] != null) return d.corr[key];
    if (a.cat && a.cat === b.cat) return a.c2 || b.c2 || 0.9;
    var g = [a.g0 || a.grp, b.g0 || b.grp].sort().join('');
    return GROUP_CORR[g] != null ? GROUP_CORR[g] : 0;
  }
  /* Fallback correlations can make the matrix slightly non-positive-definite.
     Fix by eigen-clipping (Jacobi), which leaves a valid matrix unchanged. */
  function nearestPD(S) {
    var n = S.length, A = S.map(function (r) { return r.slice(); }), V = mat(n, n), i, j, k, p, q;
    for (i = 0; i < n; i++) V[i][i] = 1;
    for (var sweep = 0; sweep < 60; sweep++) {
      var off = 0; for (i = 0; i < n; i++) for (j = i + 1; j < n; j++) off += A[i][j] * A[i][j];
      if (off < 1e-22) break;
      for (p = 0; p < n; p++) for (q = p + 1; q < n; q++) {
        if (Math.abs(A[p][q]) < 1e-15) continue;
        var th = (A[q][q] - A[p][p]) / (2 * A[p][q]), t = (th >= 0 ? 1 : -1) / (Math.abs(th) + Math.sqrt(th * th + 1)), c = 1 / Math.sqrt(t * t + 1), s = t * c;
        for (k = 0; k < n; k++) { var akp = A[k][p], akq = A[k][q]; A[k][p] = c * akp - s * akq; A[k][q] = s * akp + c * akq; }
        for (k = 0; k < n; k++) { var apk = A[p][k], aqk = A[q][k]; A[p][k] = c * apk - s * aqk; A[q][k] = s * apk + c * aqk; }
        for (k = 0; k < n; k++) { var vkp = V[k][p], vkq = V[k][q]; V[k][p] = c * vkp - s * vkq; V[k][q] = s * vkp + c * vkq; }
      }
    }
    var ev = [], minEv = Infinity; for (i = 0; i < n; i++) { ev.push(A[i][i]); minEv = Math.min(minEv, A[i][i]); }
    if (minEv > 1e-10) return false;
    for (i = 0; i < n; i++) ev[i] = Math.max(ev[i], 1e-8);
    for (i = 0; i < n; i++) for (j = 0; j < n; j++) { var s2 = 0; for (k = 0; k < n; k++) s2 += V[i][k] * ev[k] * V[j][k]; S[i][j] = s2; }
    return true;
  }
  function portStats(model, w) {
    var r = dot(w, model.mu), v = dot(w, mv(model.cov, w));
    return { ret: r * 100, vol: Math.sqrt(Math.max(v, 0)) * 100 };
  }

  /* ===================================================================
     Constraints: build l <= Aw <= u over the free (core) funds
     =================================================================== */
  function buildConstraints(holdings, tier, notes) {
    var band = CFG.band[tier] || CFG.band.mod, free = [], fixedW = 0, fixedS = 0, fixedB = 0;
    holdings.forEach(function (h, i) {
      if (h.fixed != null) { fixedW += h.fixed; if (h.grp === 'B') fixedB += h.fixed; else fixedS += h.fixed; }   /* DEMO: gold, crypto and other non-bond satellites count toward the Stock ETF band */
      else free.push(i);
    });
    var n = free.length, cats = {}, order = [];
    free.forEach(function (hi, j) { var c = holdings[hi].cat; if (!cats[c]) { cats[c] = []; order.push(c); } cats[c].push(j); });
    var stockCats = order.filter(function (c) { return D().cats[c].stock; }), bondCats = order.filter(function (c) { return !D().cats[c].stock; });
    var coreTot = 100 - fixedW;
    /* per-category bounds. High tier: bond categories may go to 0% (as before), so a 95% stock mix is reachable */
    var cmin = {}, cmax = {};
    order.forEach(function (c) { cmin[c] = CFG.catMin; cmax[c] = CFG.catMaxBy[c] != null ? CFG.catMaxBy[c] : CFG.catMax; });
    if (tier === 'high') bondCats.forEach(function (c) { cmin[c] = 0; });
    order.forEach(function (c) { if (cats[c].length > 1) cmin[c] = Math.max(cmin[c], CFG.pairMin * cats[c].length); });
    var sum = function (list, f) { return list.reduce(function (a, c) { return a + f(c); }, 0); };
    /* Stock ETF share (core part) must sit in the band, after stock satellites */
    var sLo = band[0] - fixedS, sHi = band[1] - fixedS;
    function range() {
      var smin = sum(stockCats, function (c) { return cmin[c]; }), smax = sum(stockCats, function (c) { return cmax[c]; });
      var bmin = sum(bondCats, function (c) { return cmin[c]; }), bmax = sum(bondCats, function (c) { return cmax[c]; });
      return [Math.max(sLo, smin, coreTot - bmax), Math.min(sHi, smax, coreTot - bmin)];
    }
    var rg = range();
    if (rg[0] > rg[1] + 1e-9) {           /* relax step 1: category minimums */
      [stockCats, bondCats].forEach(function (g) { g.forEach(function (c) { cmin[c] = cats[c].length > 1 ? CFG.pairMin * cats[c].length : 0; }); });
      rg = range(); notes.push('Category minimums were relaxed so the mix could fit your risk level.');
    }
    if (rg[0] > rg[1] + 1e-9) {           /* relax step 2: category maximums (very few categories left) */
      order.forEach(function (c) { cmax[c] = 100; }); rg = range();
      notes.push('With so few categories, the 40% limit per category was lifted.');
    }
    if (rg[0] > rg[1] + 1e-9) {           /* relax step 3: band (should not happen with the builder's safeguards) */
      sLo = -1e9; sHi = 1e9; rg = range(); notes.push('Your selection could not fit the Stock ETF range for your risk level, so the range was not enforced.');
    }
    var A = [], l = [], u = [], names = [];
    function row(coef, lo, hi, name) { A.push(coef); l.push(lo / 100); u.push(hi / 100); names.push(name); }
    row(free.map(function () { return 1; }), coreTot, coreTot, 'budget');
    order.forEach(function (c) { row(free.map(function (hi, j) { return cats[c].indexOf(j) >= 0 ? 1 : 0; }), cmin[c], cmax[c], 'cat:' + c); });
    free.forEach(function (hi, j) {
      var h = holdings[hi], lo = cats[h.cat].length > 1 ? CFG.pairMin : 0;
      row(free.map(function (_, k) { return k === j ? 1 : 0; }), lo, cmax[h.cat], 'fund:' + h.tk);
    });
    if (stockCats.length && bondCats.length) row(free.map(function (hi) { return D().cats[holdings[hi].cat].stock ? 1 : 0; }), rg[0], rg[1], 'stocks');
    return { A: A, l: l, u: u, names: names, free: free, fixedW: fixedW, fixedS: fixedS, fixedB: fixedB, cats: cats, order: order, cmin: cmin, cmax: cmax, stockRange: rg, band: band };
  }

  /* ===================================================================
     Optimizer: Minimum Variance, Maximum Return (with vol cap), frontier
     =================================================================== */
  function optimize(holdings, model, tier, volCap, notes) {
    var K = buildConstraints(holdings, tier, notes), free = K.free, n = free.length, N = holdings.length;
    var fixedVec = zeros(N); holdings.forEach(function (h, i) { if (h.fixed != null) fixedVec[i] = h.fixed / 100; });
    var Pf = mat(n, n), cross = zeros(n), muF = zeros(n), i, j;
    for (i = 0; i < n; i++) {
      muF[i] = model.mu[free[i]];
      for (j = 0; j < n; j++) Pf[i][j] = model.cov[free[i]][free[j]] + (i === j ? 1e-9 : 0);
      for (j = 0; j < N; j++) cross[i] += model.cov[free[i]][j] * fixedVec[j];
    }
    var solver = new QPSolver(Pf, K.A, K.l, K.u), solves = 0;
    function full(wf) { var w = fixedVec.slice(); for (var k = 0; k < n; k++) w[free[k]] = Math.max(0, wf[k]); return w; }
    function at(lam) {
      var q = zeros(n); for (var k = 0; k < n; k++) q[k] = cross[k] - lam * muF[k];
      var r = solver.solve(q); solves++;
      var w = full(r.x); return { lam: lam, w: w, st: portStats(model, w), polished: r.polished };
    }
    var minv = at(0);
    /* The frontier: lambda trades return against variance; large lambda = the return-maximizing corner */
    var LMAX = 60, lams = [0];
    for (i = 0; i <= 28; i++) lams.push(0.004 * Math.pow(LMAX / 0.004, i / 28));
    var frontier = lams.map(function (lm) { var p = at(lm); return { lam: lm, ret: p.st.ret, vol: p.st.vol, w: p.w }; });
    var top = frontier[frontier.length - 1];
    var cap = Math.max(volCap, minv.st.vol);
    var maxr;
    if (top.vol <= cap + 1e-9) { maxr = at(LMAX); maxr.capBinding = false; }
    else {
      var lo = 0, hi = LMAX, best = minv;
      for (var it = 0; it < 60; it++) {
        var mid = 0.5 * (lo + hi), p = at(mid);
        if (p.st.vol <= cap) { lo = mid; best = p; } else hi = mid;
        if (hi - lo < 1e-7) break;
      }
      maxr = best; maxr.capBinding = true;
    }
    return { K: K, minvar: minv, maxret: maxr, frontier: frontier, cap: cap, solves: solves };
  }

  /* The risk slider: 11 stops from Minimum Variance (stop 0) to Maximum Return (stop 10).
     Stop i targets the volatility i/10 of the way between the two ends and takes the highest
     expected return there, while being pulled toward the straight blend of the two ends' weights
     (a small penalty gamma x |w - blend|^2). Without the pull, mean-variance weights can swap
     between near-identical funds from one stop to the next; with it they change gradually, at a
     cost of a few hundredths of a percent of expected return. Both ends stay exact. */
  function buildStops(holdings, model, tier, opt) {
    var K = opt.K, free = K.free, n = free.length, N = holdings.length, NS = CFG.stops, i, j;
    var fixedVec = zeros(N); holdings.forEach(function (h, k) { if (h.fixed != null) fixedVec[k] = h.fixed / 100; });
    var avgVar = 0; for (i = 0; i < n; i++) avgVar += model.cov[free[i]][free[i]]; avgVar /= Math.max(1, n);
    var gamma = CFG.smooth * avgVar, P = mat(n, n), cross = zeros(n), muF = zeros(n);
    for (i = 0; i < n; i++) {
      muF[i] = model.mu[free[i]];
      for (j = 0; j < n; j++) P[i][j] = model.cov[free[i]][free[j]] + (i === j ? 1e-9 + gamma : 0);
      for (j = 0; j < N; j++) cross[i] += model.cov[free[i]][j] * fixedVec[j];
    }
    var solver = new QPSolver(P, K.A, K.l, K.u), solves = 0;
    var w0 = free.map(function (k) { return opt.minvar.w[k]; }), w1 = free.map(function (k) { return opt.maxret.w[k]; });
    var v0 = opt.minvar.st.vol, v1 = opt.maxret.st.vol, stops = [];
    /* DEMO: the recommended (middle) stop has its Stock ETF share pinned to the middle of the
       risk level's range (Low 30%, Moderate 60%, High 85%), matching the step 1 starting mix.
       Within that split it still takes the highest expected return for its level of ups and downs. */
    var midStop = Math.min(CFG.startStop, NS - 1), si = K.names.indexOf('stocks'), pinSolver = null;
    if (si >= 0 && K.band) {
      var pin = (K.band[0] + K.band[1]) / 2 - K.fixedS;
      pin = Math.min(Math.max(pin, K.stockRange[0]), K.stockRange[1]);
      var l2 = K.l.slice(), u2 = K.u.slice(); l2[si] = u2[si] = pin / 100;
      pinSolver = new QPSolver(P, K.A, l2, u2);
    }
    function full(x) { var w = fixedVec.slice(); for (var k = 0; k < n; k++) w[free[k]] = Math.max(0, x[k]); return w; }
    for (var s = 0; s < NS; s++) {
      var f = s / (NS - 1), target = v0 + (v1 - v0) * f, best;
      if (s === 0) best = { w: opt.minvar.w, st: opt.minvar.st };
      else if (s === NS - 1) best = { w: opt.maxret.w, st: opt.maxret.st };
      else {
        var ref = w0.map(function (v, k) { return v + (w1[k] - v) * f; });
        var sv = (s === midStop && pinSolver) ? pinSolver : solver;
        var at = function (lam) { var q = zeros(n); for (var k = 0; k < n; k++) q[k] = cross[k] - lam * muF[k] - gamma * ref[k]; var r = sv.solve(q); solves++; var w = full(r.x); return { w: w, st: portStats(model, w) }; };
        var lo = 0, hi = 60, b = at(0);
        if (b.st.vol > target + 1e-9) best = b;
        else {
          var top = at(hi);
          if (top.st.vol <= target) best = top;
          else { for (var it = 0; it < 60 && hi - lo > 1e-7; it++) { var mid = 0.5 * (lo + hi), p = at(mid); if (p.st.vol <= target) { lo = mid; b = p; } else hi = mid; } best = b; }
        }
      }
      stops.push({ i: s, target: target, w: best.w, st: best.st });
    }
    return { stops: stops, gamma: gamma, solves: solves };
  }

  /* Whole-percent weights for display, keeping every limit:
     stock total -> categories -> funds, each by largest remainder */
  function lr(vals, total) {
    var fl = vals.map(Math.floor), acc = fl.reduce(function (a, b) { return a + b; }, 0);
    var order = vals.map(function (v, i) { return i; }).sort(function (a, b) { return (vals[b] - fl[b]) - (vals[a] - fl[a]); });
    for (var k = 0; acc < total && k < order.length * 3; k++) { fl[order[k % order.length]]++; acc++; }
    return fl;
  }
  function roundWeights(holdings, w, K) {
    var pct = w.map(function (x) { return x * 100; }), out = zeros(holdings.length);
    holdings.forEach(function (h, i) { if (h.fixed != null) out[i] = h.fixed; });
    var coreTot = 100 - K.fixedW, d = D();
    var stockCats = K.order.filter(function (c) { return d.cats[c].stock; }), bondCats = K.order.filter(function (c) { return !d.cats[c].stock; });
    var catVal = function (c) { return K.cats[c].reduce(function (a, j) { return a + pct[K.free[j]]; }, 0); };
    var sExact = stockCats.reduce(function (a, c) { return a + catVal(c); }, 0);
    var sTot = Math.round(sExact); if (bondCats.length === 0) sTot = coreTot; if (stockCats.length === 0) sTot = 0;
    sTot = Math.min(Math.max(sTot, Math.ceil(K.stockRange[0] - 1e-9)), Math.floor(K.stockRange[1] + 1e-9));
    [[stockCats, sTot], [bondCats, coreTot - sTot]].forEach(function (g) {
      if (!g[0].length) return;
      var cv = g[0].map(catVal), sc = cv.reduce(function (a, b) { return a + b; }, 0);
      var scaled = cv.map(function (v) { return sc ? v * g[1] / sc : g[1] / cv.length; });
      var ci = lr(scaled, g[1]);
      g[0].forEach(function (c, k) {
        var js = K.cats[c], fv = js.map(function (j) { return pct[K.free[j]]; }), fs = fv.reduce(function (a, b) { return a + b; }, 0);
        var fsc = fv.map(function (v) { return fs ? v * ci[k] / fs : ci[k] / js.length; });
        var fi = lr(fsc, ci[k]);
        js.forEach(function (j, m) { out[K.free[j]] = fi[m]; });
      });
    });
    return out;
  }

  /* ===================================================================
     History for Bootstrap and Hybrid: weekly returns for each holding over
     the weeks all real funds share. Funds with no price history (placeholders
     not yet in the database) get a proxy series: a correlated copy of a
     related fund's returns, scaled to the fund's volatility, centred on its
     assumed return, plus seeded independent noise.
     =================================================================== */
  function buildHistory(holdings, model) {
    var P = root.POLARIS_PRICES; if (!P || !P.r) return null;
    var d = D(), T0 = P.weeks.length, has = holdings.map(function (h) { var a = P.r[h.id]; return !!(a && !(d.funds[h.id] || {}).ph); });
    var start = 0, end = T0 - 1, t, i, k;
    holdings.forEach(function (h, i) {
      if (!has[i]) return; var a = P.r[h.id];
      var f = 0; while (f < T0 && a[f] == null) f++; var e = T0 - 1; while (e > 0 && a[e] == null) e--;
      start = Math.max(start, f); end = Math.min(end, e);
    });
    if (end - start < 52) return null;
    var T = end - start + 1, R = holdings.map(function () { return new Float64Array(T); }), proxies = [];
    holdings.forEach(function (h, i) {
      if (!has[i]) return; var a = P.r[h.id], last = 0;
      for (t = 0; t < T; t++) { var v = a[start + t]; if (v == null) v = 0; R[i][t] = v / 10000; }   /* rare inner gaps: flat week */
    });
    /* proxies */
    var refPool = { S: ['VTI US', 'VFV CN', 'XIC CN'], B: ['ZAG CN', 'XBB CN', 'BNDW US'], G: ['CGL CN'], C: ['VTI US', 'VFV CN'] };
    holdings.forEach(function (h, i) {
      if (has[i]) return;
      var ref = -1, refId = null;
      for (k = 0; k < holdings.length; k++) if (has[k] && h.cat && holdings[k].cat === h.cat) { ref = k; break; }
      if (ref < 0) { var g = h.g0 || h.grp; for (k = 0; k < holdings.length; k++) if (has[k] && (holdings[k].g0 || holdings[k].grp) === (g === 'C' ? 'S' : g)) { ref = k; break; } }
      var series;
      if (ref >= 0) { series = R[ref]; refId = holdings[ref].id; }
      else {
        var pool = refPool[h.g0 || h.grp] || refPool.S;
        for (k = 0; k < pool.length; k++) { var a = P.r[pool[k]]; if (a) { series = new Float64Array(T); for (t = 0; t < T; t++) series[t] = (a[start + t] || 0) / 10000; refId = pool[k]; break; } }
      }
      var rho = ref >= 0 ? model.corr[i][ref] : corrPair(h, { id: refId, cat: null, g0: (h.g0 === 'C' ? 'S' : (h.g0 || h.grp)) });
      var sigW = model.vol[i] / Math.sqrt(CFG.weeksPerYear), mW = model.mu[i] / CFG.weeksPerYear;
      var out = new Float64Array(T), N = normalGen(rng(hashStr(h.id) ^ CFG.seed));
      if (series) {
        var m = 0, s = 0; for (t = 0; t < T; t++) m += series[t]; m /= T; for (t = 0; t < T; t++) s += (series[t] - m) * (series[t] - m); s = Math.sqrt(s / (T - 1)) || 1e-9;
        var b = Math.max(-1, Math.min(1, rho)), idio = Math.sqrt(Math.max(0, 1 - b * b));
        for (t = 0; t < T; t++) out[t] = mW + sigW * (b * (series[t] - m) / s + idio * N());
      } else for (t = 0; t < T; t++) out[t] = mW + sigW * N();
      R[i] = out; proxies.push({ tk: h.tk, ref: refId ? refId.split(' ')[0] : null, corr: Math.round(rho * 100) / 100 });
    });
    return { R: R, T: T, start: start, from: P.weeks[start], to: P.weeks[end], proxies: proxies };
  }

  /* ===================================================================
     Simulation: one engine, three return generators
     All methods use weekly steps, the same contribution schedule and
     common random numbers (the same seed for both scenarios), so the
     differences come from the portfolios and the methods, not from noise.
     =================================================================== */
  /* Money going in, by month: regular contributions plus one-time lump sums.
     Month m is paid at the end of week round(m*52/12), after that week's return. Month 0 is today. */
  function monthWeek(m) { return Math.round(m * CFG.weeksPerYear / 12); }
  function cashByMonth(contrib, lumps) {
    var NM = CFG.maxYears * 12, c = new Float64Array(NM + 1);
    if (contrib && contrib.amount > 0) {
      var every = { monthly: 1, semiannual: 6, annual: 12 }[contrib.freq] || 1;
      for (var m = every; m <= NM; m += every) c[m] += contrib.amount;
    }
    (lumps || []).forEach(function (x) { var mm = Math.max(0, Math.min(NM, Math.round(x.month || 0))); if (x.amount > 0) c[mm] += x.amount; });
    return c;
  }
  function cashWeeks(contrib, lumps) {
    var cm = cashByMonth(contrib, lumps), wk = new Float64Array(CFG.maxYears * CFG.weeksPerYear + 1);
    for (var m = 1; m < cm.length; m++) if (cm[m]) wk[monthWeek(m)] += cm[m];
    return { weeks: wk, now: cm[0] };
  }
  function pctl(sorted, q) { return sorted[Math.min(sorted.length - 1, Math.floor(q * sorted.length))]; }
  function simulate(method, gen, amount, contrib, lumps) {
    var Y = CFG.maxYears, W = CFG.weeksPerYear, NW = Y * W, NP = CFG.paths, cs = cashWeeks(contrib, lumps), cw = cs.weeks;
    amount += cs.now;
    var snaps = []; for (var y = 0; y <= Y; y++) snaps.push(new Float64Array(NP));
    var ddAt = { 5: new Float64Array(NP), 10: new Float64Array(NP), 20: new Float64Array(NP) };
    var idxEnd = { 5: new Float64Array(NP), 10: new Float64Array(NP), 20: new Float64Array(NP) }, idx1 = new Float64Array(NP);
    var put = [amount]; var p = amount; for (var w0 = 1; w0 <= NW; w0++) { p += cw[w0]; if (w0 % W === 0) put.push(p); }
    var buf = new Float64Array(NW + 1), flush = new Uint8Array(NW + 1);
    for (var w1 = 1; w1 <= NW; w1++) flush[w1] = (cw[w1] || w1 % W === 0) ? 1 : 0;
    for (var n = 0; n < NP; n++) {
      var v = amount, L = 0, peak = 0, mdd = 0, acc = 0;
      gen.fill(buf, NW);                              /* this path's weekly log-returns */
      snaps[0][n] = v;
      for (var w = 1; w <= NW; w++) {
        var x = buf[w];
        L += x; acc += x;                             /* growth index in logs, for drawdowns */
        if (L > peak) peak = L; else if (L - peak < mdd) mdd = L - peak;
        if (flush[w]) {                               /* compound only when money is added or a year ends */
          v *= Math.exp(acc); acc = 0;
          v += cw[w];
          if (w % W === 0) { var yy = w / W; snaps[yy][n] = v; if (yy === 1) idx1[n] = Math.exp(L); if (ddAt[yy]) { ddAt[yy][n] = 1 - Math.exp(mdd); idxEnd[yy][n] = Math.exp(L); } }
        }
      }
    }
    var years = snaps.map(function (a, y) {
      var s = Float64Array.from(a).sort();
      return { y: y, p5: pctl(s, .05), p25: pctl(s, .25), p50: pctl(s, .5), p75: pctl(s, .75), p95: pctl(s, .95), put: put[y] };
    });
    var horizons = {};
    [5, 10, 20].forEach(function (h) {
      var a = snaps[h], s = Float64Array.from(a).sort(), k5 = Math.max(1, Math.floor(0.05 * NP));
      var below = 0; for (var i = 0; i < NP; i++) if (a[i] < put[h]) below++;
      var cvar = 0; for (i = 0; i < k5; i++) cvar += s[i]; cvar /= k5;
      var dd = Float64Array.from(ddAt[h]).sort(), ie = Float64Array.from(idxEnd[h]).sort();
      horizons[h] = { p5: pctl(s, .05), p50: pctl(s, .5), p95: pctl(s, .95), mean: s.reduce(function (x, z) { return x + z; }, 0) / NP, put: put[h],
        probLoss: below / NP, cvar5: cvar, ddMedian: pctl(dd, .5) * 100, ddBad: pctl(dd, .95) * 100,
        cagrMedian: (Math.pow(pctl(ie, .5), 1 / h) - 1) * 100 };
    });
    /* one year ahead, as a % of the money invested: Value at Risk and Conditional Value at Risk at 95% */
    var g1 = Float64Array.from(idx1).sort(), k1 = Math.max(1, Math.floor(0.05 * NP)), w5 = 0;
    for (var j = 0; j < k1; j++) w5 += g1[j]; w5 /= k1;
    var oneYear = { var95: (1 - pctl(g1, .05)) * 100, cvar95: (1 - w5) * 100, median: (pctl(g1, .5) - 1) * 100, probLoss: g1.filter(function (x) { return x < 1; }).length / NP };
    return { method: method, years: years, horizons: horizons, oneYear: oneYear };
  }
  /* Generators: fill(buf, NW) writes one path's weekly log-returns into buf[1..NW] */
  function genMC(stat, seed) {
    var mu = stat.ret / 100, sg = stat.vol / 100, W = CFG.weeksPerYear, dm = (mu - sg * sg / 2) / W, ds = sg / Math.sqrt(W);
    var N = normalGen(rng(seed));
    return { drift: dm, fill: function (buf, NW) { for (var w = 1; w <= NW; w++) buf[w] = dm + ds * N(); } };
  }
  function blockGen(s, seed) {
    var T = s.length, pNew = 1 / CFG.blockWeeks, R = rng(seed ^ 0x9E3779B9);
    return { fill: function (buf, NW) {
      var pos = Math.floor(R() * T);
      for (var w = 1; w <= NW; w++) { buf[w] = s[pos]; pos = R() < pNew ? Math.floor(R() * T) : (pos + 1) % T; }
    } };
  }
  function portHist(hist, w) {
    var T = hist.T, h = new Float64Array(T);
    for (var i = 0; i < w.length; i++) { if (!w[i]) continue; var r = hist.R[i], wi = w[i]; for (var t = 0; t < T; t++) h[t] += wi * r[t]; }
    return h;
  }
  function genBoot(hist, w, seed) {
    var h = portHist(hist, w), g = new Float64Array(h.length); for (var t = 0; t < h.length; t++) g[t] = Math.log(1 + h[t]);
    return blockGen(g, seed);
  }
  function genHybrid(hist, w, stat, seed) {
    var h = portHist(hist, w), T = h.length, x = new Float64Array(T), m = 0, s = 0, t, W = CFG.weeksPerYear;
    for (t = 0; t < T; t++) { x[t] = Math.log(1 + h[t]); m += x[t]; } m /= T;
    for (t = 0; t < T; t++) s += (x[t] - m) * (x[t] - m); var sdW = Math.sqrt(s / (T - 1)), sA = sdW * Math.sqrt(W);
    var mu = stat.ret / 100, drift = (mu - sA * sA / 2) / W, g = new Float64Array(T);
    for (t = 0; t < T; t++) g[t] = x[t] - m + drift;
    var gen = blockGen(g, seed); gen.drift = drift;
    return gen;
  }
  function histStats(hist, w) {
    var h = portHist(hist, w), T = h.length, W = CFG.weeksPerYear, m = 0, s = 0, t, lg = 0;
    for (t = 0; t < T; t++) { m += h[t]; lg += Math.log(1 + h[t]); } m /= T;
    for (t = 0; t < T; t++) s += (h[t] - m) * (h[t] - m);
    var sd = Math.sqrt(s / (T - 1)), sk = 0, ku = 0;
    for (t = 0; t < T; t++) { var z = (h[t] - m) / sd; sk += z * z * z; ku += z * z * z * z; }
    var peak = 1, v = 1, mdd = 0; for (t = 0; t < T; t++) { v *= 1 + h[t]; if (v > peak) peak = v; mdd = Math.max(mdd, 1 - v / peak); }
    /* beta: how much the mix moved per 1% move of a stock market, week by week, over the same weeks
       (fund betas in the database are each against its own category index, so they can't be averaged) */
    var P = root.POLARIS_PRICES, beta = {};
    CFG.betaVs.forEach(function (b) {
      var a = P && P.r && P.r[b.id]; if (!a) return;
      var mb = 0, n = 0; for (t = 0; t < T; t++) mb += (a[hist.start + t] || 0) / 1e4; mb /= T;
      var cv = 0, vb = 0; for (t = 0; t < T; t++) { var x = (a[hist.start + t] || 0) / 1e4 - mb; cv += x * (h[t] - m); vb += x * x; }
      beta[b.k] = vb ? cv / vb : null;
    });
    return { annRet: (Math.exp(lg / T * W) - 1) * 100, annVol: sd * Math.sqrt(W) * 100, skew: sk / T, exKurt: ku / T - 3, worstWeek: Math.min.apply(null, Array.prototype.slice.call(h)) * 100, maxDD: mdd * 100, beta: beta, weeks: T };
  }

  /* ===================================================================
     Shared results state
     =================================================================== */
  var listeners = [];
  function publish(r) {
    root.PolarisResults = r;
    listeners.forEach(function (fn) { try { fn(r); } catch (e) { if (root.console) console.error(e); } });
    if (typeof root.dispatchEvent === 'function' && typeof root.CustomEvent === 'function') root.dispatchEvent(new root.CustomEvent('polaris:results', { detail: r }));
  }
  function subscribe(fn) { listeners.push(fn); if (root.PolarisResults) fn(root.PolarisResults); return function () { listeners = listeners.filter(function (f) { return f !== fn; }); }; }

  /* Load etf-browser-prices.js on demand (browser only) */
  var pricesPromise = null;
  function loadPrices() {
    if (root.POLARIS_PRICES) return Promise.resolve(true);
    if (pricesPromise) return pricesPromise;
    pricesPromise = new Promise(function (res) {
      if (typeof document === 'undefined') { res(false); return; }
      var s = document.createElement('script'); s.src = CFG.pricesUrl; s.async = true;
      s.onload = function () { res(!!root.POLARIS_PRICES); }; s.onerror = function () { pricesPromise = null; res(false); };
      document.head.appendChild(s);
    });
    return pricesPromise;
  }

  /* ===================================================================
     Main entry point
     input = {
       holdings: [...],            see buildModel
       tier: 'low' | 'mod' | 'high',
       amount: 10000, contrib: { amount: 200, freq: 'monthly' } | null, lumps: [{ amount, month }],
       capWeights: [...]           optional: percent weights of the tier's reference mix
                                   (top of its band); its volatility is the risk limit
     }
     Returns the 11 slider stops (weights, return, volatility, Sharpe, split, fee). Projections
     are run per stop when asked for: PolarisEngine.sims(stop, method), cached.
     =================================================================== */
  var ctx = null, runCount = 0;
  function stopLabel(i) { return i === 0 ? 'Minimum Variance' : i === CFG.stops - 1 ? 'Maximum Return' : 'Stop ' + i; }
  function dataWindow(hist) {
    var P = root.POLARIS_PRICES, d = D(), from = P && P.weeks ? P.weeks[0] : null, to = P && P.weeks ? P.weeks[P.weeks.length - 1] : d.pricesTo;
    var months = function (a, b) { return a && b ? Math.round((Date.parse(b) - Date.parse(a)) / 864e5 / 30.44) : null; };
    return { pricesFrom: from, pricesTo: to, months: months(from, to), simFrom: hist ? hist.from : null, simTo: hist ? hist.to : null, simWeeks: hist ? hist.T : null };
  }
  function run(input) {
    var t0 = Date.now(), d = D(), notes = [];
    if (!d || !d.funds) throw new Error('PolarisEngine: etf-data.js not loaded');
    var H = input.holdings, tier = input.tier || 'mod', model = buildModel(H);
    var cap, capSrc;
    if (input.capWeights) { cap = portStats(model, input.capWeights.map(function (x) { return x / 100; })).vol; capSrc = 'reference'; }
    else { cap = CFG.fallbackCap[tier]; capSrc = 'fixed'; }
    var opt = optimize(H, model, tier, cap, notes), sl = buildStops(H, model, tier, opt);
    var hist = buildHistory(H, model);
    if (!hist) notes.push('Weekly price history was not available, so Bootstrap and Hybrid use Monte Carlo paths.');
    var rf = CFG.riskFree.rate;
    var out = { version: CFG.version, createdAt: new Date().toISOString(), asOf: d.asOfLabel, pricesTo: d.pricesToLabel,
      inputs: { tier: tier, amount: input.amount, contrib: input.contrib || null, lumps: input.lumps || [], holdings: H.map(function (h) { return { id: h.id, tk: h.tk, name: h.name, cat: h.cat, grp: h.grp, fixed: h.fixed, mer: h.mer, cur: h.cur }; }) },
      settings: { paths: CFG.paths, seed: CFG.seed, blockWeeks: CFG.blockWeeks, catMin: CFG.catMin, catMax: CFG.catMax, catMaxBy: CFG.catMaxBy, pairMin: CFG.pairMin, band: opt.K.band,
        stockRange: opt.K.stockRange.map(function (x) { return x + opt.K.fixedS; }), stops: CFG.stops, smoothing: sl.gamma },
      model: { mu: model.mu.map(function (x) { return x * 100; }), vol: model.vol.map(function (x) { return x * 100; }), volSource: model.volSource },
      volCap: { value: opt.cap, source: capSrc, binding: !!opt.maxret.capBinding },
      riskFree: CFG.riskFree,
      frontier: opt.frontier.map(function (p) { return { ret: p.ret, vol: p.vol }; }),
      history: hist ? { from: hist.from, to: hist.to, weeks: hist.T, proxies: hist.proxies } : null,
      dataWindow: dataWindow(hist),
      methods: METHODS, headline: CFG.headline, start: Math.min(CFG.startStop, CFG.stops - 1), stops: [], notes: notes };
    var seedFor = { mc: CFG.seed, boot: CFG.seed + 1, hybrid: CFG.seed + 2 };
    ctx = { id: ++runCount, H: H, model: model, hist: hist, seedFor: seedFor, scen: {}, grids: {}, sims: {}, out: out, amount: input.amount, contrib: input.contrib || null, lumps: input.lumps || [] };
    sl.stops.forEach(function (o) {
      var pct = roundWeights(H, o.w, opt.K), w = pct.map(function (x) { return x / 100; }), st = portStats(model, w);
      var S = 0, B = 0, O = 0, fee = 0;
      H.forEach(function (h, i) { if (h.grp === 'S') S += pct[i]; else if (h.grp === 'B') B += pct[i]; else O += pct[i]; fee += pct[i] * (h.mer || 0) / 100; });
      ctx.scen[o.i] = { w: w, st: st };
      out.stops.push({ i: o.i, label: stopLabel(o.i), target: o.target,
        weights: H.map(function (h, i) { return { id: h.id, tk: h.tk, w: pct[i], exact: o.w[i] * 100 }; }),
        exact: { ret: o.st.ret, vol: o.st.vol }, stats: { ret: st.ret, vol: st.vol, sharpe: st.vol ? (st.ret - rf) / st.vol : 0, fee: fee },
        split: { S: S, B: B, O: O }, hist: hist ? histStats(hist, w) : null, sims: {} });
    });
    out.runtimeMs = Date.now() - t0; out.solves = opt.solves + sl.solves; out.runId = ctx.id;
    publish(out);
    return out;
  }
  function stopIndex(k) { return k === 'minvar' ? 0 : k === 'maxret' ? CFG.stops - 1 : +k; }
  function makeGen(k, m) {
    var c = ctx.scen[k], seed = ctx.seedFor[m], h = ctx.hist;
    if (m === 'mc' || !h) return genMC(c.st, seed);
    return m === 'boot' ? genBoot(h, c.w, seed) : genHybrid(h, c.w, c.st, seed);
  }
  /* A stop's projection with one method (2,000 paths x 20 years), computed once and cached */
  function sims(k, m) {
    if (!ctx) throw new Error('PolarisEngine.sims: run() first');
    var i = stopIndex(k), key = i + '|' + m;
    if (!ctx.sims[key]) { ctx.sims[key] = simulate(m, makeGen(i, m), ctx.amount, ctx.contrib, ctx.lumps); ctx.out.stops[i].sims[m] = ctx.sims[key]; }
    return ctx.sims[key];
  }

  /* ===================================================================
     What if: change the money going in, keep everything else.
     The weights don't depend on the amounts, and the money added doesn't change
     the markets in each simulated future. So once each path's monthly growth is
     known, any starting amount, contribution or lump sum can be valued exactly:
     V(m) = V(m-1) x growth(m) + cash(m), path by path, then sorted. This gives the
     same numbers as re-running the simulation with the new amounts.
     =================================================================== */
  /* Each path's growth factor for every month: paths x 240, built once per stop and method (about 70 ms) */
  function growthGrid(k, m) {
    var key = k + '|' + m; if (ctx.grids[key]) return ctx.grids[key];
    var NP = CFG.paths, NW = CFG.maxYears * CFG.weeksPerYear, NM = CFG.maxYears * 12, buf = new Float64Array(NW + 1), g = new Float64Array(NP * NM), gen = makeGen(k, m);
    for (var n = 0; n < NP; n++) {
      gen.fill(buf, NW);
      var w = 1, base = n * NM;
      for (var mm = 1; mm <= NM; mm++) { var end = monthWeek(mm), acc = 0; for (; w <= end; w++) acc += buf[w]; g[base + mm - 1] = Math.exp(acc); }
    }
    ctx.grids = {}; ctx.grids[key] = g;            /* keep only the one on screen */
    return g;
  }
  /* opts = { stop: 0-10 (or scenario: 'minvar'|'maxret'), method: 'mc'|'boot'|'hybrid', start: 10000,
              contrib: { amount: 200, freq: 'monthly' } | null, lumps: [{ amount: 5000, month: 36 }] }
     Returns yearly percentiles and 5/10/20-year summaries, like PolarisEngine.sims(stop, method). */
  function whatIf(opts) {
    if (!ctx) throw new Error('PolarisEngine.whatIf: run() first');
    var t0 = Date.now(), k = stopIndex(opts.stop != null ? opts.stop : opts.scenario), m = opts.method, g = growthGrid(k, m), NP = CFG.paths, NM = CFG.maxYears * 12, Y = CFG.maxYears;
    var cm = cashByMonth(opts.contrib, opts.lumps), start = Math.max(0, +opts.start || 0) + cm[0];
    var snaps = []; for (var y = 0; y <= Y; y++) snaps.push(new Float64Array(NP));
    var put = [start], p = start; for (var mm = 1; mm <= NM; mm++) { p += cm[mm]; if (mm % 12 === 0) put.push(p); }
    for (var n = 0; n < NP; n++) {
      var v = start, base = n * NM; snaps[0][n] = v;
      for (mm = 1; mm <= NM; mm++) { v = v * g[base + mm - 1] + cm[mm]; if (mm % 12 === 0) snaps[mm / 12][n] = v; }
    }
    var years = snaps.map(function (a, y) { var s = Float64Array.from(a).sort(); return { y: y, p5: pctl(s, .05), p25: pctl(s, .25), p50: pctl(s, .5), p75: pctl(s, .75), p95: pctl(s, .95), put: put[y] }; });
    var horizons = {};
    [5, 10, 20].forEach(function (h) {
      var a = snaps[h], s = Float64Array.from(a).sort(), below = 0; for (var i = 0; i < NP; i++) if (a[i] < put[h]) below++;
      var med = pctl(s, .5);
      horizons[h] = { p5: pctl(s, .05), p50: med, p95: pctl(s, .95), mean: s.reduce(function (x, z) { return x + z; }, 0) / NP, put: put[h], probLoss: below / NP, growth: med - put[h] };
    });
    var r = { stop: k, method: m, runId: ctx.id, inputs: { start: +opts.start || 0, contrib: opts.contrib || null, lumps: (opts.lumps || []).slice() }, years: years, horizons: horizons, ms: Date.now() - t0 };
    if (root.PolarisResults && root.PolarisResults.runId === ctx.id) root.PolarisResults.whatIf = r;
    if (typeof root.dispatchEvent === 'function' && typeof root.CustomEvent === 'function') root.dispatchEvent(new root.CustomEvent('polaris:whatif', { detail: r }));
    return r;
  }

  /* ===================================================================
     Everything the personalized report needs, for the chosen stop and both ends:
     all three methods, risk measures and the data behind them.
     =================================================================== */
  function report(k) {
    if (!ctx) throw new Error('PolarisEngine.report: run() first');
    var t0 = Date.now(), d = D(), i = stopIndex(k), last = CFG.stops - 1, out = ctx.out, H = ctx.H, model = ctx.model;
    var keys = [0, i, last].filter(function (x, n, a) { return a.indexOf(x) === n; });
    var per = keys.map(function (s) {
      var st = out.stops[s], w = ctx.scen[s].w, methods = {};
      METHODS.forEach(function (m) { methods[m.k] = sims(s, m.k); });
      var sumWs = 0;
      H.forEach(function (h, j) { if (w[j]) sumWs += w[j] * model.vol[j]; });
      return { i: s, label: st.label, weights: st.weights, stats: st.stats, split: st.split, hist: st.hist, methods: methods,
        divRatio: st.stats.vol ? sumWs * 100 / st.stats.vol : null };
    });
    var held = H.map(function (h, j) { return j; }).filter(function (j) { return out.stops[i].weights[j].w > 0; });
    var r = { runId: ctx.id, createdAt: new Date().toISOString(), stop: i, keys: keys, per: per,
      corr: { tks: held.map(function (j) { return H[j].tk; }), m: held.map(function (a) { return held.map(function (b) { return Math.round(model.corr[a][b] * 100) / 100; }); }) },
      stopsSummary: out.stops.map(function (st) { return { i: st.i, ret: st.stats.ret, vol: st.stats.vol, S: st.split.S }; }),
      riskFree: CFG.riskFree, betaVs: CFG.betaVs, dataWindow: out.dataWindow, history: out.history, volCap: out.volCap, settings: out.settings, inputs: out.inputs, frontier: out.frontier, asOf: out.asOf, notes: out.notes, ms: 0 };
    r.stress = stressReport(i);
    r.ms = Date.now() - t0;
    if (root.PolarisResults && root.PolarisResults.runId === ctx.id) root.PolarisResults.report = r;
    return r;
  }

  /* ===================================================================
     Stress test (report only). Each fund gets its asset class's crash (Equity -40%, Bond -15%,
     Real estate -35%, Commodity -50%, Crypto -75%; a fund listed in stress.leverage multiplies its class's fall, capped at -95%; none are listed now).
     The mix's crash = the weighted average of its funds' falls, spread evenly over the first
     12 months of every simulated future, with that future's real weekly ups and downs kept on top.
     After that, the Hybrid method carries on. Same paths and seed as the normal Hybrid projection,
     so the only difference is the crash.
     =================================================================== */
  function stressClass(h) {
    var S = CFG.stress;
    if (S.byFund[h.id]) return S.byFund[h.id];
    if (h.cat) return D().cats[h.cat] && D().cats[h.cat].stock ? 'equity' : 'bond';
    var g = h.g0 || h.grp;
    return g === 'B' ? 'bond' : g === 'G' ? 'commodity' : g === 'C' ? 'crypto' : 'equity';
  }
  function stressLoss(k) {
    var S = CFG.stress, w = ctx.scen[k].w, sh = {}, by = {}, loss = 0;
    S.classes.forEach(function (c) { sh[c.k] = c.shock; by[c.k] = { w: 0, contrib: 0 }; });
    ctx.H.forEach(function (h, i) {
      if (!w[i]) return;
      var c = stressClass(h), f = Math.max(-95, sh[c] * (S.leverage[h.id] || 1));
      by[c].w += w[i] * 100; by[c].contrib += w[i] * f; loss += w[i] * f;
    });
    return { loss: loss, byClass: by };
  }
  function stress(k) {
    if (!ctx) throw new Error('PolarisEngine.stress: run() first');
    var i = stopIndex(k), key = i + '|stress';
    if (ctx.sims[key]) return ctx.sims[key];
    var S = CFG.stress, W = CFG.weeksPerYear, CW = Math.round(S.months / 12 * W), sl = stressLoss(i), m = ctx.hist ? 'hybrid' : 'mc';
    var lg = Math.log(1 + sl.loss / 100);
    var wrap = function (base) {
      return { fill: function (buf, NW) { base.fill(buf, NW); for (var w = 1; w <= CW && w <= NW; w++) buf[w] += lg / CW - base.drift; } };
    };
    var sim = simulate(m, wrap(makeGen(i, m)), ctx.amount, ctx.contrib, ctx.lumps);
    /* time for $1 invested at the start to be worth $1 again (same paths, replayed) */
    var g = wrap(makeGen(i, m)), NW = CFG.maxYears * W, buf = new Float64Array(NW + 1), rec = [], never = 0;
    for (var n = 0; n < CFG.paths; n++) {
      g.fill(buf, NW); var L = 0, at = -1;
      for (var w = 1; w <= NW; w++) { L += buf[w]; if (w >= CW && L >= 0) { at = w; break; } }
      if (at < 0) never++; else rec.push(at / W);
    }
    rec.sort(function (a, b) { return a - b; });
    var all = rec.concat(new Array(never).fill(Infinity));
    var out = { stop: i, method: m, loss: sl.loss, byClass: sl.byClass, months: S.months, sim: sim,
      recovery: { median: pctl(all, .5), p75: pctl(all, .75), neverShare: never / CFG.paths } };
    ctx.sims[key] = out;
    return out;
  }
  /* Everything the report's stress section needs: the chosen stop and both ends simulated,
     plus every stop's crash loss next to its normal 1-in-20 bad year, for the risk and return chart */
  function stressReport(k) {
    var i = stopIndex(k), last = CFG.stops - 1, keys = [0, i, last].filter(function (x, n, a) { return a.indexOf(x) === n; });
    var m = ctx.hist ? 'hybrid' : 'mc';
    return { classes: CFG.stress.classes, months: CFG.stress.months, leverage: CFG.stress.leverage, stop: i, keys: keys,
      per: keys.map(function (s) { var x = stress(s); return { i: s, loss: x.loss, byClass: x.byClass, sim: x.sim, recovery: x.recovery, normal: sims(s, m) }; }),
      stops: ctx.out.stops.map(function (st) { return { i: st.i, ret: st.stats.ret, vol: st.stats.vol, loss: stressLoss(st.i).loss, var95: sims(st.i, m).oneYear.var95 }; }),
      classOf: ctx.H.map(function (h) { return stressClass(h); }) };
  }

  return { run: run, sims: sims, whatIf: whatIf, report: report, stress: stress, stressReport: stressReport, loadPrices: loadPrices, subscribe: subscribe, config: CFG, METHODS: METHODS,
    _internal: { QPSolver: QPSolver, buildModel: buildModel, buildConstraints: buildConstraints, optimize: optimize, buildStops: buildStops, roundWeights: roundWeights, buildHistory: buildHistory, simulate: simulate, portStats: portStats } };
});
