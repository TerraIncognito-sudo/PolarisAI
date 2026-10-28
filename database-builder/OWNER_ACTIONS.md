# Robo-Kit ETF databases: clean version 2026-10-24

Prepared 24 October 2026. This replaces `etf_databases_clean_2026-10-21` (and 10-15). It's built from the same source files (`etf_core (1).db` and the rest), with every fix from the 15 October version plus the data the website's "fund data status" page asked for. The source files are unchanged.

## Changed on 24 October: Canadian size minimum C$100M → C$50M

- **Rule:** Canadian-listed ETFs now need **C$50M** in assets (US-listed: US$250M, unchanged). The rule is set in `patch_etf_databases.py` (`CA_MIN_AUM`), in the patched notebook's exclusion cell, and in the `exclusion_rules` meta text of both databases.
- **Effect:** every Canadian fund previously excluded for size was re-checked against all remaining rules, with prices pulled for those that could pass. 16 of the 66 funds between C$50M and C$100M now qualify. The other 50 still fail volume (33), price history (11) or missing figures (6). Core list: 628 → **650**; Canadian-listed: 238 → **260**; none removed.
- **New in the core list:** ZQB, CCNS, HYBR, BEPR, XSE (Canadian bonds); FLEM (emerging markets); HTB, SPAY, QDXB, HAF (global bonds); SRII, DRMD (international); ZLH, TULV, NUSA, XSMH, XVLU (US stocks); TGRE (real estate); ZCLN (clean energy); CGLO, GDIV, MDIV (Other).
- **Picks that change:** Canadian-dollar-only emerging markets FLEM (0.17%) instead of HXEM (0.25%); sustainable Canadian-dollar-only international SRII instead of XDSR. Default picks are unchanged.
- **New audit checks (3):** no Canadian core fund under C$50M, no US core fund under US$250M, and no Canadian fund marked "below size minimum" while above C$50M.
- **Trade-off:** smaller funds tend to have wider bid-ask spreads and a higher chance of being closed. The 1,000-units-a-day volume rule still applies and is now the main filter on the Canadian side. Lowering it would admit more funds, but those funds are harder to trade.

## Result

**650 core funds.** All 33 automated checks pass. These are the 20 from the last version plus 10 new ones covering the new columns, the website theme lists, and a broad fund in every core category.

| Category | Funds | Broad-market funds | Cheapest broad fund |
|---|---|---|---|
| Canadian stocks | 20 | 9 | XIC 0.06% |
| US stocks | 80 | 47 | VTI 0.03% |
| International stocks | 200 | 49 | VEA 0.03% |
| Emerging markets stocks | 91 | 27 | VWO 0.06% |
| Canadian bonds (all maturities) | 23 | 4 | ZAG 0.09% |
| Canadian short-term bonds | 5 | 4 | XSB 0.10% |
| Global bonds (incl. US) | 71 | 18 | BNDW 0.05% |

## New in this version (from the website's data status page)

1. **Funds the site uses that were missing.** These were added through the same pipeline as every other fund, and all qualify: DXC, MKB, XCS, XRB, ZGI, XEG, TEC.
2. **ZUAG:** the CAD units hold only C$8M, so they fail the C$50M minimum. The hedged units **ZUAG/F CN** (C$1.4B, 0.09%) were added and qualify. The site should use ZUAG.F.
3. **XEC** now qualifies with a sourced fund size (C$4.3B).
4. **New columns** in `etf` (core) and `etf_universe` (context):
   - **`hedge_currency`** (`CAD` / `USD` / `none`). `cad_hedged` is now 1 only for CAD hedging. **BNDW and BNDX were wrongly marked as CAD-hedged; they're hedged to US dollars.**
   - **`broad_market`** (1 = whole-market index fund). It's set only for index funds in the seven core categories, with no sector, theme or factor tag, and nothing in the name about a single country, target maturity, credit segment or strategy. ESG-screened broad funds still count, because the site has its own Sustainable column. Every core category has at least 3.
   - **`is_active`** (1 = actively managed, 0 = tracks an index, blank = unknown). It's read from Yahoo's description first, then the fund name. 171 core funds stay blank because neither says.
5. **Theme tags:** `Gold` and `Asia-Pacific` were added to `etf_theme`.
6. **New `app_theme` table**, one row per website step-4 theme and fund, eligible funds only in the core file:

| Website theme | Funds | Examples |
|---|---|---|
| Inflation-protected bonds | 5 | XRB, XSTP, QTIP |
| Real estate | 30 | ZRE, VRE, XRE |
| Gold | 12 | CGL, MNT, GLD (bullion only) |
| Infrastructure | 2 | ZGI, SRVR |
| Asia-Pacific | 48 | VA, XCH, ZJPN |
| Energy | 1 | XEG |
| Technology | 8 | TEC, XIT, XLK |
| Clean energy | 4 | ICLN, TAN, QCLN, ZCLN (C$) |

7. **Exclusion reasons corrected** where a re-check found the figures but another rule still fails. For example, ZUAG CN is now "below size minimum" rather than "missing key figures".
8. **Payout yields fixed.** Yahoo's trailing yield was stored as 0 for 1,116 funds (404 of them eligible) that do pay, such as BNDX 4.7%, ZAG 3.5% and ZUD 1.6%. The 0 means Yahoo had no trailing figure. Those values are now blank, so readers fall back to Yahoo's `yield`. The website had been showing "None" for payouts on these funds. Funds that truly pay nothing (gold, Global X corporate-class funds) keep 0.

9. **Sustainable and income choices on the website filled.** The site's Sustainable and Income preferences had no Canadian funds to pick from, because the source list has none. Added: XESG, ESGC, DRMC (sustainable Canadian stocks; ESGA fails the volume rule), XSAB and XSTB (sustainable Canadian bonds), and VDY, XEI, XDIV, ZDV, XDV, PDC, CDZ (Canadian dividend stocks). The site's "regular fund" fallbacks drop from 32 to 16; the remaining 16 are sustainable + income, which no usable fund offers. Details in `WEBSITE_FEATURE_COVERAGE.md`.

## Tested on a local copy of the website (re-run 24 October on this version)

The site's own update steps were run against this folder, without publishing anything:
- `build_etf_data.py` ran with no errors and resolved 8 of the site's placeholder funds (DXC, MKB, TEC, XCS, XEC, XEG, XRB, ZGI). The status page went from 7 funds missing from the database to 0.
- `test_app.py`, the full builder walkthrough (3 client profiles, chat, customize, engine, what-if, plan), passed with no page errors. All 8 step-4 themes now offer real database funds.
- `test_browser.py`, the ETF browser (650 eligible, 3,106 screened, filters, compare, details, mobile), passed with no errors.
- `test_engine.py`'s simulations and what-if checks passed. Its optimizer comparison was skipped because `cvxpy` isn't installed.
- Default picks are unchanged (XIC, VTI, VEA, VWO, ZAG, XSB, BNDW). With "Canadian-dollar only", global bonds now picks ZUAG.F instead of XAGG.

**Note:** funds added or re-pulled in this patch have prices to 16 Oct; the rest end on 9 Oct, the last week of the original pull. The site handles this, because correlations use shared weeks only. A full price refresh in the next build will line them up.

## For the website developer

- Rebuild the site's data from this folder. The site's own steps: give Claude the three `.db` files and ask it to "Update PolarisAI with these databases".
- The site can now use `broad_market`, `hedge_currency`, `is_active` and `app_theme` instead of guessing from fund names.
- **Remove DXCP and DXBB from the site's starter lists.** Both launched in late 2024, so they have under 3 years of prices, and DXBB also trades too thinly. **Switch ZUAG to ZUAG.F.**
- HSU and BTCC are still team decisions (see below).

## Needs the owner's decision or action

1. **Adopt this version** and confirm the C$50M Canadian minimum is final (update section 5 of the handover doc). Use these files, or rebuild:
   - copy the `Additions` sheet (52 funds) into `ETF List Data.xlsx`;
   - put `manual_fund_figures.csv` next to the notebook;
   - run `RoboAdvisor Database builder (patched).ipynb`.

   Add new funds through the `Additions` sheet, not by writing rows straight into the databases.
2. **Builder v5 (`etf_master.db`)** isn't used here. It held only 32 funds, applied no screening rules, and its single-file layout doesn't match what the website reads. Its useful ideas (gold and Asia-Pacific themes) are in this version.
3. **Move the rules into the notebook.** `THEME_RULES`, `APP_THEMES` and the `derive_columns` logic live in `patch_etf_databases.py`, so a rebuild from the notebook alone loses `etf_theme`, `app_theme` and the three new columns.
4. **Approve two policies:**
   - **Leveraged funds:** excluded. The site still offers HSU (2× leveraged) as a manual exception.
   - **Crypto:** the database allows High-risk clients only, capped at 5%, but the site offers it to Moderate clients too. The site also uses BTCC at 1.00%, which is the management fee; its MER is 1.30%. FBTC CN (0.35%) is the cheapest eligible bitcoin fund.
5. **Confirm the figures from secondary sources:**
   - MNT's fee;
   - TPU's, TEC's and XEC's fund sizes (Pensions & Investments);
   - ZUAG.F's fund size (Cboe).

   MNT is an exchange-traded receipt rather than an ETF.
6. **Decide whether to prefer Canadian-listed funds** (VTI at 0.03% USD beats CUEI at 0.06% CAD).
7. **Check Fidelity, CI and RBC "Fund/ETF" fund sizes**, which probably include mutual-fund units.
8. **"North America" and "Other" (47 funds, including XEQT, VEQT and ZEQT)** still need a decision.
9. **Thin website themes:** Energy has 1 fund (XEG) and Infrastructure 2. US energy and infrastructure funds (e.g. XLE, IGF) aren't in the source list. Add them to the `Additions` sheet if the site needs more choice.
10. **Next refresh:** IBIT, FBTC US and VGSR qualify on their own as their price history grows.
