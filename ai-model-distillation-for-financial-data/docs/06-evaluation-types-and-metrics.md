# Evaluation Types and Metrics

The system compares the performance of student models with and without customization using F1-scores.

## Key Terminology

- **Student Model**: The smaller, more efficient model being trained/evaluated (e.g., Llama 3.2 1B, Llama 3.2 3B)
- **Teacher Model**: The larger, more capable model that generated the production responses used as ground truth
- **Base Evaluation**: Testing the student model before any customization (zero-shot)
- **ICL Evaluation**: Testing the student model with in-context learning examples (few-shot) but no fine-tuning
- **Customized Evaluation**: Testing the student model after fine-tuning with LoRA
- **F1-Score**: The primary metric measuring how well the student model's responses match the teacher model's responses

## Evaluation Types

The system supports four evaluation types:

### Base Evaluation (`base-eval`)

**Zero-shot F1-score baseline of student model before customization**

Base evaluation tests the student model on a held-out evaluation dataset sampled from production logs, without any fine-tuning. This establishes the baseline performance of the out-of-the-box model.

- **Dataset:** Held-out evaluation set from production data
- **Model:** Student model (no fine-tuning)
- **Metric:** F1-score
- **Purpose:** Establishes baseline performance before customization

> **Note:** The model receives only the `request.messages` as input and generates its own response, which is then compared against the ground truth for F1-score calculation.

### ICL Evaluation (`icl-eval`)

**Few-shot F1-score evaluation of student model with in-context learning examples**

ICL (In-Context Learning) evaluation tests the student model's ability to leverage a few-shot context -- a small number of example Q&A pairs are injected into the system message of each prompt, simulating a "few-shot" learning scenario. The ICL examples are retrieved from KDB-X.

- **Dataset:** ICL-augmented evaluation set (each test example has a configurable number of ICL examples injected into its system message)
- **Model:** Student model (no fine-tuning)
- **Context:** Few-shot (ICL) examples, controlled by `icl_config` in `config.yaml`
- **Metric:** F1-score
- **Purpose:** Measures how well the student model can adapt when given a few relevant examples, simulating real-world prompt engineering or agentic use cases

**Example:**

```json
{
  "request": {
    "messages": [
      {
        "role": "system",
        "content": "You are a helpful assistant that can answer questions and help with tasks.\nHere are some examples of how you should respond to different types of requests:\n\nFor example, if the conversation looks like this:\nuser: What is the sentiment of this earnings call?\n\nThen you'll respond with:\nassistant: The sentiment is bullish based on revenue guidance and margin expansion.\n\nFor example, if the conversation looks like this:\nuser: Summarise the key risk factors.\n\nThen you'll respond with:\nassistant: Key risks include rising interest rates, supply chain disruptions, and regulatory uncertainty."
      },
      {"role": "user", "content": "What is the outlook for next quarter?"}
    ]
  },
  "response": {
    "choices": [
      {
        "message": {
          "role": "assistant",
          "content": "The outlook is cautiously optimistic, with management guiding for 8-10% revenue growth."
        }
      }
    ]
  }
}
```

> **Note:** ICL examples are injected into the system message as formatted instructional text. The model receives the `request.messages` (including the system message with examples) as input, and its response is compared against the ground truth for F1-score calculation.

### Customized Evaluation (`customized-eval`)

**F1-score evaluation of customized model**

Customized evaluation tests the fine-tuned version of the student model on the same evaluation dataset. This measures the improvement from customization.

- **Dataset:** Same held-out evaluation set as base evaluation
- **Model:** Fine-tuned student model (via LoRA)
- **Metric:** F1-score
- **Purpose:** Quantifies improvement from customization and enables direct comparison to the base model

> **Note:** The customized model receives the same inputs as the base evaluation, allowing for direct F1-score comparison.

### Backtest Evaluation (`backtest-eval`)

**Financial-grade evaluation of model trading signals**

Backtest evaluation runs a vectorised backtest in KDB-X using as-of joins (`aj`) to measure the financial performance of a model's trading signals. This evaluation is only triggered when the enrichment pipeline produces market data.

- **Dataset:** Trading signals generated during the flywheel run, joined against `market_ticks` for entry/exit prices
- **Model:** The NIM model whose signals are being evaluated
- **Metrics:** Sharpe ratio, max drawdown, total return, win rate, number of trades
- **Purpose:** Validates that model predictions translate into profitable trading strategies, complementing the NLP-based F1 evaluation

> **Note:** The backtest uses a 1-day hold period and configurable transaction costs (default 5 bps). Signals are joined to market data via `aj` (as-of join) on `sym` and `timestamp` to get entry prices, then shifted +1 day for exit prices.

For a deeper discussion of why NLP accuracy alone isn't sufficient for financial models and how backtest evaluation closes that gap, see [Financial Backtesting: Why NLP Accuracy Isn't Enough](financial-backtesting.md).

## Metrics

The system now uses **two complementary evaluation approaches**:

1. **F1-Score** (NLP metric) -- measures text quality of model responses
2. **Financial metrics** (backtest) -- measures trading performance of model signals

### F1-Score

The F1-score balances precision (accuracy of positive predictions) and recall (coverage of actual positives), providing a single metric to assess model performance.

**In this system**, the F1-score compares the student model's generated responses against the teacher model's responses (ground truth) by:
- **Precision**: Measuring what percentage of tokens/concepts in the student's response are correct
- **Recall**: Measuring what percentage of the teacher's response tokens/concepts the student captured

Scores range from 0 to 1, where:
- **1.0** = Perfect match with teacher model's response
- **0.0** = No overlap with teacher model's response
- **Higher scores** = Better alignment between student and teacher outputs

### Financial Metrics (Backtest)

| Metric | Description | Range |
|--------|-------------|-------|
| Sharpe Ratio | Risk-adjusted return (mean return / std deviation) | Any real number; >1 is good |
| Max Drawdown | Largest peak-to-trough decline | -1.0 to 0.0; closer to 0 is better |
| Total Return | Cumulative net return after costs | Any real number |
| Win Rate | Fraction of trades with positive return | 0.0 to 1.0 |
| N Trades | Number of signals with valid entry/exit prices | Integer >= 0 |

## Evaluation Results Format

Evaluation results are returned in a consistent structure. Each result includes metadata (such as evaluation type, timestamps, and progress) and a `scores` dictionary containing the F1-score metric.


