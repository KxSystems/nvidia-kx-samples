# Data

## Included Datasets

### `test_financial_data.jsonl` — Synthetic Seed Data

200 synthetic financial news records for quick smoke-testing. Each record is a
chat-format JSONL entry with a user prompt (financial headline) and an assistant
response (analyst rating). Use this to verify the pipeline works end-to-end
before loading real data.

### `sample_market_data.parquet` — Sample Market Data

Historical OHLCV market data used by the backtesting module to evaluate trading
signals derived from model predictions.

### `fingpt_sentiment_1k.jsonl` — FinGPT Financial Sentiment (1,000 records)

A 1,000-record sample from the
[FinGPT/fingpt-sentiment-train](https://huggingface.co/datasets/FinGPT/fingpt-sentiment-train)
dataset (76K+ records total). Each record contains a financial news headline or
tweet with a ground-truth sentiment label (positive / negative / neutral).

**Source:** FinGPT — an open-source financial LLM project.
**License:** Apache 2.0
**Format:** Chat-format JSONL (compatible with the data loader).

#### Loading into the pipeline

```bash
# Via the load script
python src/scripts/load_test_data.py \
  --workload_id news_sentiment \
  --client_id fingpt-1k \
  --file data/fingpt_sentiment_1k.jsonl

# Then submit a job
curl -X POST http://localhost:8000/api/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "workload_id": "news_sentiment",
    "client_id": "fingpt-1k",
    "model_name": "meta/llama-3.2-1b-instruct",
    "steps": ["deploy_base", "evaluate_base", "fine_tune", "evaluate_customized"]
  }'
```

#### Downloading the full dataset

To use all 76K+ records instead of the 1K sample:

```python
from datasets import load_dataset

ds = load_dataset("FinGPT/fingpt-sentiment-train", split="train")
print(f"{len(ds)} records")
```

## Generating Custom Data

See `generate_sample_data.py` in this directory for the script used to create
the synthetic seed data.

## JSONL Format

All datasets use the chat-completion JSONL format — one JSON object per line:

```json
{"messages": [{"role": "user", "content": "Classify: headline text"}, {"role": "assistant", "content": "label"}]}
```

The data loader (`src/scripts/load_test_data.py`) converts this to the OpenAI
request/response schema used internally by the pipeline.
