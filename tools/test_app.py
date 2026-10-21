"""Headless walkthrough of the PolarisAI builder, including the step 5 engine. Usage: python3 test_app.py http://localhost:8765"""
import sys, json
from playwright.sync_api import sync_playwright

BASE = sys.argv[1].rstrip("/")
errors = []


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
    res = page.evaluate("""()=>{const r=window.PolarisResults;return {tier:r.inputs.tier,cap:r.volCap.value,rec:r.recommended,ms:r.runtimeMs,
      sc:Object.fromEntries(Object.entries(r.scenarios).map(([k,s])=>[k,{ret:+s.stats.ret.toFixed(2),vol:+s.stats.vol.toFixed(2),split:s.split,
        w:s.weights.filter(x=>x.w).map(x=>x.tk+':'+x.w).join(' '),sum:s.weights.reduce((a,x)=>a+x.w,0),
        med10:Object.fromEntries(['mc','boot','hybrid'].map(m=>[m,Math.round(s.sims[m].horizons[10].p50)]))}]))}}""")
    cards = page.eval_on_selector_all("#scen .scard h3", "hs=>hs.map(h=>h.innerText)")
    cmp_rows = page.eval_on_selector_all("#cmp tbody tr", "rs=>rs.map(r=>r.innerText.replace(/\\s+/g,' '))")
    oc = [page.text_content(i) for i in ("#oc-bad", "#oc-med", "#oc-good")]
    # switch method and horizon, choose the other scenario from its dot on the chart
    page.click("#opt .tab[data-m=boot]"); oc_boot = page.text_content("#oc-med")
    page.click("#opt .tab[data-yrs='20']")
    other = "minvar" if res["rec"] == "maxret" else "maxret"
    page.click("#ef .pt[data-sc=%s] circle >> nth=0" % other)
    chosen = page.eval_on_selector("#scen .scard.sel h3", "h=>h.innerText")
    risk = page.text_content("#otbl-h")
    # what if: more money in, one lump sum, compare with the engine, then apply to the plan
    wi0 = page.eval_on_selector_all("#wi-tbl tbody tr", "rs=>rs.map(r=>r.innerText.replace(/\\s+/g,' '))")
    assert all("No change" in r for r in wi0), "what-if starts equal to the plan"
    page.click("#wi .wistep[data-d='1000']")
    page.fill("#wi-camt", "500"); page.select_option("#wi-freq", "monthly")
    page.click("#wi-add"); page.fill("#wi-lumps input >> nth=0", "8000"); page.select_option("#wi-lumps select >> nth=0", "3")
    page.wait_for_timeout(150)
    wi1 = page.eval_on_selector_all("#wi-tbl tbody tr", "rs=>rs.map(r=>r.innerText.replace(/\\s+/g,' '))")
    chk = page.evaluate("""()=>{const r=window.PolarisResults, w=r.whatIf;const y=+document.querySelector('#opt .tab[data-yrs][aria-pressed=true]').dataset.yrs;
      return {put:w.horizons[y].put, med:Math.round(w.horizons[y].p50), cell:document.querySelector('#wi-tbl tbody tr:nth-child(2) td:nth-child(3)').innerText, ms:w.ms}}""")
    page.click("#wi-apply"); page.wait_for_selector("#wi-msg:not([hidden])", timeout=20000)
    applied = page.text_content("#wi-msg")
    wi2 = page.eval_on_selector_all("#wi-tbl tbody tr", "rs=>rs.map(r=>r.innerText.replace(/\\s+/g,' '))")
    assert all("No change" in r for r in wi2), "after applying, the plan equals the what-if"
    page.click("#to-plan")
    page.wait_for_selector("#plan:not([hidden])")
    plan = page.eval_on_selector_all("#ptbl tbody tr", "rs=>rs.map(r=>r.innerText.replace(/\\s+/g,' '))")
    fee = page.text_content("#pl-fee") + " | " + page.text_content("#pl-fee-d")
    pnote = page.text_content("#pl-proj-n")
    changes = page.eval_on_selector_all("#pl-choices li", "ls=>ls.map(l=>l.innerText)")
    assert res["sc"]["minvar"]["sum"] == 100 and res["sc"]["maxret"]["sum"] == 100, "weights must sum to 100"
    assert res["sc"]["minvar"]["vol"] <= res["sc"]["maxret"]["vol"] + 1e-9, "min variance must not be riskier"
    assert res["sc"]["maxret"]["ret"] >= res["sc"]["minvar"]["ret"] - 1e-9, "max return must not earn less"
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
    print("cards:", cards, "| chosen after click:", chosen, "|", risk)
    print("compare:", cmp_rows)
    print("outlook (hybrid, horizon):", oc, "| bootstrap median:", oc_boot)
    print("what-if after changes:", wi1)
    print("what-if check:", chk, "| applied:", applied)
    print("plan:", plan)
    print("plan amounts:", page.text_content("#pl-amt"), "|", page.text_content("#pl-contrib"), "| put in:", page.text_content("#pl-in"))
    print("plan note:", pnote)
    print("changes:", changes)
    print("plan fee:", fee)


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(reduced_motion="reduce", viewport={"width": 1280, "height": 900})
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
    b.close()
print("\nERRORS:", errors or "none")
