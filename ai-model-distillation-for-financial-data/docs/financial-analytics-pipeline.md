<!--
SPDX-FileCopyrightText: Copyright (c) 2026 KX Systems, Inc. All rights reserved.
SPDX-License-Identifier: Apache-2.0

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
-->

# Financial Analytics Pipeline — Deep Dive

This document provides a step-by-step technical walkthrough of the financial analytics pipeline: how training data flows from `flywheel_logs` through enrichment, labeling, signal generation, and backtesting. Each stage is explained with its q queries, data structures, and design rationale.

## Table of Contents

- [Training Data — `flywheel_logs`](#training-data--flywheel_logs)
- [Market Data Enrichment](#market-data-enrichment)
- [Market-Return Labeling](#market-return-labeling)
- [Signal Generation](#signal-generation)
- [Backtesting](#backtesting)
- [End-to-End DAG](#end-to-end-dag)

---

## Training Data — `flywheel_logs`

### What It Is

`flywheel_logs` is the training data table. Every record represents one LLM interaction (a user prompt + model response) that will be used for LoRA fine-tuning. It is the raw material the entire flywheel runs on.

### Schema

| Column | Type | Purpose |
|--------|------|---------|
| `doc_id` | symbol | Unique record ID |
| `workload_id` | symbol | Groups records into a workload/job (e.g., `alpaca-news-aapl`) |
| `client_id` | symbol | Who produced the data (e.g., `alpaca-poc`) |
| `timestamp` | timestamp | When the event occurred — critical for `aj` enrichment and backtesting |
| `request` | general (JSON string) | The prompt sent to the model (OpenAI chat format) |
| `response` | general (JSON string) | The model's response (OpenAI chat completion format) |

### Record Format

Each record follows the **OpenAI chat completion format**:

**`request`** (the prompt):

```json
{
  "model": "teacher",
  "messages": [
    {
      "role": "user",
      "content": "Classify the following financial news headline for AAPL: \"Apple reports record Q4 revenue of $89.5B, beating expectations by 3%\""
    }
  ]
}
```

**`response`** (the label):

```json
{
  "choices": [
    {
      "message": {
        "role": "assistant",
        "content": "BUY — Apple reports record Q4 revenue, strong iPhone demand and services growth suggest continued momentum."
      }
    }
  ]
}
```

The `response.choices[0].message.content` can be:
- **Pre-labeled**: The teacher model already provided a BUY/SELL/HOLD response with rationale. Used directly for fine-tuning.
- **Empty** (`""`): The record has no label yet. The [market-return labeling](#market-return-labeling) step fills it in using real market returns.

### What the Pipeline Needs From Each Record

| Field | Where Used | What Happens Without It |
|-------|-----------|------------------------|
| Ticker in `request.messages` | Enrichment, labeling, signal generation | Record is skipped — no market context, no label, no trading signal |
| `timestamp` | Enrichment `aj`, labeling `aj`, backtest `aj` | Record is skipped for all market-data operations |
| `response.choices[0].message.content` | Fine-tuning training target | If empty AND no market data for labeling, the model learns to output nothing (100% HOLD) |
| `workload_id` | Scoping records to a job | Records will not be found by the flywheel job |

### Ideal Training Data

The best training records for the financial pipeline are:

1. **Real financial events** — news headlines, earnings reports, analyst notes — not generic Q&A
2. **Ticker-specific** — mention a real stock symbol (e.g., `AAPL`) so enrichment, labeling, and backtesting work
3. **Time-stamped** — tied to a real point in time for accurate `aj` lookups against market data
4. **Either pre-labeled or labelable** — have a teacher response, or have empty content with matching market data in `market_ticks` so the labeling step can compute ground truth from actual returns

### Data Sources

| Source | Tickers | Timestamps | Labels | Enrichable | Backtestable |
|--------|---------|-----------|--------|-----------|-------------|
| `test_financial_data.jsonl` | None | None | Generic Q&A | No | No |
| `fingpt_sentiment_1k.jsonl` | In tweet text (`$TSLA`) | None | positive/neutral/negative | No | No |
| Alpaca news (`load_alpaca_data.py --with-news`) | Explicit (`--symbol AAPL`) | Real article timestamps | Empty (auto-labeled) | Yes | Yes |

The Alpaca news loader is the **recommended** data source for the full financial pipeline.

---

## Market Data Enrichment

**Module**: `kdbx/enrichment.py`
**DAG stage**: Runs inside `create_datasets()`, before labeling

### What It Does

Enrichment adds **point-in-time market context** to training records before fine-tuning. Each record gets 9 financial features from the exact moment the event occurred, using KDB-X as-of joins (`aj`).

### Step 1: Ticker Extraction

For each `flywheel_logs` record, the system extracts which stock ticker it refers to. Two strategies are available (configured via `enrichment_config`):

- **`field`** (default): Reads a named field from the record, e.g., `record["sym"]`
- **`regex`**: Applies a regex pattern against the message content to find ticker mentions (e.g., `\b([A-Z]{1,5})\b`)

```python
# kdbx/enrichment.py
sym = extract_sym_from_record(record, config)
# Returns "AAPL" or None if no ticker found
```

If neither strategy finds a ticker, `config.default_sym` is used as a fallback (e.g., `"AAPL"` for single-stock POCs).

### Step 2: Filter Enrichable Records

Only records with **both** a valid ticker AND a timestamp are enrichable:

```python
# src/tasks/tasks.py — create_datasets()
enrichable = []
for rec in records:
    sym = extract_sym_from_record(rec, config)
    ts = rec.get(config.timestamp_field)
    if sym and ts:
        enrichable.append((rec, sym, ts))
```

Records missing either field are skipped — they still go to training, just without market features.

### Step 3: Batch `aj` Query

All enrichable records are sent to KDB-X in a **single batch** as-of join. This is the core of enrichment.

```q
{[s;ts]
  // Build a lookup table from the inputs
  lookup: ([] sym: s; timestamp: ts);

  // aj #1: Join against market_ticks
  //   For each (sym, timestamp), find the most recent market_ticks row
  //   where sym matches AND timestamp <= event time
  snap: aj[`sym`timestamp; lookup;
    select sym, timestamp, close, vwap, high, low, volume from market_ticks];

  // aj #2: Join against order_book
  //   Same logic — find most recent bid/ask at event time
  book: aj[`sym`timestamp; lookup;
    select sym, timestamp, bid_price, ask_price, spread, mid from order_book];

  // Left join to combine both result sets
  snap lj `sym`timestamp xkey book
}
```

**How `aj` works here**:

| Event | sym | timestamp | What `aj` finds in `market_ticks` |
|-------|-----|-----------|-----------------------------------|
| News about AAPL | AAPL | 2025-06-15T14:30 | Most recent AAPL row where timestamp <= 14:30 |

This is a **point-in-time** lookup — no look-ahead bias. The record only sees data that existed at that moment.

> **Critical requirement**: `market_ticks` and `order_book` must be sorted by `` `sym`timestamp `` (via `xasc`) for `aj` to return correct results. Without this sort order, `aj` may return an arbitrary row instead of the most recent one. The data loaders apply `` `sym`timestamp xasc `market_ticks `` after each data load.

### Step 4: Field Mapping

The q result comes back as a table. Each row's fields are mapped into the training record:

```python
_FIELD_MAP = {
    "close": "market_close",     "vwap": "market_vwap",
    "high": "market_high",       "low": "market_low",
    "volume": "market_volume",   "bid_price": "market_bid",
    "ask_price": "market_ask",   "spread": "market_spread",
    "mid": "market_mid",
}
```

The enriched record gets these 9 fields added:

```python
record["market_close"] = 188.50
record["market_vwap"] = 187.92
record["market_high"] = 189.10
record["market_low"] = 186.30
record["market_volume"] = 52340000
record["market_bid"] = 188.48
record["market_ask"] = 188.52
record["market_spread"] = 0.04
record["market_mid"] = 188.50
```

### Step 5: Stats Tracking

Enrichment statistics are recorded on the `flywheel_runs` record and surfaced in job detail API responses:

```python
enrichment_stats = {
    "num_enriched": 847,
    "total_records": 1000,
    "features": ["close", "vwap", "high", "low", "volume",
                  "bid_price", "ask_price", "spread", "mid"],
    "time_seconds": 1.2
}
```

### Graceful Degradation

If KDB-X has no market data, or a record's ticker doesn't match anything in `market_ticks`, the `aj` returns nulls. The system:

- Skips null fields (does not inject `NaN` values)
- Logs a warning
- Continues — the record is still used for training, just without market context

---

## Market-Return Labeling

**Module**: `kdbx/labeling.py`
**DAG stage**: Runs inside `create_datasets()`, after enrichment

### What It Does

Records with **empty** `response.choices[0].message.content` need labels before fine-tuning. The labeling step computes **objective ground truth** from real market returns: if the stock went up significantly the next day, it's a BUY; if it went down, it's a SELL; otherwise HOLD.

### Step 1: Identify Labelable Records

A record is labelable when it has:
- A valid ticker (extracted via `extract_sym_from_record()`)
- A timestamp
- An **empty** response content (non-empty content is not overwritten)

```python
labelable = []
for rec in records:
    sym = extract_sym_from_record(rec, config)
    ts = rec.get(config.timestamp_field)
    content = rec["response"]["choices"][0]["message"].get("content", "")
    if sym and ts and not content:
        labelable.append((rec, sym, ts))
```

### Step 2: Batch `aj` Return Lookup

All labelable records are sent to KDB-X in a single batch:

```q
{[syms;timestamps]
  // Build lookup table
  lookup: ([] sym: syms; timestamp: timestamps);

  // aj: entry price = close at event time
  entry: aj[`sym`timestamp; lookup;
    select sym, timestamp, entry_price:close from market_ticks];

  // Shift timestamp +1 day, then aj for exit price
  exit_lookup: update timestamp: timestamp + 1D from lookup;
  exits: aj[`sym`timestamp; exit_lookup;
    select sym, timestamp, exit_price:close from market_ticks];

  // Combine entry and exit prices
  update exit_price: exits`exit_price from entry
}
```

For each record, this returns the **close price at event time** (entry) and the **close price 1 day later** (exit).

### Step 3: Compute Direction

```python
return_pct = ((exit_price - entry_price) / entry_price) * 100

if return_pct > +threshold_bps / 100:   # default: +0.5%
    direction = "BUY"
elif return_pct < -threshold_bps / 100:  # default: -0.5%
    direction = "SELL"
else:
    direction = "HOLD"
```

The threshold is configurable via `signal_config.labeling.return_threshold_bps` (default: 50 bps = 0.5%).

### Step 4: Generate Template Rationale

The label is formatted as a training-ready response string:

```python
generate_template_rationale("BUY", "AAPL", 1.50, 185.50, 188.28)
# → "BUY — AAPL next-day return +1.50% ($185.50 → $188.28)"
```

This rationale is written into `record["response"]["choices"][0]["message"]["content"]`, which flows directly into the NeMo training JSONL with zero downstream changes.

### Step 5: What Happens to Unlabelable Records

- **No market data** (entry or exit price is null): `direction = None`, record is skipped. It still goes to training but with empty content — the `format_training_data()` function handles this gracefully.
- **Content already populated**: Record is not touched. Pre-labeled data from a teacher model takes priority.

### Configuration

```yaml
signal_config:
  labeling:
    enabled: true
    return_threshold_bps: 50.0   # +/- 0.5% → BUY/SELL, else HOLD
    horizon: "1D"                 # next-day return lookforward
```

---

## Signal Generation

**Module**: `src/tasks/tasks.py` → `generate_signals()` task
**KDB-X writer**: `kdbx/signals.py`
**DAG stage**: Runs after each evaluation (base and customized)

### What It Does

After a model is evaluated (F1-score), the `generate_signals` task runs each evaluation record through the deployed NIM to produce BUY/SELL/HOLD trading signals. These signals are stored in the KDB-X `signals` table for subsequent backtesting.

### Step 1: Fetch Evaluation Records

The same records used for evaluation are re-fetched:

```python
records = RecordExporter().get_records(
    previous_result.client_id,
    previous_result.workload_id,
    split_config,
)
```

### Step 2: Inject System Prompt

Each record's messages get a system prompt prepended that tells the NIM to classify in trading terms:

```python
messages = [
    {"role": "system", "content": settings.signal_config.system_prompt},
    *record["request"]["messages"]
]
```

The default system prompt:

> *"You are a financial trading signal generator. Analyze the following and respond with BUY, SELL, or HOLD followed by a brief rationale."*

### Step 3: Call the NIM

The messages are sent to the deployed NIM's `/v1/chat/completions` endpoint:

```python
resp = requests.post(
    nim_url,
    json={"model": model_name, "messages": messages},
    timeout=60,
)
content = resp.json()["choices"][0]["message"]["content"]
```

The model responds with something like:

> *"BUY — Strong earnings beat with positive guidance suggests continued upward momentum."*

### Step 4: Parse Direction

The response is parsed to extract the trading direction:

```python
direction = _parse_direction(content)
# Looks for BUY, SELL, or HOLD at the start of the content
# Falls back to HOLD if no direction found
```

### Step 5: Use Original Event Timestamp

The signal's timestamp is set to the **original event time** from the training record, not the current time:

```python
event_ts = rec.get(settings.enrichment_config.timestamp_field)
sig_ts = datetime.fromisoformat(event_ts) if event_ts else datetime.utcnow()
```

This is critical for backtesting accuracy — the backtest `aj` will join the signal to the market price **at the time the event actually happened**, not when the model processed it.

### Step 6: Write to KDB-X

Signals are batched and written to the `signals` table in a single q call:

```python
write_signals_batch(signals_batch)
```

Each signal contains:

| Field | Example | Purpose |
|-------|---------|---------|
| `signal_id` | `"a1b2c3d4-..."` | Unique identifier |
| `timestamp` | `2025-06-15T14:30:00` | Original event time |
| `sym` | `AAPL` | Ticker symbol |
| `direction` | `BUY` | Trading direction |
| `confidence` | `0.0` | Reserved for future use |
| `model_id` | `meta/llama-3.2-1b-instruct` | Which model generated it |
| `rationale` | `"BUY — strong earnings..."` | Full model response |

The q insert uses typed vectors for correct column types:

```q
{[sid;ts;s;dir;conf;mid;rat]
 n: count sid;
 `signals insert flip
 `signal_id`timestamp`sym`direction`confidence`model_id`rationale`realized_pnl`realized_at
 !(sid;ts;s;dir;conf;mid;rat;n#0n;n#0Np)}
```

`realized_pnl` and `realized_at` are filled with null floats/timestamps server-side (for future live-trading reconciliation).

---

## Backtesting

**Module**: `kdbx/backtest.py`
**DAG stage**: Runs after each signal generation step

### What It Does

Backtesting answers the question: **"Would these signals have made money?"** It simulates trades using real historical prices and computes financial performance metrics.

### Why It Matters

F1-score tells you how well a distilled model reproduces the teacher's text outputs. It does **not** tell you whether those outputs make money. Two models with identical F1 can have wildly different financial performance — one might catch the high-impact market-moving events while the other misclassifies them.

Backtest evaluation catches these failure modes before deployment.

### Step 1: The Backtest Query

The entire backtest runs as a single vectorized q lambda:

```q
{[mid;cost]
  // 1. Get all BUY/SELL signals for this model
  sigs: select from signals where model_id = mid, direction in `BUY`SELL;

  // 2. aj: entry price = most recent close at signal time
  entry: aj[`sym`timestamp; sigs;
    select sym, timestamp, entry_price:close from market_ticks];

  // 3. Shift timestamp +1 day, then aj for exit price
  exits: aj[`sym`timestamp;
    update timestamp: timestamp + 1D from entry;
    select sym, timestamp, exit_price:close from market_ticks];

  // 4. Join exit prices back to entry table
  trades: update
    dir_mult: ?[direction = `BUY; 1f; -1f],
    gross_ret: (exit_price - entry_price) % entry_price
  from entry lj `signal_id xkey select signal_id, exit_price from exits;

  // 5. Compute net returns with transaction costs
  trades: update net_ret: (gross_ret * dir_mult) - cost % 10000
  from trades where not null entry_price, not null exit_price;

  // 6. Aggregate financial metrics
  rets: exec net_ret from trades;
  n: count rets;
  `sharpe`max_drawdown`total_return`win_rate`n_trades!(
    $[n > 1; (avg rets) % dev rets; 0f];
    $[n > 0; (min (prds 1 + rets) % maxs prds 1 + rets) - 1; 0f];
    $[n > 0; (prd 1 + rets) - 1; 0f];
    $[n > 0; (sum rets > 0) % n; 0f];
    n)
}
```

### Step 2: How Each `aj` Works

**Entry price lookup**:

| Signal | sym | timestamp | `aj` finds in `market_ticks` |
|--------|-----|-----------|------------------------------|
| BUY AAPL | AAPL | June 15, 14:30 | Most recent AAPL close where timestamp <= June 15 14:30 → **$188.50** |

**Exit price lookup** (timestamp shifted +1 day):

| Signal | sym | shifted timestamp | `aj` finds in `market_ticks` |
|--------|-----|-------------------|------------------------------|
| BUY AAPL | AAPL | June 16, 14:30 | Most recent AAPL close where timestamp <= June 16 14:30 → **$191.20** |

HOLD signals are excluded from the backtest (`direction in `BUY`SELL``).

### Step 3: Trade Simulation Example

**BUY signal on AAPL** (price goes up):

```
entry_price  = $188.50
exit_price   = $191.20
gross_return = (191.20 - 188.50) / 188.50 = +1.43%
dir_mult     = +1 (BUY)
cost         = 5 bps = 0.05%
net_return   = (1.43% × 1) - 0.05% = +1.38%   ← profitable trade
```

**SELL signal on AAPL** (price goes up — wrong call):

```
entry_price  = $188.50
exit_price   = $191.20
gross_return = (191.20 - 188.50) / 188.50 = +1.43%
dir_mult     = -1 (SELL / short)
net_return   = (1.43% × -1) - 0.05% = -1.48%  ← losing trade
```

### Step 4: Metric Computation

| Metric | q Expression | What It Measures |
|--------|-------------|------------------|
| **Sharpe Ratio** | `(avg rets) % dev rets` | Risk-adjusted return. >1.0 is good, >2.0 is strong |
| **Max Drawdown** | `(min (prds 1+rets) % maxs prds 1+rets) - 1` | Worst peak-to-trough decline. Closer to 0% is better |
| **Total Return** | `(prd 1+rets) - 1` | Cumulative net profit/loss across all trades |
| **Win Rate** | `(sum rets > 0) % n` | Fraction of trades that made money |
| **N Trades** | `count rets` | Sample size. Need 50+ for statistical significance |

### Reading the Results Together

No single metric tells the full story:

- **High Sharpe + low drawdown** = consistent, reliable strategy. This is the ideal outcome.
- **High return + high drawdown** = the model catches big moves but has painful losing streaks. May need position sizing adjustments.
- **High win rate + low Sharpe** = many small wins offset by a few large losses. The model may misclassify tail-risk events.
- **Low N trades** = not enough data to draw conclusions. Load more market data before making deployment decisions.

### Step 5: Results Storage

Backtest results are:

1. Written as a `backtest-eval` evaluation record in KDB-X (via the `evaluations` table)
2. Surfaced in the job detail API response alongside base and customized F1-scores
3. Both the base and customized models are backtested independently, enabling direct comparison

---

## End-to-End DAG

The full financial analytics pipeline runs as a sequential Celery DAG:

```
create_datasets()
├── Fetch records from flywheel_logs
├── Enrichment (aj against market_ticks + order_book)
├── Labeling (aj for next-day returns → BUY/SELL/HOLD)
└── Upload training/eval/val splits to NeMo Data Store

base_eval (F1-score)
  → generate_signals (base model → signals table)
    → run_backtest_assessment (base signals → financial metrics)

customization (LoRA fine-tuning via NeMo Customizer)

customized_eval (F1-score)
  → generate_signals (customized model → signals table)
    → run_backtest_assessment (customized signals → financial metrics)
```

Both models are backtested independently, so you can directly compare: **did fine-tuning improve financial performance, not just NLP accuracy?**

### Data Flow Summary

```
flywheel_logs (training records)
    │
    ▼ extract ticker + timestamp
market_ticks ──aj──► enriched records (+ 9 market features)
order_book ────aj──┘
    │
    ▼ empty responses only
market_ticks ──aj──► labeled records (BUY/SELL/HOLD from real returns)
    │
    ▼ upload to NeMo
    ├── training split → LoRA fine-tuning
    └── eval split → F1 evaluation
                        │
                        ▼ call NIM with system prompt
                   signals table (BUY/SELL/HOLD per record)
                        │
                        ▼ aj for entry + exit prices
                   backtest metrics (Sharpe, drawdown, return, win rate)
```

### Critical Dependency: `xasc` Sort Order

All `aj` operations in the pipeline depend on `market_ticks` and `order_book` being sorted by `` `sym`timestamp ``. The data loaders apply this sort after each data load:

```q
`sym`timestamp xasc `market_ticks
`sym`timestamp xasc `order_book
```

Without this sort, `aj` returns incorrect prices and all downstream metrics (enrichment, labeling, backtesting) produce wrong results.

---

**Related documentation:**

- [KDB-X Architecture](KDB-X-Architecture.md) — adapter layers and table schemas
- [Configuration Guide](03-configuration.md) — enrichment, labeling, and backtest configuration
- [Workflow Orchestration](08-workflow-orchestration.md) — DAG task sequence
- [Data Logging](data-logging.md) — how to instrument your app to write to `flywheel_logs`
- [Evaluation Types and Metrics](06-evaluation-types-and-metrics.md) — F1-score and backtest eval types
- [Scripts Reference](scripts.md) — `load_alpaca_data.py` for loading market data and news
