# PolarisAI website: feature coverage check against the 2026-10-24 dataset

Checked on 21 October 2026 and re-run on 24 October against this version (Canadian size minimum C$50M). Every client choice and data-driven feature in the builder (`app.html`), the ETF browser (`browser.html`) and the step 4 customize menu was mapped to the database. The site's own tests (`test_app.py`, `test_browser.py`, `test_engine.py`) were run on a local copy built from this dataset, and all passed with no page errors.

**Legend:** ✅ supported by the data · ⚠️ supported with a known limit · ❌ not supported by the data

## Step 1–2: client choices

| Choice on the site | What it needs from the data | Status |
|---|---|---|
| Risk level (loss tolerance, time horizon) | `risk_tier` on every fund | ✅ Every core category has Low/Medium funds; High clients see all |
| Canadian-dollar ETFs only | `currency` | ✅ A CAD fund in every core category |
| Region: more Canada / around the world | Weighting only | ✅ Needs no extra data |
| Sustainable funds | `is_esg` or an ESG tag, per category | ✅ Now in all 7 core categories. Added XESG, ESGC, DRMC (Canadian stocks), XSAB (Canadian bonds) and XSTB (short-term bonds) |
| Income (dividend-paying stocks) | `income` or the High Dividend tag | ✅ All 4 stock categories. Added VDY, XEI, ZDV, XDV, PDC, CDZ and XDIV (Canadian stocks) |
| Sustainable **and** income together | Both flags on one fund | ⚠️ No usable fund exists. The only ESG dividend ETFs (CI, about C$15–18M) are below the size minimum. The site falls back to a regular fund and flags it, as designed |
| Bonds: steadier / more income | Weighting between short-term and all-maturity bonds | ✅ Needs no extra data |
| "Use a regular fund / leave it out" fallback | Fallback when a category has no match | ✅ Now needed in 16 of the 112 category checks (was 32); all 16 are sustainable + income |

## Step 4: customize

| Option | Site's fund | Status | Notes |
|---|---|---|---|
| Swap a core fund | Config lists 17 funds | ⚠️ 14 resolve from the database | DXBB, DXCP and ZUAG fail the screens. Suggested replacements: VAB or XBB (Canadian bonds), VSB or ZSB (short-term), ZUAG.F (global bonds) |
| Add a second fund | Config lists 8 funds | ⚠️ 6 resolve | DXCP and ZUAG as above. Short-term bonds has no second fund in the config; VSB or ZSB would fill it |
| Theme: Inflation-protected bonds | XRB | ✅ | Low tier, matches the site. Also QTIP, XSTP, XSTH |
| Theme: Real estate | ZRE | ✅ | VRE is cheaper (0.39% vs 0.61%) |
| Theme: Gold | CGL | ✅ | New `Gold` tag. Also MNT |
| Theme: Infrastructure | ZGI | ✅ | Newly added |
| Theme: Asia-Pacific | VA | ✅ | New `Asia-Pacific` tag; 48 funds |
| Theme: Energy and natural resources | XEG | ✅ | Newly added; High tier, matches the site |
| Theme: Technology (including AI) | TEC | ✅ | Newly added. Also XIT, XLK and the AI funds (BOTZ, AIQ, CHAT, ROBO) |
| Theme: Clean energy | ICLN (US$) | ✅ | With the C$50M minimum, **ZCLN (C$75M, 0.39%) now qualifies**. The site can offer it to Canadian-dollar-only clients (its config currently lists ICLN only) |
| High-risk: Cryptocurrency | BTCC (manual entry) | ⚠️ | In the database as BTCC/B CN (MER 1.30%; the site uses 1.00%). FBTC CN is cheaper at 0.35%. Policy: High only (site offers Moderate too) |
| High-risk: Leveraged US stocks | HSU (manual entry) | ❌ by policy | Leveraged funds are excluded from the database. The team needs to decide whether to keep HSU as a manual exception |

Every theme fund's risk tier in the database matches the tier the site assumes.

## ETF browser

| Feature | Status |
|---|---|
| Fund count, category tiles, risk, listing, fund-family filters | ✅ 650 eligible of 3,106 screened |
| Broad / Canadian-dollar / ESG / Income toggles | ✅ |
| Theme drop-down | ✅ 23 tag labels in 5 dimensions, rebuilt from evidence (Gold and Asia-Pacific included) |
| Fund details: description, fee, size, yield, returns, risk | ✅ Every core fund has a description. Payout yields fixed (were showing "None" for 404 funds) |
| Compare and correlation | ✅ Weekly prices on the same Friday weeks for every fund |

## New data the site can start using (developer)

- `broad_market`: whole-market index funds. Can replace the site's name-keyword rules.
- `hedge_currency` (CAD / USD / none): fixes BNDW and BNDX, which showed as CAD-hedged.
- `is_active`: index vs actively managed.
- `app_theme`: the funds that qualify for each of the 8 step 4 themes (108 rows).

## Needs a decision

1. Replacements for DXBB, DXCP and ZUAG in the swap and second-fund lists (suggestions above).
2. Clean energy for Canadian-dollar-only clients: add ZCLN to the site's theme option (now eligible).
3. Sustainable + income clients: keep the current fallback, or treat it as "sustainable first".
4. BTCC units and fee, or switch to FBTC CN. Crypto for Moderate clients or High only.
5. HSU: keep as an exception or remove.
