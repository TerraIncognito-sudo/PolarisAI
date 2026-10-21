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

1. Read the published files from the artifact: `tools/build_etf_data.py`, `tools/polaris-config.json` and the current `etf-data.js` (saved as the "previous" file for the change report).
2. Run:
   ```
   python3 build_etf_data.py --core etf_core.db --context etf_context.db \
       --prices etf_prices.db --config polaris-config.json --out site \
       --previous previous-etf-data.js
   ```
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
- **HSU and BTCC:** kept as manual entries until the team settles the leveraged and crypto policy.

To change a rule or a placeholder, edit `polaris-config.json` and rerun the script.

## The optimizer and simulation engine (`polaris-engine.js`)

Step 5 of the builder ("Build and look ahead") runs `polaris-engine.js`. It reads only the generated data files, so a data update needs no engine changes.

**What it does**

1. **Model.** Expected return per fund = the category assumption in `polaris-config.json` minus the fund's MER (satellites use their own assumption). Volatility and correlation come from the weekly prices in `etf-data.js`. Placeholder funds use the config's fallback volatility and the builder's usual correlation rules.
2. **Two scenarios, side by side.**
   - *Minimum Variance* (shown as "Steadiest mix"): the lowest-volatility weights.
   - *Maximum Return* (shown as "Highest expected growth"): the highest expected return whose volatility stays at or below the risk limit. The risk limit is the volatility of the tier's boldest reference mix: the top of its Stock ETF band, split the builder's usual way, using the client's own funds.
   - Both keep 5–40% per core category (emerging markets at most 15%), the tier's Stock ETF band (Low 20–40%, Moderate 50–70%, High 75–95%, including stock satellites), satellites at their chosen weight, and at least 3% in each fund when a category has two funds. At a High risk level a bond category may go to 0%, as before.
   - Solver: a convex QP solver (ADMM with exact active-set polishing). Maximum Return is found by bisection along the efficient frontier until volatility meets the limit. Weights are rounded to whole percents without breaking any limit.
   - Recommendation: Minimum Variance for Low, Maximum Return for Moderate and High.
3. **Three simulation methods.** Each runs 2,000 futures for 20 years in weekly steps, with the client's contributions. The 5-, 10- and 20-year views are snapshots of the same paths, and both scenarios use the same random draws.
   - *Monte Carlo*: normal weekly log-returns from the expected return and the portfolio volatility.
   - *Bootstrap*: the portfolio's real weekly returns over the price window, replayed with a stationary block bootstrap (blocks of about 6 weeks on average). It inherits that window's returns, so it reads as optimistic when the last 3 years were strong.
   - *Hybrid* (headline method): Bootstrap's real weekly shocks, re-centred on the forward-looking expected return.
   - Funds without price history get a stand-in history: a related fund's returns scaled to the fund's volatility and correlation, centred on its expected return, plus seeded noise. The page names these funds.
4. **Shared results state.** Every run is published as `window.PolarisResults`, along with a `polaris:results` event on `window` and `PolarisEngine.subscribe(fn)`. The object holds the inputs, settings, risk limit, efficient frontier, and, for each scenario, its weights, return, volatility, fee and split. For each scenario and method it also holds yearly percentiles plus 5/10/20-year summaries: percentiles, mean, chance of ending below what was put in, the average of the worst 5% of outcomes (CVaR), drawdowns and median growth rate.

5. **What if I put in more or less?** A card in step 5 lets the client change the starting amount and the regular contribution (amount and frequency), and add up to 3 one-time lump sums ("Today" or "In N years"). The fund mix doesn't change, because weights are percentages. `PolarisEngine.whatIf({scenario, method, start, contrib, lumps})` revalues the same 2,000 futures with the new money going in. It keeps each path's monthly growth for the portfolio and method on screen (2,000 × 240 factors, built in about 70 ms) and applies `value = value × growth + money added` month by month. Each update takes about 7 ms and matches a full re-run with those amounts to rounding error. The result is published as `PolarisResults.whatIf`, with a `polaris:whatif` event. "Use these amounts in my plan" writes the amounts back to step 1 and the lump sums to the plan (`run()` accepts `lumps: [{amount, month}]`), then re-runs. The client keeps their chosen portfolio and method.

**Settings** live at the top of `polaris-engine.js` (`CFG`): number of paths, seed, block length, category limits (including the emerging-market limit), the minimum per fund when a category has two funds, the Stock ETF bands, the fallback risk limits and the headline method.

**Checks**

```
python3 tools/test_engine.py site     # optimizer vs cvxpy, simulators vs numpy, what-if vs full re-run (pip install cvxpy)
python3 -m http.server 8765 -d site & python3 tools/test_app.py http://localhost:8765
```
