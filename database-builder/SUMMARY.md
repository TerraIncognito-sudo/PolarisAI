# Robo-Kit ETF dataset: summary note (version 2026-10-24)

**This is the current dataset for the PolarisAI website.** It replaces `etf_databases_clean_2026-10-21` and earlier versions. It was built from the team's databases of 15 October, re-checked against Yahoo Finance, and tested on a local copy of the website.

## Changed in this version: Canadian size minimum lowered to C$50M

At the team's request, the minimum fund size for **Canadian-listed** ETFs is now **C$50M** (was C$100M). US-listed funds still need US$250M. Of the 66 Canadian funds between C$50M and C$100M, **16 now pass every screen**. The other 50 still fail another rule: 33 trade under 1,000 units a day, 11 have under 3 years of prices, and 6 lack a fee or size. The core list grows from 628 to **650**, and Canadian-listed funds from 238 to **260**.

Notable additions: FLEM (emerging markets, 0.17%; now the Canadian-dollar-only pick), SRII (sustainable international), ZQB (Canadian corporate bonds, 0.11%), QDXB (global bonds), and **ZCLN, a Canadian-dollar clean energy fund**. Default picks are unchanged.

## At a glance

| | |
|---|---|
| ETFs screened | 3,106 |
| Pass all screens (core list) | **650** (260 Canadian-listed) |
| Automated data checks | 33 of 33 pass |
| Website tests | Build, builder walkthrough, ETF browser and engine checks all pass |
| Prices | 3 years of weekly dividend-adjusted closes, complete Friday weeks only |

## Core picks (lowest fee among broad index funds)

| Category | Funds | Pick |
|---|---|---|
| Canadian stocks | 20 | XIC 0.06% |
| US stocks | 80 | VTI 0.03% |
| International stocks | 200 | VEA 0.03% |
| Emerging markets stocks | 91 | VWO 0.06% |
| Canadian bonds | 23 | ZAG 0.09% |
| Canadian short-term bonds | 5 | XSB 0.10% |
| Global bonds | 71 | BNDW 0.05% |

## Website step-4 themes

All 8 now come from the database, with no placeholders:

| Theme | First choice |
|---|---|
| Inflation-protected bonds | XRB |
| Real estate | ZRE |
| Gold | CGL |
| Infrastructure | ZGI |
| Asia-Pacific | VA |
| Energy | XEG |
| Technology | TEC |
| Clean energy | ICLN (ZCLN is now a Canadian-dollar option) |

Crypto add-ons are BTCC.B and FBTC CN, for High-risk clients only and capped at 5%.

## Also in this dataset (since 2026-10-15)

- **8 funds the website needed:** DXC, MKB, XCS, XRB, ZGI, XEG and TEC were added, and ZUAG.F replaces the too-small ZUAG. XEC now qualifies.
- **New columns:**
  - `hedge_currency` (CAD / USD / none). This fixes BNDW and BNDX, which were wrongly marked CAD-hedged.
  - `broad_market` (whole-market index funds).
  - `is_active` (active vs index).
- **New tags and table:** `Gold` and `Asia-Pacific` theme tags, and an `app_theme` table that lists the funds for each website theme.
- **Sustainable and income choices filled:** XESG, ESGC, DRMC (sustainable Canadian stocks), XSAB and XSTB (sustainable Canadian bonds), and VDY, XEI, XDIV, ZDV, XDV, PDC, CDZ (Canadian dividend stocks). Sustainable clients now get a sustainable fund in all 7 categories. See `WEBSITE_FEATURE_COVERAGE.md` for every site choice checked against the data.
- **Payout yields fixed:** 1,116 funds showed a 0% yield because Yahoo had no trailing figure. They now fall back to Yahoo's yield; for example, ZAG shows 3.5%, not "None".
- **Exclusion reasons** corrected where a fund fails a different rule than first recorded.

## Still carried from earlier fixes

- Missing Canadian and US index funds added.
- Funds entered outside the build process were rebuilt through it.
- Category names, regions and fund names cleaned.
- The theme table was rebuilt from evidence (the original is kept as `etf_theme_owner_v1`).
- Leveraged funds excluded.
- Fees and fund sizes Yahoo lacks are filled from issuer sources, listed in `rebuild_scripts/manual_fund_figures.csv` with links and dates.

## Files in this folder

| File | What it's for |
|---|---|
| `etf_core.db`, `etf_context.db`, `etf_prices.db` | The dataset: drop-in replacements for the current files |
| `OWNER_ACTIONS.md` | Full change list, test results, and the decisions still needed |
| `WEBSITE_FEATURE_COVERAGE.md` | Every website choice and feature checked against the data |
| `ETF_List_Additions.xlsx` | 52 funds to add to `ETF List Data.xlsx` for a full rebuild |
| `RoboAdvisor Database builder (patched).ipynb` | The build notebook with the fixes built in |
| `rebuild_scripts/` (in the zip) | The patch script and the sourced figures |

## For the website developer

Update the site the usual way: give Claude the three `.db` files and ask it to "Update PolarisAI with these databases". Then, in the site's config:
- switch ZUAG to ZUAG.F;
- remove DXBB and DXCP from the starter lists (both are too new, and DXBB also trades too thinly);
- optionally, use `broad_market`, `hedge_currency` and `app_theme` instead of guessing from fund names.

## Decisions still open (details in OWNER_ACTIONS.md)

1. Confirm the C$50M minimum is final, and add it to section 5 of the handover doc.
2. Approve the policies: no leveraged funds (the site still offers HSU), and crypto for High-risk clients only (the site offers it to Moderate too).
3. Choose the BTCC units and fee (MER 1.30%, not 1.00%), or switch to FBTC CN at 0.35%.
4. Decide whether to prefer Canadian-listed funds over cheaper US-listed ones.
5. Decide what to do with the "North America" and "Other" funds (47, including XEQT, VEQT and ZEQT).
6. Confirm the figures taken from secondary sources: MNT, TPU, TEC, XEC and ZUAG.F.
7. Move the patch rules into the notebook so a rebuild keeps them.
