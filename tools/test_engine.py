"""Independent check of polaris-engine.js.
Optimizer: compares both scenarios with cvxpy (Clarabel) on random selections built like the app does.
Simulators: compares Monte Carlo with the exact lognormal answer, and Bootstrap and Hybrid with a separate numpy implementation.
What if: checks that revaluing with new amounts equals a full re-run with those amounts.
Usage: python3 test_engine.py <site folder>      (needs node, numpy, scipy; cvxpy for the optimizer check: pip install cvxpy)"""
import json, os, re, subprocess, sys, tempfile
import numpy as np
from scipy.stats import norm
SITE = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), '..'))
out = os.path.join(tempfile.mkdtemp(), 'cases.json')
subprocess.run(['node', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'engine_cases.js'), SITE, out], check=True)
C = json.load(open(out)); fails = []

try:
    import cvxpy as cp
    worst = dict(minvar_vol_gap=0.0, maxret_ret_gap=0.0, weight_gap=0.0, constraint_breach=0.0, rounded_breach=0.0, cap_breach=0.0)
    for i, c in enumerate(C['opt']):
        mu, S, A, l, u = map(np.array, (c['mu'], c['cov'], c['A'], c['l'], c['u'])); free = c['free']; fx = np.array(c['fixed'], dtype=float)
        Sff = S[np.ix_(free, free)]; cross = S[free, :] @ fx; base = fx @ S @ fx
        def full(x):
            f = fx.copy(); f[free] = x; return f
        w = cp.Variable(len(free)); var = cp.quad_form(w, cp.psd_wrap(Sff)) + 2 * cross @ w + base
        cp.Problem(cp.Minimize(var), [A @ w >= l, A @ w <= u]).solve(solver='CLARABEL')
        wm = full(w.value); we = np.array(c['minvar'])
        worst['minvar_vol_gap'] = max(worst['minvar_vol_gap'], (np.sqrt(we @ S @ we) - np.sqrt(wm @ S @ wm)) * 100)
        w2 = cp.Variable(len(free)); var2 = cp.quad_form(w2, cp.psd_wrap(Sff)) + 2 * cross @ w2 + base
        cp.Problem(cp.Maximize(mu[free] @ w2), [A @ w2 >= l, A @ w2 <= u, var2 <= (c['cap'] / 100) ** 2]).solve(solver='CLARABEL')
        wr = full(w2.value); wx = np.array(c['maxret'])
        worst['maxret_ret_gap'] = max(worst['maxret_ret_gap'], (mu @ wr - mu @ wx) * 100)
        worst['cap_breach'] = max(worst['cap_breach'], np.sqrt(wx @ S @ wx) * 100 - c['cap'])
        worst['weight_gap'] = max(worst['weight_gap'], np.abs(we - wm).max() * 100, np.abs(wx - wr).max() * 100)
        for x in (we, wx):
            z = A @ x[free]; worst['constraint_breach'] = max(worst['constraint_breach'], (l - z).max() * 100, (z - u).max() * 100)
        for k in ('minvar', 'maxret'):
            x = np.array(c['rounded'][k]) / 100; z = A @ x[free]
            worst['rounded_breach'] = max(worst['rounded_breach'], (l - z).max() * 100, (z - u).max() * 100)
            if abs(sum(c['rounded'][k]) - 100) > 1e-9: fails.append(f'case {i} {k}: rounded weights do not sum to 100')
    print('Optimizer vs cvxpy, worst case over', len(C['opt']), 'selections (percentage points):', {k: round(v, 6) for k, v in worst.items()})
    for k, tol in dict(minvar_vol_gap=1e-4, maxret_ret_gap=1e-4, weight_gap=0.1, constraint_breach=1e-6, rounded_breach=1e-6, cap_breach=1e-4).items():
        if worst[k] > tol: fails.append(f'optimizer: {k} = {worst[k]:.6f} > {tol}')
except ImportError:
    print('cvxpy not installed: optimizer check skipped (pip install cvxpy)')

P = json.loads(re.search(r'=(\{.*\});?\s*$', open(os.path.join(SITE, 'etf-browser-prices.js')).read(), re.S).group(1)); weeks = P['weeks']
rng = np.random.default_rng(1)
def stationary(g, nw, n, L):
    T = len(g); pos = rng.integers(0, T, n); x = np.zeros(n); snaps = {}
    for wk in range(1, nw + 1):
        x += g[pos]; new = rng.random(n) < 1 / L; pos = np.where(new, rng.integers(0, T, n), (pos + 1) % T)
        if wk % 52 == 0: snaps[wk // 52] = np.exp(x)
    return snaps
worst_sim = 0.0
for c in C['sims']:
    if c['contrib']:
        h = c['sc']['minvar']['h']['mc']
        for H in (5, 10, 20):
            if h[str(H)]['put'] != c['amount'] + c['contrib']['amount'] * 12 * H: fails.append(f'contributions wrong at {H} years')
        continue
    i0, i1 = weeks.index(c['hist']['from']), weeks.index(c['hist']['to'])
    Rm = np.array([[(P['r'][i][t] or 0) / 1e4 for t in range(i0, i1 + 1)] for i in c['ids']]); A0 = c['amount']
    for k, s in c['sc'].items():
        w = np.array(s['w']); h = w @ Rm; mu = s['ret'] / 100; sg = s['vol'] / 100
        x = np.log1p(h); sA = x.std(ddof=1) * np.sqrt(52)
        gens = {'boot': x, 'hybrid': x - x.mean() + (mu - sA * sA / 2) / 52}
        for H in (10, 20):
            ref = {'mc': [A0 * np.exp((mu - sg * sg / 2) * H + sg * np.sqrt(H) * norm.ppf(q)) for q in (.05, .5, .95)]}
            for m, g in gens.items(): ref[m] = A0 * np.quantile(stationary(g, H * 52, 20000, c['blockWeeks'])[H], [.05, .5, .95])
            for m in ('mc', 'boot', 'hybrid'):
                e = s['h'][m][str(H)]; eng = [e['p5'], e['p50'], e['p95']]
                gap = max(abs(a / b - 1) for a, b in zip(eng, ref[m])); worst_sim = max(worst_sim, gap)
                if gap > 0.06: fails.append(f"{c['tier']} {k} {m} {H}y: engine {np.round(eng)} vs reference {np.round(ref[m])}")
print(f'Simulators vs independent reference: worst relative gap at the 5th/50th/95th percentiles {worst_sim:.1%} (sampling error with 2,000 paths is a few %)')
W = C['whatif']
print(f"What if vs full re-run (relative gap): same amounts {W['same']:.1e}, new amounts {W['changed']:.1e}, doubling all money {W['doubled']:.1e}")
for k, v in W.items():
    if v > 1e-9: fails.append(f'what-if {k}: gap {v:.2e}')
print('PASS' if not fails else 'FAIL\n  ' + '\n  '.join(fails))
sys.exit(1 if fails else 0)
