#!/usr/bin/env python3
"""
PolarisAI data build.

Reads the three fund databases plus polaris-config.json and writes:
  etf-data.js        window.POLARIS_DATA, loaded by index.html and app.html
  data-status.html   a page for the team: as-of date, picks, placeholders,
                     database requests and what changed since the last build
  build-report.md    the same summary as plain text

Usage:
  python3 build_etf_data.py --core etf_core.db --context etf_context.db \
      --prices etf_prices.db --out ../site [--previous old-etf-data.js]

Only the Python standard library is needed.
"""
import argparse, datetime as dt, html, json, math, os, re, sqlite3, sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REQUIRED = {
    "core": {"etf": ["ticker", "ticker_yahoo", "name", "fund_family", "listing_country", "currency",
                     "asset_class", "etf_category", "region", "theme", "is_esg", "income", "leveraged",
                     "cad_hedged", "mer_pct", "aum_cad_m", "volatility", "risk_tier"],
             "etf_theme": ["ticker", "theme", "dimension"], "meta": ["key", "value"],
             "allocation_policy": ["asset_class", "allowed_risk_profiles", "max_weight"]},
    "context": {"etf_universe": ["ticker", "eligible", "exclusion_reason"],
                "etf_profile": ["ticker", "long_business_summary", "description_source", "morningstar_category"],
                "etf_metrics": ["ticker", "max_drawdown", "income_yield_trailing", "holdings_count",
                                "three_year_avg_return", "sharpe_ratio", "beta", "week52_high", "week52_low"],
                "etf_theme": ["ticker", "theme", "dimension"],
                "yahoo_raw": ["ticker", "raw_json"]},
    "prices": {"price_weekly": ["ticker", "week_end", "adj_close"], "meta": ["key", "value"]},
}


def die(msg):
    print("ERROR: " + msg, file=sys.stderr)
    sys.exit(1)


def check_schema(con, which):
    for table, cols in REQUIRED[which].items():
        got = [r[1] for r in con.execute(f'PRAGMA table_info("{table}")')]
        if not got:
            die(f"{which} database has no table '{table}'. Is this the right file?")
        missing = [c for c in cols if c not in got]
        if missing:
            die(f"{which} database table '{table}' is missing columns: {', '.join(missing)}")


def short_tk(ticker):
    t = ticker.rsplit(" ", 1)[0]
    return t.replace("/", ".")


def fmt_date(iso):
    d = dt.date.fromisoformat(iso[:10])
    months = ["Jan.", "Feb.", "Mar.", "Apr.", "May", "June", "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."]
    return f"{months[d.month-1]} {d.day}, {d.year}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--core", required=True)
    ap.add_argument("--context", required=True)
    ap.add_argument("--prices", required=True)
    ap.add_argument("--config", default=os.path.join(HERE, "polaris-config.json"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--previous", help="the etf-data.js currently published, for the change report")
    a = ap.parse_args()

    cfg = json.load(open(a.config, encoding="utf-8"))
    core = sqlite3.connect(f"file:{a.core}?mode=ro", uri=True)
    ctx = sqlite3.connect(f"file:{a.context}?mode=ro", uri=True)
    prc = sqlite3.connect(f"file:{a.prices}?mode=ro", uri=True)
    check_schema(core, "core"); check_schema(ctx, "context"); check_schema(prc, "prices")
    core.row_factory = sqlite3.Row

    meta = dict(core.execute("select key, value from meta").fetchall())
    pmeta = dict(prc.execute("select key, value from meta").fetchall())
    as_of = meta.get("patched_at") or meta.get("built_at")
    screened = ctx.execute("select count(*) from etf_universe").fetchone()[0]
    universe = {r[0]: (r[1], r[2]) for r in ctx.execute("select ticker, eligible, exclusion_reason from etf_universe")}

    # ---------- eligible funds ----------
    etf = {r["ticker"]: dict(r) for r in core.execute("select * from etf")}
    if not etf:
        die("etf_core.db has no funds")
    tags = defaultdict(list)
    for t, theme, dim in core.execute("select ticker, theme, dimension from etf_theme"):
        tags[t].append((dim, theme))
    prof = {r[0]: (r[1], r[2]) for r in ctx.execute("select ticker, long_business_summary, description_source from etf_profile")}
    mets = {r[0]: r[1:] for r in ctx.execute("select ticker, max_drawdown, income_yield_trailing, holdings_count, three_year_avg_return from etf_metrics")}
    policy = {r[0]: (r[1], r[2]) for r in core.execute("select asset_class, allowed_risk_profiles, max_weight from allocation_policy")}

    cats = cfg["categories"]
    db2key = {v["db"]: k for k, v in cats.items()}
    for k, v in cats.items():
        if not any(e["etf_category"] == v["db"] for e in etf.values()):
            die(f"No eligible funds in category '{v['db']}' (app key {k}). Did the category names change?")

    br = cfg["broad_rules"]

    def name_hit(name, words):
        n = " " + (name or "") + " "
        return [w for w in words if w.lower() in n.lower()]

    def passes(e, tiers, sus, inc, cad):
        k = db2key.get(e["etf_category"])
        if k is None or e["risk_tier"] not in tiers or e["leveraged"]:
            return False
        stock = cats[k]["stock"]
        if cad and e["currency"] != "CAD":
            return False
        if e["theme"] and not (sus and e["theme"] in br.get("esg_theme_values", [])):
            return False
        t = tags.get(e["ticker"], [])
        for dim, th in t:
            if dim in br["exclude_theme_dimensions"] or th in br["exclude_factor_tags"] or th in br["exclude_macro_tags"]:
                return False
        esg = bool(e["is_esg"]) or any(d.startswith("Dimension 4") for d, _ in t)
        if sus != esg:
            return False
        if stock:
            is_inc = bool(e["income"]) or any(th == br["income_tag"] for _, th in t)
            if inc != is_inc:
                return False
            words = [w for w in br["stock_name_exclude"] if not (inc and w in br["stock_name_exclude_unless_income"])]
            if name_hit(e["name"], words):
                return False
        else:
            if name_hit(e["name"], br["bond_name_exclude"]):
                return False
        return True

    def rank(ids):
        return sorted(ids, key=lambda t: (etf[t]["mer_pct"] if etf[t]["mer_pct"] is not None else 99, -(etf[t]["aum_cad_m"] or 0)))

    counts, picks, fallback = {}, {}, {}
    for tg, tiers in cfg["tier_groups"].items():
        for sus in (0, 1):
            for inc in (0, 1):
                for cad in (0, 1):
                    key = f"{tg}|{sus}|{inc}|{cad}"
                    counts[key], picks[key], fallback[key] = {}, {}, {}
                    for k, c in cats.items():
                        ids = [t for t, e in etf.items() if e["etf_category"] == c["db"] and passes(e, tiers, bool(sus), bool(inc and c["stock"]), bool(cad))]
                        counts[key][k] = len(ids)
                        if ids:
                            picks[key][k] = rank(ids)[0]
                        else:
                            # regular fund: drop sustainable/income, keep risk and currency; then drop currency
                            for s2, i2, c2 in ((0, 0, cad), (0, 0, 0)):
                                ids2 = [t for t, e in etf.items() if e["etf_category"] == c["db"] and passes(e, tiers, bool(s2), bool(i2), bool(c2))]
                                if ids2:
                                    picks[key][k] = rank(ids2)[0]; fallback[key][k] = 1; break
                            else:
                                die(f"No fund at all for {k} under {key}")
    cat_all = {k: sum(1 for e in etf.values() if e["etf_category"] == c["db"]) for k, c in cats.items()}

    # ---------- resolve placeholder tickers ----------
    def resolve(item):
        tk = item["tk"]
        cands = [item["id"]] if item.get("id") else [f"{tk} CN", f"{tk} US", f"{tk}/B CN", f"{tk}/U CN"]
        for c in cands:
            if c in etf:
                return c, "eligible", None
        for c in cands:
            if c in universe:
                return c, "excluded", universe[c][1]
        return None, "missing", None

    pool = set()
    for key in picks:
        pool.update(picks[key].values())
    placeholders = {}
    status_rows = []

    def ref(item, where):
        rid, st, why = resolve(item)
        if item.get("manual"):
            note = "kept as a manual entry" + (f"; the database has {rid}, check it is the same units" if rid else "")
            status_rows.append({"tk": item["tk"], "where": where, "status": "manual", "id": rid, "why": note})
            pid = "PH:" + item["tk"]; placeholders[pid] = item
            return pid
        status_rows.append({"tk": item["tk"], "where": where, "status": st, "id": rid, "why": why})
        if st == "eligible":
            pool.add(rid)
            return rid
        pid = "PH:" + item["tk"]
        placeholders[pid] = item
        return pid

    swaps = {k: [ref(i, f"Swap options · {cats[k]['name']}") for i in lst] for k, lst in cfg["swaps"].items()}
    second = {k: [ref(i, f"Second fund · {cats[k]['name']}") for i in lst] for k, lst in cfg["second"].items()}
    themes = []
    for t in cfg["themes"]:
        themes.append(dict(t, id=ref(t, "Thematic ETF")))
    extras = []
    for x in cfg["extras"]:
        extras.append(dict(x, id=ref(x, "High-risk ETF")))
    for k, tk in cfg["old_core_picks"].items():
        rid, st, why = resolve({"tk": tk})
        status_rows.append({"tk": tk, "where": f"Previous core pick · {cats[k]['name']}", "status": st, "id": rid, "why": why})

    # ---------- prices: returns, calendar years, correlation ----------
    series = defaultdict(dict)
    for t, w, p in prc.execute("select ticker, week_end, adj_close from price_weekly"):
        series[t][w] = p
    last_week = pmeta.get("last_week") or prc.execute("select max(week_end) from price_weekly").fetchone()[0]

    def perf(t):
        s = series.get(t)
        if not s or len(s) < 30:
            return {}
        weeks = sorted(s)
        px = [s[w] for w in weeks]
        out = {}
        if len(px) > 52:
            out["r1"] = round((px[-1] / px[-53] - 1) * 100, 2)
        if len(px) >= 150:
            n = len(px) - 1
            out["r3"] = round(((px[-1] / px[0]) ** (52 / n) - 1) * 100, 2)
        cal = []
        years = sorted({w[:4] for w in weeks})
        for y in years:
            prev = [w for w in weeks if w[:4] < y]
            cur = [w for w in weeks if w[:4] == y]
            if not prev or not cur:
                continue
            if prev[-1][:4] != str(int(y) - 1) or prev[-1][5:7] != "12":
                continue
            r = (s[cur[-1]] / s[prev[-1]] - 1) * 100
            ytd = cur[-1][5:7] != "12"
            cal.append([int(y), round(r, 2), 1 if ytd else 0])
        out["cal"] = cal
        out["last"] = weeks[-1]
        return out

    def rets(t):
        s = series.get(t, {})
        w = sorted(s)
        return {w[i]: s[w[i]] / s[w[i - 1]] - 1 for i in range(1, len(w))}

    R = {t: rets(t) for t in pool}
    corr = {}
    ids = sorted(pool)
    for i, x in enumerate(ids):
        for y in ids[i + 1:]:
            common = [w for w in R[x] if w in R[y]]
            if len(common) < 52:
                continue
            ax = [R[x][w] for w in common]; ay = [R[y][w] for w in common]
            mx, my = sum(ax) / len(ax), sum(ay) / len(ay)
            sxy = sum((p - mx) * (q - my) for p, q in zip(ax, ay))
            sxx = sum((p - mx) ** 2 for p in ax); syy = sum((q - my) ** 2 for q in ay)
            if sxx > 0 and syy > 0:
                corr[f"{x}|{y}"] = round(sxy / math.sqrt(sxx * syy), 3)

    # ---------- fund records ----------
    def first_sentences(txt, n=2, limit=420):
        if not txt:
            return None
        parts = re.split(r"(?<=[a-z0-9)\]][.!?])\s+(?=[A-Z])", txt.strip())
        out = " ".join(parts[:n])
        return out if len(out) <= limit else out[:limit].rsplit(" ", 1)[0] + "…"

    # ---------- extra fund facts (Yahoo raw data, metrics, profile, tags) ----------
    raw = {}
    for t, js in ctx.execute("select ticker, raw_json from yahoo_raw"):
        try:
            raw[t] = json.loads(js) if js else {}
        except ValueError:
            raw[t] = {}
    mets2 = {r[0]: r[1:] for r in ctx.execute("select ticker, sharpe_ratio, beta, week52_high, week52_low from etf_metrics")}
    mstar = {r[0]: r[1] for r in ctx.execute("select ticker, morningstar_category from etf_profile")}
    utags = defaultdict(list)
    for t, th in ctx.execute("select ticker, theme from etf_theme order by ticker, dimension, theme"):
        utags[t].append(th)

    def num(v, mult=1.0, dp=2):
        try:
            if v is None or v == "" or (isinstance(v, float) and math.isnan(v)):
                return None
            return round(float(v) * mult, dp)
        except (TypeError, ValueError):
            return None

    def extra(t, perf_rec):
        r = raw.get(t, {}) or {}
        m2 = mets2.get(t, (None, None, None, None))
        out = {
            "ytd": perf_rec["cal"][-1][1] if perf_rec.get("cal") and perf_rec["cal"][-1][2] else num(r.get("ytdReturn")),
            "r5": num(r.get("fiveYearAverageReturn"), 100),
            "sharpe": num(m2[0]), "beta": num(m2[1] if m2[1] is not None else r.get("beta3Year")),
            "price": num(r.get("regularMarketPrice") or r.get("navPrice") or r.get("previousClose")),
            "hi52": num(m2[2] if m2[2] is not None else r.get("fiftyTwoWeekHigh")),
            "lo52": num(m2[3] if m2[3] is not None else r.get("fiftyTwoWeekLow")),
            "nav": num(r.get("navPrice")), "pe": num(r.get("trailingPE"), 1, 1),
            "avgvol": int(r["averageVolume"]) if isinstance(r.get("averageVolume"), (int, float)) else None,
            "exch": r.get("fullExchangeName") or r.get("exchange"),
            "mstar": mstar.get(t),
            "yld_raw": num(r.get("yield"), 100) if isinstance(r.get("yield"), (int, float)) and r.get("yield") < 1 else None,
            "tags": utags.get(t) or None,
        }
        inc = r.get("fundInceptionDate")
        if isinstance(inc, (int, float)) and inc > 0:
            out["incep"] = dt.datetime.fromtimestamp(inc, dt.timezone.utc).strftime("%Y-%m")
        return out

    funds = {}
    for t in sorted(pool):
        e = etf[t]
        m = mets.get(t, (None, None, None, None))
        d, dsrc = prof.get(t, (None, None))
        rec = {
            "id": t, "tk": short_tk(t), "name": e["name"], "fam": e["fund_family"],
            "cur": e["currency"], "listing": e["listing_country"], "cat": db2key.get(e["etf_category"]),
            "dbcat": e["etf_category"], "ac": e["asset_class"], "mer": e["mer_pct"],
            "aum": round(e["aum_cad_m"], 1) if e["aum_cad_m"] is not None else None,
            "vol": round(e["volatility"] * 100, 2) if e["volatility"] is not None else None,
            "tier": e["risk_tier"], "esg": e["is_esg"], "inc": e["income"],
            "hedged": e["cad_hedged"], "yahoo": e["ticker_yahoo"],
            "dd": round(m[0] * 100, 1) if m[0] is not None else None,
            "yld": round(m[1] * 100, 2) if m[1] is not None and m[1] < 1 else None,
            "hold": int(m[2]) if m[2] else None,
            "desc": first_sentences(d) if dsrc == "yahoo" else None,
        }
        pr = perf(t)
        rec.update(pr)
        rec.update(extra(t, pr))
        if rec.get("yld") is None: rec["yld"] = rec.get("yld_raw")
        rec.pop("yld_raw", None)
        funds[t] = {k: v for k, v in rec.items() if v is not None}
    for pid, item in placeholders.items():
        funds[pid] = {"id": pid, "tk": item["tk"], "name": item.get("name", item["tk"]),
                      "mer": item.get("mer"), "cur": item.get("cur", "CAD"), "ph": 1,
                      "phcorr": item.get("corr"), "vol": item.get("vol")}

    # ---------- policy checks for the data requests ----------
    policy_flags = []
    for x in cfg["extras"]:
        if x.get("kind") == "lev":
            policy_flags.append(f"{x['tk']} is a leveraged fund offered at {', '.join(x['levels'])} risk, but the database excludes leveraged funds. Kept as a manual exception for now.")
        if x.get("kind") == "crypto" and "Crypto" in policy:
            allowed, maxw = policy["Crypto"]
            lv = {"mod": "Moderate", "high": "High", "low": "Low"}
            offered = [lv[l] for l in x["levels"]]
            if set(offered) != set(a.strip() for a in (allowed or "").split(",")):
                policy_flags.append(f"Crypto: allocation_policy allows {allowed} only (max {maxw:.0%}), but the site offers {x['tk']} to {' and '.join(offered)}. Kept as is for now.")
        rid, st, _ = resolve(x)
        if st == "eligible" and x.get("mer") is not None and abs((etf[rid]["mer_pct"] or 0) - x["mer"]) > 0.005:
            policy_flags.append(f"{x['tk']}: the site uses {x['mer']:.2f}% (manual entry); the database has {rid} at {etf[rid]['mer_pct']:.2f}%. Confirm which units the site should offer.")
    crypto_cheapest = rank([t for t, e in etf.items() if e["asset_class"] == "Crypto"])
    if crypto_cheapest:
        c0 = etf[crypto_cheapest[0]]
        policy_flags.append(f"Lowest-fee eligible bitcoin ETF is {crypto_cheapest[0]} at {c0['mer_pct']:.2f}%. Decide whether it should replace BTCC.")

    data = {
        "version": 1,
        "builtAt": dt.datetime.now().replace(microsecond=0).isoformat(),
        "asOf": as_of, "asOfLabel": fmt_date(as_of), "pricesTo": last_week, "pricesToLabel": fmt_date(last_week),
        "screened": screened, "eligible": len(etf),
        "cats": {k: {"name": c["name"], "db": c["db"], "stock": c["stock"], "about": c["about"], "ex": c.get("ex"), "all": cat_all[k]} for k, c in cats.items()},
        "counts": counts, "picks": picks, "fallback": fallback,
        "funds": funds, "corr": corr,
        "assume": cfg["assumptions"],
        "swaps": swaps, "second": second, "themes": themes, "extras": extras,
    }

    os.makedirs(a.out, exist_ok=True)
    js = "/* PolarisAI fund data. Generated by tools/build_etf_data.py — do not edit by hand. */\nwindow.POLARIS_DATA=" + json.dumps(data, separators=(",", ":"), ensure_ascii=False) + ";\n"
    open(os.path.join(a.out, "etf-data.js"), "w", encoding="utf-8").write(js)
    write_browser(a.out, data, ctx, etf, universe, prof, mets, raw, perf, extra, first_sentences, utags, br, cats, series, last_week)

    # ---------- change report ----------
    changes = []
    if a.previous and os.path.exists(a.previous):
        txt = open(a.previous, encoding="utf-8").read()
        prev = json.loads(txt[txt.index("=") + 1:].rstrip().rstrip(";"))
        changes.append(f"Previous data as of {prev.get('asOfLabel')}; new data as of {data['asOfLabel']}.")
        changes.append(f"Eligible funds: {prev.get('eligible')} → {data['eligible']}. Screened: {prev.get('screened')} → {data['screened']}.")
        for key in ("lm|0|0|0", "h|0|0|0", "lm|0|0|1"):
            for k in cats:
                o = prev.get("picks", {}).get(key, {}).get(k); n = picks[key][k]
                if o != n:
                    changes.append(f"Pick changed ({key}, {cats[k]['name']}): {o} → {n}")
        pf, nf = prev.get("funds", {}), funds
        for t in sorted(set(pf) & set(nf)):
            if pf[t].get("mer") != nf[t].get("mer"):
                changes.append(f"Fee changed for {t}: {pf[t].get('mer')} → {nf[t].get('mer')}")
        for t in sorted(set(pf) - set(nf)):
            if t.startswith("PH:") and ("PH:" + t[3:]) not in nf:
                changes.append(f"Placeholder {t[3:]} is now resolved from the database")
    else:
        changes.append("No previous data file given, so there is nothing to compare against.")

    write_status(a.out, data, cats, status_rows, policy_flags, cfg, changes)
    print(f"OK  data as of {data['asOfLabel']}  eligible {len(etf)}  screened {screened}  pool {len(pool)}  placeholders {len(placeholders)}  corr pairs {len(corr)}")
    print("Default picks (Low/Moderate, no preferences):", ", ".join(f"{k}={picks['lm|0|0|0'][k]}" for k in cats))
    print("CAD-only picks:", ", ".join(f"{k}={picks['lm|0|0|1'][k]}" for k in cats))
    for c in changes:
        print("  change:", c)


BROWSER_COLS = ["id", "tk", "name", "fam", "cat", "ac", "region", "listing", "cur", "mer", "aum", "vol", "tier",
                "esg", "inc", "lev", "hedged", "elig", "why", "broad", "tags", "mstar", "ytd", "r1", "r3", "r5",
                "sharpe", "beta", "dd", "yld", "price", "hi52", "lo52", "incep", "pe", "nav", "avgvol", "exch",
                "yahoo", "desc", "cal", "hasp"]


def write_browser(out, data, ctx, etf, universe, prof, mets, raw, perf, extra, first_sentences, utags, br, cats, series, last_week):
    """etf-browser-data.js: every screened fund. etf-browser-prices.js: weekly returns (loaded only for Compare)."""
    core_db = {c["db"]: c["stock"] for c in cats.values()}
    def name_hit(name, words):
        n = " " + (name or "") + " "
        return any(w.lower() in n.lower() for w in words)
    def broad(u, tags):
        if u["etf_category"] not in core_db or u["leveraged"] or u["is_inverse"]:
            return 0
        if u["theme"] and u["theme"] not in br.get("esg_theme_values", []):
            return 0
        bad = set(br["exclude_factor_tags"]) | set(br["exclude_macro_tags"])
        if any(t in bad for t in tags):
            return 0
        words = br["stock_name_exclude"] if core_db[u["etf_category"]] else br["bond_name_exclude"]
        words = [w for w in words if w not in br["stock_name_exclude_unless_income"]]
        return 0 if name_hit(u["name"], words) else 1
    ctx.row_factory = sqlite3.Row
    rows = []
    for u in ctx.execute("select * from etf_universe order by ticker"):
        t = u["ticker"]
        e = etf.get(t) or {}
        g = lambda k: e.get(k) if e.get(k) is not None else u[k]
        m = mets.get(t, (None, None, None, None))
        d, dsrc = prof.get(t, (None, None))
        pr = perf(t)
        ex = extra(t, pr)
        tags = utags.get(t, [])
        mer = g("mer_pct"); aum = g("aum_cad_m"); vol = g("volatility")
        rec = {
            "id": t, "tk": short_tk(t), "name": g("name"), "fam": g("fund_family"), "cat": g("etf_category"),
            "ac": g("asset_class"), "region": g("region"), "listing": g("listing_country"), "cur": g("currency"),
            "mer": mer, "aum": round(aum, 1) if aum is not None else None,
            "vol": round(vol * 100, 2) if vol is not None else None, "tier": g("risk_tier"),
            "esg": u["is_esg"], "inc": u["income"], "lev": u["leveraged"], "hedged": u["cad_hedged"],
            "elig": 1 if t in etf else 0, "why": None if t in etf else (universe.get(t, (0, None))[1]),
            "broad": broad(u, tags), "yahoo": g("ticker_yahoo"),
            "dd": round(m[0] * 100, 1) if m[0] is not None else None,
            "yld": round(m[1] * 100, 2) if m[1] is not None and m[1] < 1 else None,
            "desc": first_sentences(d, 3, 600) if d and dsrc == "yahoo" else None,
            "r1": pr.get("r1"), "r3": pr.get("r3"),
            "cal": pr.get("cal") or None, "hasp": 1 if t in series and len(series[t]) > 52 else 0,
        }
        r = raw.get(t, {}) or {}
        if rec["r3"] is None and r.get("threeYearAverageReturn") is not None:
            try: rec["r3"] = round(float(r["threeYearAverageReturn"]) * 100, 2)
            except (TypeError, ValueError): pass
        rec.update({k: v for k, v in ex.items() if k not in rec or rec[k] is None})
        if rec.get("yld") is None: rec["yld"] = ex.get("yld_raw")
        rows.append([rec.get(c) for c in BROWSER_COLS])
    payload = {"asOf": data["asOf"], "asOfLabel": data["asOfLabel"], "pricesToLabel": data["pricesToLabel"],
               "screened": data["screened"], "eligible": data["eligible"], "cols": BROWSER_COLS, "rows": rows}
    js = "/* PolarisAI ETF browser data. Generated by tools/build_etf_data.py \u2014 do not edit by hand. */\nwindow.POLARIS_BROWSER=" + json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + ";\n"
    open(os.path.join(out, "etf-browser-data.js"), "w", encoding="utf-8").write(js)
    # weekly returns in basis points, aligned to one week list
    weeks = sorted({w for s in series.values() for w in s})
    idx = {w: i for i, w in enumerate(weeks)}
    ser = {}
    for t, s in series.items():
        ws = sorted(s)
        arr = [None] * len(weeks)
        for i in range(1, len(ws)):
            arr[idx[ws[i]]] = round((s[ws[i]] / s[ws[i - 1]] - 1) * 10000)
        ser[t] = arr
    js = "window.POLARIS_PRICES=" + json.dumps({"weeks": weeks, "unit": "basis points", "r": ser}, separators=(",", ":")) + ";\n"
    open(os.path.join(out, "etf-browser-prices.js"), "w", encoding="utf-8").write(js)


def write_status(out, data, cats, rows, flags, cfg, changes):
    e = html.escape
    F = data["funds"]
    def pick_cell(key, k):
        t = data["picks"][key][k]; f = F[t]
        fb = " <em>(regular fund)</em>" if data["fallback"][key].get(k) else ""
        return f"<td><b>{e(f['tk'])}</b> {e(f['name'])}<br><small>{f['mer']:.2f}% · {e(f['cur'])} · {data['counts'][key][k]} eligible</small>{fb}</td>"
    combos = [("lm|0|0|0", "Low / Moderate"), ("h|0|0|0", "High"), ("lm|0|0|1", "Canadian-dollar only"), ("lm|1|0|0", "Sustainable"), ("lm|0|1|0", "Income")]
    picks_html = "<table><thead><tr><th>Category</th>" + "".join(f"<th>{e(n)}</th>" for _, n in combos) + "</tr></thead><tbody>"
    for k, c in cats.items():
        picks_html += f"<tr><th>{e(c['name'])}</th>" + "".join(pick_cell(key, k) for key, _ in combos) + "</tr>"
    picks_html += "</tbody></table>"
    st_lbl = {"eligible": "In database", "excluded": "Excluded", "missing": "Not in database", "manual": "Manual entry"}
    need = [r for r in rows if r["status"] != "eligible"]
    ok = [r for r in rows if r["status"] == "eligible"]
    SEP, DASH, EMSEP = " \u00b7 ", "\u2014", " \u2014 "
    def rows_html(rs):
        return "".join(f"<tr><td><b>{e(r['tk'])}</b></td><td>{e(r['where'])}</td><td><span class='s {r['status']}'>{st_lbl[r['status']]}</span>{(' · ' + e(r['why'])) if r['why'] else ''}</td><td>{e(r['id'] or '—')}</td></tr>" for r in rs)
    req_html = "".join(f"<li><b>{e(s['area'])}:</b> {e(s['ask'])}</li>" for s in cfg["schema_requests"])
    flag_html = "".join(f"<li>{e(f)}</li>" for f in flags)
    ch_html = "".join(f"<li>{e(c)}</li>" for c in changes)
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PolarisAI data status</title><meta name="robots" content="noindex">
<style>
:root{{--bg:#0D1D47;--card:#13285E;--ink:#fff;--muted:#C9D7F2;--line:rgba(143,184,255,.25);--warm:#FFC27A;--ok:#6EE0A8;--bad:#FF9E8A}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 "DM Sans",system-ui,sans-serif;padding:24px 16px 60px}}
.wrap{{max-width:1100px;margin:0 auto}}h1{{font:700 30px/1.15 system-ui,sans-serif;margin:0 0 6px}}h2{{margin:36px 0 10px;font-size:20px;color:var(--warm)}}
p{{color:var(--muted);margin:0 0 10px}}a{{color:#8FB8FF}}.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:18px 0}}
.kpis div{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}}.kpis b{{display:block;font-size:24px}}.kpis span{{color:var(--muted);font-size:13px}}
.tw{{overflow-x:auto;border:1px solid var(--line);border-radius:12px}}table{{border-collapse:collapse;width:100%;font-size:13.5px;min-width:640px}}
th,td{{text-align:left;vertical-align:top;padding:8px 10px;border-bottom:1px solid var(--line)}}thead th{{color:var(--muted);font-weight:600;background:rgba(255,255,255,.04)}}
small{{color:var(--muted)}}em{{color:var(--warm);font-style:normal}}ul{{margin:0;padding-left:20px}}li{{margin:0 0 6px}}
.s{{font-size:12px;font-weight:700;padding:2px 8px;border-radius:999px}}.s.eligible{{background:rgba(110,224,168,.15);color:var(--ok)}}.s.excluded{{background:rgba(255,194,122,.15);color:var(--warm)}}.s.missing{{background:rgba(255,158,138,.15);color:var(--bad)}}.s.manual{{background:rgba(185,166,242,.18);color:#CDBEFF}}
details{{margin-top:10px}}summary{{cursor:pointer;color:var(--muted)}}
</style></head><body><div class="wrap">
<h1>PolarisAI data status</h1>
<p>Fund data as of <b>{e(data['asOfLabel'])}</b> (prices to {e(data['pricesTo'])}). Built {e(data['builtAt'].replace('T',' '))}. <a href="app.html">Open the builder</a> · <a href="index.html">Landing page</a></p>
<div class="kpis"><div><b>{data['screened']:,}</b><span>ETFs screened</span></div><div><b>{data['eligible']:,}</b><span>pass all screens</span></div>
<div><b>{len({r['tk'] for r in need if r['status']=='missing'})}</b><span>funds the site uses that aren't in the database</span></div><div><b>{len({r['tk'] for r in need if r['status']=='excluded'})}</b><span>funds the site uses that fail the screens</span></div></div>
<h2>What changed in this update</h2><ul>{ch_html}</ul>
<h2>For the next database build</h2>
<p>These are needed so step 4 and the high-risk options can come entirely from the database instead of placeholders.</p>
<div class="tw"><table><thead><tr><th>Fund</th><th>Used for</th><th>Status</th><th>Database ticker</th></tr></thead><tbody>{rows_html(need)}</tbody></table></div>
<h2>Policy conflicts to settle</h2><ul>{flag_html}</ul>
<h2>Schema requests</h2><ul>{req_html}</ul>
<h2>Core picks by preference</h2>
<p>Lowest fee among broad funds that fit the risk level and preference; ties go to the larger fund. US-listed funds are allowed unless the client picks Canadian-dollar ETFs only.</p>
<div class="tw">{picks_html}</div>
<details><summary>Step 4 funds already in the database ({len(ok)})</summary><div class="tw"><table><tbody>{rows_html(ok)}</tbody></table></div></details>
<h2>How to update</h2><p>Upload the three new .db files to Claude in a chat and ask it to update PolarisAI. The steps are in <a href="tools/UPDATING.md">tools/UPDATING.md</a>.</p>
</div></body></html>"""
    open(os.path.join(out, "data-status.html"), "w", encoding="utf-8").write(page)
    md = [f"# PolarisAI data build — data as of {data['asOfLabel']}", "", "## Changes"] + [f"- {c}" for c in changes]
    md += ["", "## Needed in the next database build"] + [f"- {r['tk']} ({r['where']}): {st_lbl[r['status']]}{(' — ' + r['why']) if r['why'] else ''}" for r in need]
    md += ["", "## Policy conflicts"] + [f"- {f}" for f in flags]
    md += ["", "## Schema requests"] + [f"- **{s['area']}:** {s['ask']}" for s in cfg["schema_requests"]]
    open(os.path.join(out, "build-report.md"), "w", encoding="utf-8").write("\n".join(md) + "\n")


if __name__ == "__main__":
    main()
