# Updating PolarisAI fund data

PolarisAI reads all fund figures from generated data files, built from the team's three fund databases by `tools/build_etf_data.py`:

| File | Used by |
|---|---|
| `etf-data.js` | Landing page (`index.html`) and portfolio builder (`app.html`): picks, counts, fund details and hover tooltips |
| `etf-browser-data.js` | ETF browser (`browser.html`): all screened funds, eligible and excluded |
| `etf-browser-prices.js` | ETF browser compare view, and the Bootstrap and Hybrid simulations in step 5 of the builder: weekly returns, loaded only when needed |
| `data-status.html` | The team's status page, linked from the About section |

The pages themselves never need editing for a data update.

## What the team does

1. Rebuild the databases as usual (`etf_core.db`, `etf_context.db`, `etf_prices.db`).
2. Open a chat with Claude, attach all three files, and say: **"Update PolarisAI with these databases"**. Include the artifact link: https://claude.ai/code/artifact/fc7710af-02aa-4bc0-be16-796943dedb9c
3. Claude replies with a change report: new as-of date, picks that changed, fee changes, and placeholders that are now resolved. Then it republishes the site.
4. Check `data-status.html` on the site for anything still needed in the next database build.

## What Claude does (step by step)

1. Read the published files from the artifact: `tools/build_etf_data.py`, `tools/polaris-config.json`, the current `etf-data.js` (saved as the "previous" file for the change report) and the current `data-status.html` (the status-page template).
2. Run:
   ```
   python3 build_etf_data.py --core etf_core.db --context etf_context.db \
       --prices etf_prices.db --config polaris-config.json --out site \
       --previous previous-etf-data.js --status-template data-status.html
   ```
   `--status-template` keeps the published status page's education notice, theme switch, Back button, footer notice and light-theme blocks, and puts the new tables inside them. Without it the script writes a bare page (and says so).
   The script stops with a clear error if a table or column it needs is missing, or if a core category has no eligible funds.
3. Optional: run `tools/test_app.py` against a local copy of the site to walk through every step of the builder, and `tools/test_engine.py site` to check the optimizer and simulations against independent implementations.
4. Republish the artifact with only the four generated files changed (`etf-data.js`, `etf-browser-data.js`, `etf-browser-prices.js`, `data-status.html`). `index.html`, `app.html`, `polaris-engine.js`, `browser.html` and the audio files stay as they are.
5. Share `build-report.md` (the change report) in the chat.

## What the script checks and uses

| Database | Used for |
|---|---|
| `etf_core.db` → `etf`, `etf_theme`, `meta`, `allocation_policy` | Eligible funds, fees, size, risk tier, ESG and income flags, theme tags, as-of date, crypto policy |
| `etf_context.db` → `etf_universe`, `etf_profile`, `etf_metrics`, `etf_theme`, `yahoo_raw` | Every screened fund for the browser, why a fund was excluded, descriptions, Morningstar category, Sharpe, beta, 52-week range, drawdown, yield, price, P/E, volume, launch date |
| `etf_prices.db` → `price_weekly`, `meta` | 1- and 3-year returns, calendar-year returns, and correlations between funds |

## Rules that live in `polaris-config.json`

- **Core picks:** the lowest MER among *broad* funds in each category that fit the risk level and preferences, with ties going to the larger fund. US-listed funds are allowed unless the client picks "Canadian-dollar ETFs only". Risk level: Low and Moderate clients see Low- and Medium-tier funds, and High clients see all.
- **Broad fund rules:** exclude sector, theme and factor tags, plus some fund-name keywords (single countries, target-maturity bonds and similar). Remove this once the database has a `broad_market` flag.
- **Step 4 starter lists (swaps, second funds, themes, high-risk):** placeholders. A ticker missing from the database keeps the fee written in the config and shows a "Placeholder" tag. Once the database carries it, the database figures take over automatically.
- **Expected returns per category:** set assumptions. Volatility and correlation always come from prices.
- **High-risk ETFs (`extras`):** two bitcoin ETFs from the database, FBTC CN and BTCC/B CN, offered at Moderate and High; a client can hold one, at 5%. No leveraged funds (HSU was removed on Oct. 25, 2026).
- **Settled decisions (`policy_decisions`):** shown on the status page under "Decisions made" instead of as conflicts. The crypto risk levels are one of them.

To change a rule or a placeholder, edit `polaris-config.json` and rerun the script.

## The optimizer and simulation engine (`polaris-engine.js`)

Step 5 of the builder ("Build and look ahead") runs `polaris-engine.js`. It reads only the generated data files, so a data update needs no engine changes.

**What it does**

1. **Model.** Expected return per fund = the category assumption in `polaris-config.json` minus the fund's MER (satellites use their own assumption). Volatility and correlation come from the weekly prices in `etf-data.js`. Placeholder funds use the config's fallback volatility and the builder's usual correlation rules.
2. **The risk slider: 11 stops.**
   - *Stop 0, Minimum Variance* ("Steadiest mix"): the lowest-volatility weights.
   - *Stop 10, Maximum Return* ("Highest expected growth"): the highest expected return whose volatility stays at or below the risk limit. The risk limit is the volatility of the tier's boldest reference mix: the top of its Stock ETF band, split the builder's usual way, using the client's own funds.
   - *Stops 1–9*: evenly spaced volatility targets between the two ends. Each takes the highest expected return at its target, with a small penalty for distance from the straight blend of the two ends' weights (`CFG.smooth` × the funds' average variance). Without it, weights can jump between near-identical funds from stop to stop; with it, no fund moves more than about 7 points between neighbouring stops, and the most any stop gives up against the exact frontier is under 0.2 points of expected return (median 0.04). Both ends stay exact.
   - Every stop keeps 5–40% per core category (emerging markets at most 15%), the tier's Stock ETF band (Low 20–40%, Moderate 50–70%, High 75–95%, including stock satellites), satellites at their chosen weight, and at least 3% in each fund when a category has two funds. At a High risk level a bond category may go to 0%.
   - Solver: a convex QP solver (ADMM with exact active-set polishing). Targets are hit by bisection on the return/risk trade-off. Weights are rounded to whole percents without breaking any limit.
   - The slider starts in the middle (`CFG.startStop`, stop 5). Sharpe ratios use `CFG.riskFree` (2.50%, the 3-month Government of Canada treasury bill on Oct. 22, 2026; update it with the data).
3. **Three simulation methods**, run per stop on demand (`PolarisEngine.sims(stop, method)`, about 60 ms each, cached). Each runs 2,000 futures for 20 years in weekly steps, with the client's contributions. All stops and methods share random draws.
   - *Monte Carlo*: normal weekly log-returns from the expected return and the portfolio volatility.
   - *Bootstrap*: the portfolio's real weekly returns over the price window, replayed with a stationary block bootstrap (blocks of about 6 weeks on average). It inherits that window's returns, so it reads as optimistic when the last 3 years were strong.
   - *Hybrid* (the only method on screen): Bootstrap's real weekly shocks, re-centred on the forward-looking expected return.
   - Funds without price history get a stand-in history: a related fund's returns scaled to the fund's volatility and correlation, centred on its expected return, plus seeded noise.
   - Each projection also gives one-year Value at Risk and Conditional Value at Risk at 95%.
4. **Shared results state.** Every run is published as `window.PolarisResults` (plus a `polaris:results` event and `PolarisEngine.subscribe(fn)`): inputs, settings, risk limit, frontier, the data window (`dataWindow`: price dates and months, used for the data caution), and for each stop its weights, return, volatility, Sharpe ratio, fee, split, look-back statistics (return, volatility, maximum drawdown, beta against XIC and ACWI, skewness, kurtosis) and any projections computed so far.
5. **The report.** `PolarisEngine.report(stop)` gathers the chosen stop and both ends with all three methods, correlations and diversification ratios (about 0.7 s). Step 5 and the plan open it as a popup in three parts (`buildReport()` in app.html). **Part 1, At a glance** (one printed page): rounded typical, tough (1 in 20) and great futures and the money put in, a simple chart labelled "Likely range" (middle half) and "Less likely, but possible" (9 in 10), the mix, a bad year in dollars, fees, the crash in one line, a short education notice and a two-line data caution. **Part 2, Your plan explained**: question headings (What am I invested in? How bumpy will the ride be? What could my money grow to? How sure are these numbers? What if a crash hits? What should I do next?), each with a picture or small table and two to four plain points; methods use plain names (Our main method = Hybrid, Smooth model = Monte Carlo, Past replay = Bootstrap). Each section links to its appendix section ("Details: A3"). **Part 3, Technical appendix**: A1 portfolio, A2 slider and frontier, A3 the 27-row comparison and fund weights, A4 all three methods, A5 stress-test details, A6 correlations, A7 assumptions beside the FP Canada / IFP 2026 guidelines and the data window, A8 method, A9 formulas with one-line meanings, A10 abbreviations, A11 glossary, A12 important information (hypothetical results, results may vary, limits, investments covered), then the full education notice. Charts label their own lines: `endLabels()` writes each line's value at its right end without overlaps and `chartLegend()` draws a key inside the chart. The Part 2 methods chart shows each method's typical future, its gap to the main method and the tough and great ends; appendix A4 has the labelled fan chart (`rptFan`, 5th/25th/median/75th/95th and money put in) and the three methods side by side (`rptMethodLines`, each median with its difference from the main method; a line far above the others is cut at the top and labelled "off the chart"). Keep Parts 1 and 2 short and plain (about grade 8, sentences under about 20 words, "you" voice); put new technical detail in the appendix. `tools/test_app.py` checks the headings, a Flesch-Kincaid grade of 9 or lower for Parts 1 and 2, that Part 1's typical future equals the appendix median (`data-k="typ"`), and that every appendix link has a target. "Print / Save as PDF" uses the browser's print dialog (print styles hide the rest of the page); if the embedded view blocks printing, it says so and points to "Download HTML", which uses the artifact `downloads` capability.
6. **What if I put in more or less?** Built into the Polaris Outlook card (step 5 shows two cards: the risk slider, which also states the risk limit, and the Outlook; the risk-and-return chart now appears only in the report). With the plan's amounts the chart and tiles are the plan's projection. When the client changes an amount, the same chart shows the what-if range with the plan's median as a dashed line, a "Showing your what-if amounts" badge appears, each tile shows the change "vs your plan", and the full comparison table sits under "Show details". The table has three views: with unsaved what-if amounts it compares them with the plan ("Your current plan / What if / Change"); after new amounts are saved it compares the plan now with the amounts first entered ("Your original amounts / Your plan now / Change", and the tiles show the change "vs your original amounts"); with nothing to compare, the Change column shows a dash and a hint (`#wi-hint`) says how to start. On a phone the controls fold under the chart ("Adjust amounts"). The report always uses the plan's amounts; if what-if amounts are unsaved, the report popup says so. After new amounts are saved, a "Restore my original amounts" button brings back the amounts entered in step 1 (kept the first time amounts are saved; typing new amounts in step 1 makes those the originals). "Reset" only discards unsaved what-if changes. The controls let the client change the starting amount and the regular contribution (amount and frequency), and add up to 3 one-time lump sums. The fund mix doesn't change, because weights are percentages. `PolarisEngine.whatIf({stop, method, start, contrib, lumps})` revalues the same 2,000 futures with the new money going in (each path's monthly growth, 2,000 × 240 factors, then `value = value × growth + money added`). Each update takes about 7 ms and matches a full re-run to rounding error. It is published as `PolarisResults.whatIf` with a `polaris:whatif` event. "Use these amounts in my plan" writes the amounts back to step 1 and the lump sums to the plan, then re-runs; the slider stays where it was.
6b. **Investor quote under the Outlook chart.** When the client has adjusted an amount and the longer controls leave room under the chart (desktop only; never on a phone), a quote card (`#olq`) fills the space: a line grows, the words appear one at a time, then the author's name fades in (shown instantly with reduced motion). Quotes match the risk level (`QUOTES` in app.html: steady, balanced or growth investors) and rotate each time the card reappears. `placeQuote()` measures the space after every what-if update and on resize, and hides the card if it would make the card taller. Each quote's wording and attribution was checked against its source (Buffett: Kilpatrick 1992 and the 1986 and 1988 Berkshire letters; Bogle: CFA Institute essay and The Little Book of Common Sense Investing; Lynch: Worth, 1995; Munger). The card says it is for inspiration only, not advice. Add quotes only with a verified source.
8. **Stress test (report only).** `PolarisEngine.stress(stop)` applies a crash in the first 12 months, by asset class: Equity −40% (2008 Global Financial Crisis), Bond −15% (2022 rate-hike selloff), Real estate −35% (2008 REIT collapse), Commodity −50% (oil crash 2020), Crypto −75% (2022 bitcoin bear market). Core stock categories are equity and core bond categories are bond; satellites use `CFG.stress.byFund` (ZRE real estate, CGL gold and XEG energy as commodity, FBTC and BTCC.B crypto), keyed by fund id in `etf-data.js`, or their group. When a placeholder joins the database its id changes from `PH:XXX` to the database ticker, so check `byFund` after such updates. The mix's fall is the weighted average, spread over the 12 months with each Hybrid path's weekly ups and downs kept on top; afterwards the Hybrid method carries on, with no extra rebound. It also reports the median time for $1 to get back to $1. `report()` includes it as `stress`: the chosen stop and both ends, plus every stop's crash loss next to its normal 1-in-20 bad year. The report shows it in Part 2 ("What if a crash hits?"): three plain points, the Polaris Outlook under stress over the client's horizon (`rptStressFan`, with each line labelled in dollars at its end and the value after the crash year next to the money put in), and risk and return under stress in dollars (`rptStressDollars`: a typical year, a 1-in-20 bad year and the crash on the starting amount, for the steadiest stop, the client's stop and the most-growth stop). Appendix A5 has the tables, the every-stop risk-and-return chart (`rptStressRR`) and the 20-year Outlook under stress. Step 5 doesn't show it. Shocks and mappings live in `CFG.stress`.
7. **Data caution.** After the projections, in the plan and in the report, the page states how many months of prices the numbers learn from, with dates read from the price file.

**Settings** live at the top of `polaris-engine.js` (`CFG`): number of paths, seed, block length, category limits (including the emerging-market limit), the minimum per fund when a category has two funds, the Stock ETF bands, the fallback risk limits, the headline method, the number of slider stops, the start stop, the smoothing strength, the risk-free rate and the markets used for beta.

**Checks**

```
python3 tools/test_engine.py site     # optimizer and every slider stop vs cvxpy, simulators vs numpy, what-if vs full re-run (pip install cvxpy)
python3 -m http.server 8765 -d site & python3 tools/test_app.py http://localhost:8765
```

## Light and dark themes

Every page has a theme switch in its header (sun/moon button). Dark is the original design and the default; the light theme is a plain, professional version of the same pages. Nothing else changes: same layout, features and text. The choice is remembered per viewer in the browser (`localStorage` key `polaris-theme`) and carries across all four pages. A tiny script in each page's `<head>` applies it before the page paints, so there is no flash. The site marks the light theme with its own attribute, `data-ptheme="light"` on `<html>`, never `data-theme`: the Claude app that hosts the site sets `data-theme` to the viewer's own app theme, and sharing that name made pages turn light on their own (with a moon icon beside a "Light" label). `tools/test_app.py` sets a host `data-theme` and checks the site ignores it.

How the light theme is built:

- `python3 tools/theme_light.py site` reads each page's own CSS and maps every colour to a light palette by what it does (text darkens to stay readable on white, dark panels turn white, translucent overlays become soft tints, borders and shadows soften, chart lines darken). It writes the result into `<style id="light-auto">` as rules under `:root[data-ptheme="light"]`. Colours that scripts put into SVG attributes or inline styles (charts, swatches) get matching rules too.
- Hand-written adjustments live in `tools/theme/light-common.css` (the switch itself) and `tools/theme/light-<page>.css` (colour tokens, the hero's morning sky, chart legend swatches). They are copied into `<style id="light-fix">` and win over the generated rules.
- Anything inside an element with class `keep-dark` keeps its own colours in both themes: the two explainer videos and the report (which is already a white page).
- **After changing a page's CSS, run the script again.** It only rewrites the blocks it owns (`theme-boot`, `light-auto`, `light-fix`, `theme-toggle`), so it is safe to repeat.

Checks: `python3 tools/test_app.py http://localhost:8765 light` runs the whole walkthrough in the light theme; without `light` it runs in dark and also tests the switch.

## Education notice

Every page starts with the same notice (`.edu-note`, styled in `<style id="edu-css">`): "For education only. PolarisAI is a student prototype, not investment advice. Always talk to a licensed financial professional before you buy any ETF." The same message appears in each page's footer, in a "Before you buy" card and the first "What happens now" step on the plan, in the Navigator ("Is this financial advice?", "How do I buy these funds?"), and at the top and bottom of the report (including the printed and downloaded versions). Keep it on any new page. `tools/test_app.py` checks that it is there.
