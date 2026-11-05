# near-thesis: NEAR, measured

An evidence-first, long-term investment thesis for NEAR Protocol, built for the **NEAR HACKATHON** (Investment Thesis track, Nov 2026). Every number comes from public data through code in this repo, and the valuation model's assumptions sit in one YAML file you can edit and re-run.

- **Live dashboard:** https://rajeshmullippa-collab.github.io/near-thesis/
- **The thesis:** [THESIS.md](THESIS.md)
- **Every number, regenerated on each run:** [EVIDENCE.md](EVIDENCE.md)
- **Model assumptions:** [config/assumptions.yaml](config/assumptions.yaml)
- **Demo post on X:** https://x.com/rajeshmullippa/status/2118146054088540494

> Built by **Hark, an AI agent, under the direction of Rajesh Mullippa**. Not financial advice and not a price call.

## The problem

Most "NEAR thesis" content is conviction plus a chart. This repo answers a narrower, testable question with data anyone can reproduce:

> Working hypothesis (from the track prompt): *cross-chain volume through NEAR Intents is a better leading indicator of real network usage than token price.*

It tests that hypothesis, shows what supports it and what cuts against it, and turns the result into a bull/base/bear valuation whose every input is explicit.

## Reproduce it (one command)

Requires Python 3.10+.

```bash
git clone https://github.com/rajeshmullippa-collab/near-thesis && cd near-thesis
make            # = pip install -r requirements.txt && python -m near_thesis run
```

That fetches every source live, writes the raw responses to `data/snapshot/`, and rebuilds the 9 charts, `docs/index.html`, `EVIDENCE.md` and the model. No API keys, no wallet, no transactions.

Offline (from the committed snapshot, exactly what CI runs):

```bash
pip install -r requirements.txt
python -m near_thesis run --offline
python -m pytest -q
```

## Try it: "do X, see Y"

| Do | See |
| --- | --- |
| `python -m near_thesis run --offline` | `Built 9 charts, docs/index.html and EVIDENCE.md from data as of 2026-11-03`, then a bull/base/bear table with present value per NEAR and the Intents growth rate today's price implies |
| `make serve`, open http://localhost:8000 | The dashboard: 8 KPI tiles, 9 charts, each with its one-sentence reading and its source/method, the scenario table and the sensitivity grid |
| Open `EVIDENCE.md` | ~30 metrics with value and source, the lead-lag test table, the scenario table |
| Edit `config/assumptions.yaml` (e.g. base `intents_volume_cagr: 0.6`), run `make model` | The base-case present value changes; the reverse-model column tells you what growth today's price needs |
| `python -m near_thesis fetch` | Every snapshot in `data/snapshot/` refreshed from the live sources, with timestamps in `data/snapshot/_manifest.json` |

## What is measured, and from where

| Topic | Metric(s) | Source (all public, no key) |
| --- | --- | --- |
| Accounts | daily active / new / deleted accounts | NearBlocks `GET /v1/charts` |
| Transactions | daily transactions, gas used, active contracts | NearBlocks `GET /v1/charts` |
| Fees | daily L1 gas fees in NEAR and USD; burn share | NearBlocks; NEAR RPC `EXPERIMENTAL_protocol_config` (`burnt_gas_reward`) |
| Supply / inflation | total supply history, realized growth, protocol max inflation | NearBlocks; NEAR RPC `block`, `EXPERIMENTAL_protocol_config` |
| Staking | stake per validator, staked share, Nakamoto coefficient | NEAR RPC `validators` |
| NEAR Intents | daily volume, gross fees, revenue captured by NEAR | DefiLlama `near-intents` adapter (`/summary/dexs`, `/summary/fees`) |
| Buyback | balances of the revenue / buyback wallets listed on revenue.near.org | NEAR RPC `query view_account` |
| DeFi | chain TVL, stablecoins on NEAR, DEX volume | DefiLlama |
| Price | NEAR price, market cap, volume (365 days) | CoinGecko (falls back to NearBlocks price) |
| Developers | weekly commits on core NEAR repos | GitHub REST `stats/commit_activity` |

Not used, and why: the NEAR BigQuery public dataset (needs a billed Google Cloud project) and the NEAR Intents Explorer API (needs a partner JWT). Both would let a judge cross-check the DefiLlama Intents numbers at transaction level; THESIS.md lists this as a limitation.

## How it works

```
near_thesis/
  sources.py     fetchers; raw responses -> data/snapshot/*.json (+ _manifest.json with source and time)
  metrics.py     one daily table (UTC days), point-in-time facts, staking, lead-lag hypothesis test
  model.py       bull/base/bear valuation + reverse model + sensitivity grid
  charts.py      PNG charts -> docs/charts/
  dashboard.py   docs/index.html (self-contained, data embedded, Chart.js vendored) + EVIDENCE.md
  cli.py         python -m near_thesis [fetch|build|model|run] [--offline]
config/assumptions.yaml   every model input
data/snapshot/            cached raw data (CI and --offline use it)
docs/                     GitHub Pages site
tests/                    offline tests (data sanity, model monotonicity, reverse-model round trip)
```

**Valuation model.** `holder_earnings = Intents volume × net take-rate × share reaching holders + L1 fees × burn share`; `value = earnings × exit multiple`; divide by projected supply, discount back. The reverse model solves for the Intents growth rate that makes today's price fair under each scenario's other assumptions. It values cash flows only, so the gap to market price is reported as such.

**Hypothesis test.** Pearson correlation of weekly log-changes between Intents volume and price, transactions, active accounts and TVL at lags of −8…+8 weeks (Jan 2025 onward), with a ±2/√n noise band. Descriptive, not causal.

## CI and the live dashboard

- `.github/workflows/ci.yml`: on every push, rebuilds everything from the cached snapshot and runs the tests.
- `.github/workflows/refresh.yml`: daily, fetches live data, rebuilds, commits the new snapshot; GitHub Pages serves `/docs`, so the dashboard updates itself.

## Hackathon disclosures

- All code and the thesis were written during NEAR HACKATHON (first commit Nov 2026; window opened 2026-10-19). No pre-hackathon code.
- Libraries: pandas, numpy, matplotlib, requests, PyYAML, pytest, Chart.js 4.4.4 (vendored, MIT).
- AI: built by Hark, an AI agent, under Rajesh Mullippa's direction. Data and every number are produced by the code, not written by hand.
- The same team lead is not submitting another NEAR HACKATHON project.
- No wallet connection, no transactions, no keys. Only public read endpoints.

## License

MIT, see [LICENSE](LICENSE).
