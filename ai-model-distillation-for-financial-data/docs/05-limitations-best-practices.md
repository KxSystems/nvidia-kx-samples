# Limitations & Best Practices

## Operational Scope

The developer example provides flywheel service that evaluates candidate models on defined workloads using automated metrics and benchmarks. Models that demonstrate strong performance according to these criteria are surfaced in the evaluation results as promising candidates for further review.

### Example Evaluation Results

The following simplified example results surface the `llama-3.2-1b-instruct-ft-1` model as a promising candidate for your use case.

```json
[
  {
    "model_name": "llama-3.2-1b-instruct-ft-1",
    "evaluations": [
      {
        "eval_type": "base-eval",
        "scores": { "f1_score": 0.92 },
        "progress": 100.0
      }
    ]
  },
  {
    "model_name": "llama-3.2-1b-instruct-ft-2",
    "evaluations": [
      {
        "eval_type": "base-eval",
        "scores": { "f1_score": 0.78 },
        "progress": 100.0
      }
    ]
  }
]
```

This flywheel doesn't automatically promote or deploy any model. You must also validate surfaced models using your own acceptance tests and guardrails before considering them for production.

## Evaluation Types and Metrics

> **📖 For detailed evaluation information:** See [Evaluation Types and Metrics](06-evaluation-types-and-metrics.md)

The system supports base evaluation, customized evaluation (both using F1-score metrics), and [backtest evaluation](financial-backtesting.md) using financial metrics (Sharpe ratio, max drawdown, total return, win rate).

## Common Pitfalls

### Assuming User Feedback Is Needed

This version of the flywheel exclusively relies on production logs and automated teacher/judge models for evaluation. There is no ingestion or use of explicit user feedback (positive or negative) in any part of the evaluation, training, or promotion process. Attempts to influence model selection or improvement via user thumbs-up/down or similar feedback mechanisms will have no effect.

### Over-trusting a High Accuracy %

A high F1-score (e.g., 0.95) indicates strong overall alignment with reference outputs, but the remaining 5% of cases may include critical or policy-violating errors. The system's automated F1-score metric does not guarantee safety or correctness in all scenarios. For financial workloads, two models with the same F1-score can produce very different trading outcomes — use [backtest evaluation](financial-backtesting.md) to validate that model signals translate into profitable strategies. Always review divergent cases and consider additional guardrails or human review for high-risk workloads.

### Ignoring Test-Time Compute

Test-time compute is not just a function of model size; smaller models may generate longer outputs or require more tokens to achieve similar results, potentially increasing latency and cost. The developer example does not automatically optimize for or report on total compute cost. When comparing models, always consider both latency and total tokens generated per request, and validate under realistic production loads.

### Data Leakage

The developer example includes deduplication and validation steps to reduce the risk of data leakage between evaluation, training, and reference datasets. However, it is your responsibility to ensure that no overlap exists, especially if datasets are updated or re-used. Overlapping data can lead to inflated evaluation scores and misleading results.

> **📖 For data validation requirements:** See [Dataset Validation](dataset-validation.md)

### Un-tagged Workloads

Workload IDs are essential for correct data partitioning, evaluation, and reporting. The system expects all records to be tagged with a unique workload ID; missing or inconsistent IDs will result in improper dataset splits and unreliable comparisons. Always ensure that your data ingestion and logging pipelines assign and preserve workload IDs.

> **📖 For data logging implementation:** See [Data Logging for AI Apps](data-logging.md)


## Operational Tips

### Start with a Small Subset of Traffic to Shorten Iteration Cycles

Begin by routing only a small portion of your production or evaluation traffic to new models or configurations. This approach allows you to:

- Quickly validate changes and catch issues early, reducing risk.
- Use the `eval_size` and `val_ratio` parameters in your configuration to control the number of records used for evaluation and validation.
- Iterate faster by focusing on a representative sample before scaling up to the full workload.
- Roll back or adjust based on early feedback without impacting the majority of users or data.

> **📖 For data split tuning:** See [Data Split Configuration](03-configuration.md#data-split-configuration)

### Schedule Jobs During Off-Peak Hours if Using Shared Infrastructure

If your environment shares compute resources with other teams or workloads, consider running intensive jobs (such as training, evaluation, or large-scale data processing) during off-peak hours. This can:

- Reduce contention for resources, leading to faster and more reliable job completion.
- Minimize the impact on other critical workloads.
- Be automated using workflow schedulers, cron jobs, or cloud-native orchestration tools.
- Leverage the system's support for asynchronous job execution (e.g., Celery tasks) to queue jobs for later execution.

> **📖 For workflow orchestration details:** See [Task Orchestration and Workflow Management](08-workflow-orchestration.md)

### Keep Historical Job Results; Improvements Aren't Always Monotonic

Always retain the results of previous jobs, including evaluation metrics and model performance data. This practice is important because:

- Model improvements may not be linear; sometimes, changes can degrade performance on certain workloads or metrics.
- Historical results allow you to compare new outcomes against established baselines and detect regressions.
- The system tracks job runs and results in persistent storage (KDB-X tables such as `flywheel_runs`).
- Keeping a record of past results supports root cause analysis and informed rollback decisions if needed.

### Tune `data_split_config` as You Learn Workload Characteristics

This developer example provides configuration options to control how data is partitioned:

- `data_split_config` controls the partitioning of data into evaluation, training, and validation sets using **class-aware stratified splitting**. Adjust `eval_size`, `val_ratio`, `min_total_records`, and `stratify_enabled` to match your workload's size and diversity.
- Monitor the impact of these settings on evaluation outcomes and iterate as you gather more data about your workloads.
- Refer to the configuration files and code (`src/config.py`, `src/tasks/tasks.py`, and `src/lib/flywheel/util.py`) for details on how these parameters are used in practice.

> **📖 For all configuration options:** See [Model Integration & Evaluation Settings](03-configuration.md#evaluation-settings)

### Data Split Performance & Troubleshooting

#### Performance Characteristics
- **Small datasets** (< 100 records): Minimal overhead
- **Large datasets** (> 10,000 records): May require `limit` parameter tuning
- **Highly imbalanced classes**: Consider adjusting `eval_size` relative to smallest class

#### Common Issues & Solutions
| Issue | Cause | Solution |
|-------|-------|----------|
| "Insufficient samples per class" | `eval_size` too large for available classes | Reduce `eval_size` or increase dataset size |
| Uneven class distribution | Too many rare classes | Check class balance with `get_tool_name()` analysis |
| Non-reproducible splits | Missing `random_seed` | Set `random_seed: 42` in config |

#### When Stratification Falls Back to Random Splitting
The system automatically falls back to random splitting when:
- Stratification is disabled (`stratify_enabled: false`)
- Only one unique class exists (`num_classes == 1`)
- Split size is smaller than the number of classes (`test_size < num_classes`)

Classes with very few samples (≤ `rare_class_threshold`) are grouped as `"others"` to improve stratification stability.

**Source Reference**: See `src/lib/flywheel/util.py:219-245` for the `_safe_stratified_split` fallback logic.

