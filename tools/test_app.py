"""Headless walkthrough of the PolarisAI builder, including the step 5 risk slider, outlook and report. Usage: python3 test_app.py http://localhost:8765 [light]"""
import sys, json
from playwright.sync_api import sync_playwright

BASE = sys.argv[1].rstrip("/")
errors = []


import re as _re
def _syl(w):
    w = w.lower().strip(".,;:!?()'\"")
    if not w: return 0
    if len(w) <= 3: return 1
    w = _re.sub(r"(?:[^laeiouy]es|ed|[^laeiouy]e)$", "", w); w = _re.sub(r"^y", "", w)
    return max(1, len(_re.findall(r"[aeiouy]{1,2}", w)))
def fk_grade(text):
    """Flesch-Kincaid grade level. Numbers and money count as one-syllable words."""
    sents = [x for x in _re.split(r"[.!?]+(?=\s|$)|\n+", text) if _re.search(r"[A-Za-z]", x)]
    words = _re.findall(r"[A-Za-z][A-Za-z'-]*|\$?[0-9][0-9,.%]*", text)
    syl = sum(_syl(w) if w[0].isalpha() else 1 for w in words)
    return 0.39 * len(words) / max(1, len(sents)) + 11.8 * syl / max(1, len(words)) - 15.59, len(words)

def run(page, loss, time, prefs, label):
    page.goto(BASE + "/app.html")
    page.wait_for_selector("#pform")
    page.fill("#amount", "10000")
    page.click("label[for=c-no]")
    page.click("label[for=%s]" % {"low": "l1", "mod": "l2", "high": "l3"}[loss])
    page.click("label[for=%s]" % {"low": "t1", "mod": "t2", "high": "t3"}[time])
    page.click("#pform [type=submit]")
    page.wait_for_selector("#result:not([hidden])")
    page.click("#to-prefs")
    page.wait_for_timeout(300)
    # set preferences straight on the hidden form, then go to the portfolio
    page.evaluate("""(p)=>{const f=document.getElementById('prefform');
      for(const [n,v] of Object.entries(p)){const x=f.querySelector(`input[name="${n}"][value="${v}"]`); if(x) x.checked=true;}
      f.dispatchEvent(new Event('change',{bubbles:true}));}""", prefs)
    total = page.text_content("#av-total")
    rows = page.eval_on_selector_all("#av-tbl tbody tr", "rs=>rs.map(r=>r.innerText.replace(/\\s+/g,' '))")
    page.evaluate("document.getElementById('to-port').click()")
    page.wait_for_selector("#port:not([hidden])")
    funds = page.eval_on_selector_all("#funds li.fund h3", "hs=>hs.map(h=>h.innerText.replace(/\\s+/g,' '))")
    flags = page.eval_on_selector_all("#funds .flag", "hs=>hs.map(h=>h.innerText)")
    note = page.text_content("#pick-note")
    # open a fund bubble
    page.hover("#funds .ftip >> nth=1"); page.wait_for_selector(".fpop", timeout=3000)
    pop = page.text_content(".fpop")
    page.mouse.move(5, 5); page.wait_for_timeout(700)
    assert page.query_selector(".fpop") is None, "tooltip did not close on mouse out"
    # customize: swap US stocks, add a theme
    page.click("#change-port")
    page.wait_for_selector("#cust:not([hidden])")
    page.click(".howb[data-opt=swap]")
    page.click("#opts .chip >> nth=1")  # US stocks
    swap_opts = page.eval_on_selector_all("#opts .chip", "cs=>cs.map(c=>c.innerText.replace(/\\s+/g,' '))")
    page.hover("#opts .chip >> nth=0"); page.wait_for_selector(".fpop", timeout=3000)
    print("chip tooltip:", page.text_content(".fpop .fpoph")); page.mouse.move(5, 5); page.wait_for_timeout(700)
    page.click("#opts .chip >> nth=0")
    page.click(".howb[data-opt=second]")
    sec_opts = page.eval_on_selector_all("#opts .chip", "cs=>cs.map(c=>c.innerText.replace(/\\s+/g,' '))")
    page.click("#opts .chip.back")
    page.click(".howb[data-opt=theme]")
    theme_opts = page.eval_on_selector_all("#opts .chip", "cs=>cs.map(c=>c.innerText.replace(/\\s+/g,' '))")
    # add the first allowed theme at 5%
    enabled = page.query_selector_all("#opts .chip:not(.dim):not(.back)")
    added = None
    if enabled:
        added = enabled[0].inner_text()
        enabled[0].click(); page.click("#opts .chip >> nth=0")
    cust_rows = page.eval_on_selector_all("#ctbl tbody tr", "rs=>rs.map(r=>r.innerText.replace(/\\s+/g,' '))")
    cust_fee = page.text_content("#cust-fee")
    page.click("#cust-done")
    page.wait_for_selector("#opt-main:not([hidden])", timeout=20000)
    res = page.evaluate("""()=>{const r=window.PolarisResults;return {tier:r.inputs.tier,cap:+r.volCap.value.toFixed(2),start:r.start,ms:r.runtimeMs,months:r.dataWindow.months,
      stops:r.stops.map(s=>({i:s.i,ret:+s.stats.ret.toFixed(2),vol:+s.stats.vol.toFixed(2),S:s.split.S,sum:s.weights.reduce((a,x)=>a+x.w,0),w:s.weights.filter(x=>x.w).map(x=>x.tk+':'+x.w).join(' ')}))}}""")
    sl = lambda: {"val": page.input_value("#risk"), "name": page.text_content("#sl-name"), "pos": page.text_content("#sl-pos"), "stats": page.inner_text("#sl-stats").replace("\n", " ")}
    sl0 = sl(); assert sl0["val"] == "5", "slider starts in the middle"
    caution = page.text_content("#oc-caution"); assert "36 months" in caution, caution
    assert page.query_selector("#opt .tab[data-m]") is None, "only Hybrid on screen"
    oc = [page.text_content(i) for i in ("#oc-bad", "#oc-med", "#oc-good")]
    # keyboard: two stops toward growth
    page.focus("#risk"); page.keyboard.press("ArrowRight"); page.keyboard.press("ArrowRight"); page.wait_for_timeout(150)
    sl7 = sl(); assert sl7["val"] == "7"; oc7 = page.text_content("#oc-med")
    page.click("#opt .tab[data-yrs='20']")
    page.focus("#risk"); page.keyboard.press("Home"); page.keyboard.press("ArrowRight"); page.keyboard.press("ArrowRight"); page.wait_for_timeout(150)
    assert page.input_value("#risk") == "2", "Home and arrow keys move the slider"
    assert page.query_selector("#ef") is None and page.query_selector("#wifan") is None, "one projection chart, no risk-and-return chart on screen"
    assert "risk limit" in page.text_content("#sl-cap").lower(), "the slider card states the risk limit"
    risk = page.text_content("#otbl-h")
    # the report: opens over the page, covers all three methods, closes with Escape
    page.click("#rpt-open"); page.wait_for_selector("#rpt:not([hidden])", timeout=20000)
    rpt = page.inner_text("#rpt-paper")
    for t in ("Part 1", "At a glance", "In a typical future", "In a tough future", "Likely range", "Less likely, but possible", "Part 2", "Your plan explained",
              "What am I invested in?", "How bumpy will the ride be?", "What could my money grow to?", "How sure are these numbers?", "What if a crash hits?",
              "Part 3", "Technical appendix", "Formulas", "Abbreviations", "FP Canada", "hypothetical in nature",
              "Data caution", "36 months", "Monte Carlo", "Bootstrap", "Hybrid", "Sharpe ratio", "Value at Risk", "Minimum Variance", "Maximum Return", "Glossary", "stop 2",
              "For education only", "licensed financial professional", "Stress test details", "Risk and return under stress", "Polaris Outlook under stress"):
        assert t.lower() in rpt.lower(), "report is missing: " + t
    # Parts 1 and 2 read at about grade 8; the headline number matches the appendix
    plain = page.evaluate("()=>[...document.querySelectorAll('#rpt-paper .plain')].map(s=>[...s.querySelectorAll('p,li')].filter(e=>!e.closest('.edu,.warn')).map(e=>e.innerText).join('\\n')).join('\\n')")
    grade, words = fk_grade(plain)
    print("  report Parts 1-2: %d words, grade %.1f" % (words, grade))
    assert grade <= 9.0, "Parts 1 and 2 should read at about grade 8, got %.1f" % grade
    typ = page.eval_on_selector_all("#rpt-paper [data-k=typ]", "es=>es.map(e=>+e.dataset.v)")
    assert len(typ) == 2 and typ[0] == typ[1], "Part 1's typical future matches the appendix: %s" % typ
    assert all(page.query_selector("#rpt-" + a.split("#rpt-")[1]) for a in page.eval_on_selector_all("#rpt-paper a.xref", "es=>es.map(e=>e.getAttribute('href'))")), "every appendix link has a target"
    page.keyboard.press("Escape"); assert page.is_hidden("#rpt"), "Escape closes the report"
    assert "Stress test" not in page.inner_text("#opt"), "the stress test is only in the report"
    # what if (built into the Polaris Outlook): more money in, one lump sum, compare with the engine, then apply
    assert page.is_hidden("#ol-badge") and page.is_hidden("#wi-detail"), "plan view: no what-if badge, details folded"
    assert page.is_hidden("#olq"), "no quote before the client adjusts an amount"
    page.click("#wi-det"); assert page.is_visible("#wi-tbl")
    wi0 = page.eval_on_selector_all("#wi-tbl tbody tr", "rs=>rs.map(r=>r.innerText.replace(/\\s+/g,' '))")
    assert all(r.endswith("—") for r in wi0) and page.is_visible("#wi-hint") and "Nothing to compare yet" in page.text_content("#wi-hint"), "before any change: a dash in the Change column and a hint"
    page.click("#wi .wistep[data-d='1000']")
    page.fill("#wi-camt", "500"); page.select_option("#wi-freq", "monthly")
    page.click("#wi-add"); page.fill("#wi-lumps input >> nth=0", "8000"); page.select_option("#wi-lumps select >> nth=0", "3")
    page.wait_for_timeout(150)
    wi1 = page.eval_on_selector_all("#wi-tbl tbody tr", "rs=>rs.map(r=>r.innerText.replace(/\\s+/g,' '))")
    assert page.is_visible("#ol-badge") and page.is_visible("#fk-plan"), "what-if view: badge and the plan's median line"
    assert "vs your plan" in page.text_content("#oc-med-d"), "tiles show the change from the plan"
    assert page.text_content("#oc-med") == page.text_content("#wi-tbl tbody tr:nth-child(2) td:nth-child(3)"), "tile and table agree"
    # the report ignores unsaved what-if amounts: same content as before, plus a reminder in the popup
    page.click("#rpt-open"); page.wait_for_selector("#rpt:not([hidden])", timeout=20000)
    rpt_b = page.inner_text("#rpt-paper")
    assert rpt_b.split("Report ID")[0] == rpt.split("Report ID")[0], "the report is unchanged by what-if amounts"
    assert "uses the amounts in your plan" in page.text_content("#rpt-msg"), "the popup says the report uses the plan's amounts"
    page.keyboard.press("Escape")
    chk = page.evaluate("""()=>{const r=window.PolarisResults, w=r.whatIf;const y=+document.querySelector('#opt .tab[data-yrs][aria-pressed=true]').dataset.yrs;
      return {put:w.horizons[y].put, med:Math.round(w.horizons[y].p50), cell:document.querySelector('#wi-tbl tbody tr:nth-child(2) td:nth-child(3)').innerText, ms:w.ms}}""")
    page.click("#wi-apply"); page.wait_for_selector("#wi-msg:not([hidden])", timeout=20000)
    applied = page.text_content("#wi-msg")
    wi2 = page.eval_on_selector_all("#wi-tbl tbody tr", "rs=>rs.map(r=>r.innerText.replace(/\\s+/g,' '))")
    assert "Your original amounts" in page.text_content("#wi-tbl thead") and "Your plan now" in page.text_content("#wi-tbl thead"), "after saving, the table compares the plan with the original amounts"
    assert not any(r.endswith("No change") or r.endswith("—") for r in wi2[:5]), "after saving, the Change column shows the difference from the original amounts: %s" % wi2
    assert "vs your original amounts" in page.text_content("#oc-med-d"), "tiles show the change from the original amounts"
    print("after saving:", wi2[1])
    assert page.is_hidden("#ol-badge"), "after applying, the chart is the plan again"
    # a quote fills the room the longer controls leave under the chart, matched to the risk level, without making the card taller
    page.wait_for_timeout(200)
    hq = page.evaluate("[document.querySelector('.olchart').offsetHeight, document.getElementById('wi').offsetHeight]")
    assert page.is_visible("#olq"), "a quote shows in the space under the chart: %s" % hq
    assert hq[0] <= hq[1] + 2, "the quote fits beside the controls: %s" % hq
    kick = {"low": "steady", "mod": "balanced", "high": "growth"}[page.evaluate("window.PolarisResults.inputs.tier")]
    assert kick in page.text_content("#olq-kick").lower() and page.text_content("#olq-by").startswith("—"), "the quote fits the risk level and names its author"
    print("quote:", page.text_content("#olq-kick"), "|", page.text_content("#olq-by"))
    page.click("#to-plan")
    page.wait_for_selector("#plan:not([hidden])")
    plan = page.eval_on_selector_all("#ptbl tbody tr", "rs=>rs.map(r=>r.innerText.replace(/\\s+/g,' '))")
    fee = page.text_content("#pl-fee") + " | " + page.text_content("#pl-fee-d")
    pnote = page.text_content("#pl-proj-n")
    changes = page.eval_on_selector_all("#pl-choices li", "ls=>ls.map(l=>l.innerText)")
    st = res["stops"]
    assert all(x["sum"] == 100 for x in st), "weights must sum to 100 at every stop"
    assert all(st[k]["vol"] >= st[k - 1]["vol"] - 0.02 and st[k]["ret"] >= st[k - 1]["ret"] - 0.02 for k in range(1, len(st))), "return and volatility rise along the slider"
    print(f"\n===== {label}  (loss={loss}, time={time}, prefs={prefs})")
    print("available:", total, rows)
    print("core funds:", funds)
    print("flags:", flags)
    print("pick-note:", note[:160])
    print("bubble:", pop[:500].replace("\n", " | "))
    print("swap options:", swap_opts)
    print("second-fund categories:", sec_opts)
    print("themes:", theme_opts, "added:", added)
    print("customize:", cust_rows)
    print("cust fee:", cust_fee)
    print("engine:", json.dumps(res))
    print("slider at start:", sl0, "| after 2 x ArrowRight:", sl7, "| table:", risk)
    print("outlook (hybrid):", oc, "| median at stop 7:", oc7)
    print("caution:", caution)
    print("report:", len(rpt), "characters;", rpt[:600].replace("\n", " | "))
    print("what-if after changes:", wi1)
    print("what-if check:", chk, "| applied:", applied)
    print("plan:", plan)
    print("plan amounts:", page.text_content("#pl-amt"), "|", page.text_content("#pl-contrib"), "| put in:", page.text_content("#pl-in"))
    print("plan note:", pnote)
    print("changes:", changes)
    print("plan fee:", fee)
    # back in step 5: restore the amounts entered in step 1
    page.click("#back-plan"); page.wait_for_selector("#opt:not([hidden])")
    assert page.is_visible("#wi-orig-box"), "after saving new amounts, the restore button shows"
    orig_note = page.text_content("#wi-orig-n")
    page.click("#wi-orig"); page.wait_for_function("document.getElementById('wi-msg').textContent.includes('original amounts')", timeout=20000)
    assert page.input_value("#amount") == "10,000" and page.is_checked("#c-no"), "step 1 amounts restored"
    assert page.is_hidden("#wi-orig-box"), "restore button hides once the plan matches the original amounts"
    assert page.is_visible("#wi-hint") and "Nothing to compare yet" in page.text_content("#wi-hint"), "after restoring, nothing to compare"
    assert page.text_content("#oc-in") == "$10,000", "the outlook uses the original amounts again"
    page.click("#to-plan"); page.wait_for_selector("#plan:not([hidden])")
    restored = page.eval_on_selector_all("#pl-choices li", "ls=>ls.map(l=>l.innerText)")
    assert not any("Changed your amounts" in c for c in restored), "the plan no longer lists changed amounts"
    print("restore:", orig_note, "->", page.text_content("#pl-amt"), page.text_content("#pl-in"))


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(reduced_motion="reduce", viewport={"width": 1280, "height": 900})
    if len(sys.argv) > 2:  # e.g. light: run the whole walkthrough in that theme
        ctx.add_init_script("try{if(!localStorage.getItem('polaris-theme'))localStorage.setItem('polaris-theme','%s')}catch(e){}" % sys.argv[2])
    page = ctx.new_page()
    page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    run(page, "mod", "high", {"region": "none", "sus": "none", "inc": "none", "bond": "none", "cad": "none"}, "Moderate, no preferences")
    run(page, "high", "high", {"region": "canada", "sus": "none", "inc": "income", "bond": "income", "cad": "yes"}, "High, Canada + income + CAD only")
    run(page, "low", "low", {"region": "global", "sus": "yes", "inc": "none", "bond": "steady", "cad": "none"}, "Low, sustainable")
    # real chat flow in step 2
    page.goto(BASE + "/app.html"); page.wait_for_selector("#pform")
    page.fill("#amount", "25000"); page.click("label[for=c-no]"); page.click("label[for=l2]"); page.click("label[for=t2]")
    page.click("#pform [type=submit]"); page.click("#to-prefs"); page.wait_for_selector("#pc-chips .pchip.pick")
    page.click("#pc-chips .pchip.pick[data-k=sus]"); page.click("#pc-chips .pchip.pick[data-k=cad]")
    print("\nchat counts:", page.text_content("#av-total"), page.eval_on_selector_all("#av-tbl tbody tr", "rs=>rs.map(r=>r.innerText.replace(/\\s+/g,' '))"))
    page.click("#pc-chips .pchip.go"); page.wait_for_timeout(400)
    print("chat log:", page.inner_text("#pc-log")[-700:].replace("\n"," | "))
    page.click("#pc-chips .pchip.go"); page.wait_for_selector("#port:not([hidden])")
    print("chat portfolio:", page.eval_on_selector_all("#funds li.fund h3", "hs=>hs.map(h=>h.innerText.replace(/\\s+/g,' '))"))
    for q in page.query_selector_all("#opts .chip"):
        q.click()
    print("navigator answers:", page.inner_text("#log")[:900].replace("\n"," | "))
    # tracker jump: from step 3 straight to the plan (engine runs on demand)
    page.click("#keep-port"); page.wait_for_selector("#opt-main:not([hidden])", timeout=20000)
    page.click("#st3"); page.click("#st6"); page.wait_for_selector("#plan:not([hidden])", timeout=20000)
    print("tracker jump plan:", page.text_content("#pl-med"), page.text_content("#pl-proj-h"))
    # education notice: on every page, telling people to see a licensed professional before buying
    for pg in ("index", "app", "browser", "data-status"):
        page.goto(BASE + "/" + pg + ".html")
        t = page.inner_text(".edu-note")
        assert "For education only" in t and "licensed financial professional" in t, pg + ": education notice missing"
    print("education notice: on all 4 pages")
    # phone: the amount controls fold under the chart
    page.set_viewport_size({"width": 390, "height": 844}); page.goto(BASE + "/app.html"); page.wait_for_selector("#pform")
    page.click("#keep-port") if page.is_visible("#keep-port") else None
    page.fill("#amount", "10000"); page.click("label[for=c-no]"); page.click("label[for=l2]"); page.click("label[for=t2]"); page.click("#pform [type=submit]")
    page.wait_for_selector("#result:not([hidden])"); page.click("#to-prefs"); page.wait_for_timeout(300)
    page.evaluate("document.getElementById('to-port').click()"); page.wait_for_selector("#port:not([hidden])")
    page.click("#keep-port"); page.wait_for_selector("#opt-main:not([hidden])", timeout=20000)
    assert page.is_hidden("#adj-body") and page.is_visible("#adj-tog"), "phone: controls folded"
    page.click("#adj-tog"); assert page.is_visible("#wi-start"), "phone: controls open"
    page.click("#wi .wistep[data-d='1000']"); page.wait_for_timeout(200); assert page.is_hidden("#olq"), "phone: no quote (no room beside the chart)"
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "phone: no sideways scroll"
    print("phone: amount controls fold and open")
    page.set_viewport_size({"width": 1280, "height": 900})
    # theme switch: flips the page, is remembered on the next page, and flips back
    page.goto(BASE + "/index.html"); start = page.evaluate("document.documentElement.getAttribute('data-ptheme')")
    page.click(".theme-btn"); now = page.evaluate("document.documentElement.getAttribute('data-ptheme')")
    assert (start == "light") != (now == "light"), "the switch changes the theme"
    page.goto(BASE + "/browser.html"); assert page.evaluate("document.documentElement.getAttribute('data-ptheme')") == now, "theme carries to the next page"
    # the Claude app marks pages with its own data-theme; the site must ignore it
    page.evaluate("document.documentElement.setAttribute('data-theme', document.documentElement.getAttribute('data-ptheme')==='light'?'dark':'light')"); page.wait_for_timeout(100)
    assert page.evaluate("document.documentElement.getAttribute('data-ptheme')") == now, "the host app's theme marker does not change the site's theme"
    lbl = page.text_content(".theme-btn .theme-lbl"); moon = page.is_visible(".theme-btn .ti-moon")
    assert (lbl == "Dark") == moon, "the theme button's icon and label agree: %s, moon %s" % (lbl, moon)
    assert page.get_attribute(".theme-btn", "aria-pressed") == ("true" if now == "light" else "false")
    page.click(".theme-btn"); assert page.evaluate("document.documentElement.getAttribute('data-ptheme')") == start
    print("theme switch:", start or "dark", "->", now or "dark", "-> back: ok")
    b.close()
print("\nERRORS:", errors or "none")
