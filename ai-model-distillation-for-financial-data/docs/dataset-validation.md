# Dataset Validation

Learn about the data validation process used by the developer example. This validation process ensures that all data follows the OpenAI Chat Completion format and meets quality standards before being used for training or evaluation.

## Validation Flow Diagram

```sh
┌─────────────────────────┐
│   Start Validation      │
│   Input: Records,       │
│   Workload Type, Limit  │
└─────────────────────────┘
            │
            ▼
┌─────────────────────────┐
│  validate_records_count │
│  - Check min_records    │
│  - Check eval_size      │
│  - Check limit validity │
└─────────────────────────┘
            │
            ▼
┌─────────────────────────┐
│  Separate by Format     │
│  - Valid OpenAI format  │
│  - Invalid format       │
└─────────────────────────┘
            │
     ┌──────┴──────┐
     │             │
  Valid         Invalid
     │             │
     ▼             ▼
┌─────────────┐ ┌─────────────┐
│Valid OpenAI │ │  Track      │
│  Records    │ │  Invalid    │
└─────────────┘ │  Count      │
     │          └─────────────┘
     ▼
┌─────────────────────────┐
│ Apply Quality Filters   │
│ Based on Workload Type  │
└─────────────────────────┘
            │
     ┌──────┴──────┐
     │             │
TOOL_CALLING    GENERIC
     │             │
     ▼             ▼
┌─────────────┐ ┌─────────────┐
│ Validate:   │ │ No Special  │
│ - Has tool  │ │ Validation  │
│   calls     │ │             │
│ - Valid     │ │             │
│   function  │ │             │
│   args JSON │ │             │
│ - Parse     │ │             │
│   args to   │ │             │
│   objects   │ │             │
└─────────────┘ └─────────────┘
     │             │
     └──────┬──────┘
            ▼
┌─────────────────────────┐
│  Remove Duplicates      │
│  Based on User Queries  │
└─────────────────────────┘
            │
            ▼
┌─────────────────────────────────────┐
│  Check: Have >= min_total_records   │
│  valid records?                     │
└─────────────────────────────────────┘
            │
     ┌──────┴──────┐
     │             │
  Yes│          No │
     ▼             ▼
┌─────────┐  ┌────────────────┐
│ Random  │  │ FAIL:          │
│ Select  │  │ Not Enough     │
│ limit   │  │ Valid Records  │
│ records │  └────────────────┘
└─────────┘
     │
     ▼
┌─────────────────────────┐
│  Log Statistics         │
│  Return Records         │
└─────────────────────────┘
```

## Key Components

### 1. Records Count Validation

The first validation step checks the input parameters and record counts:

- **Minimum Records Check**: Ensures total records ≥ `min_total_records`
- **Eval Size Check**: Ensures `eval_size` ≤ total records available
- **Limit Validity Check**: Ensures `limit` ≥ `min_total_records`

If any of these checks fail, the validation stops with a descriptive error message.

### 2. OpenAI Format Validation

The validator checks for a complete OpenAI format structure:

- Top-level: `request` and `response` fields
- Request: Must have `messages` list with valid message objects
- Response: Must have `choices` list with valid choice objects
- Each message: Must have `role` and appropriate content fields
- Each choice: Must have `message` field
- **Tool Properties Limit**: If tools are present, tool function parameter definitions are limited to a maximum of 8 properties (workaround for known NIM bug)

### 3. Quality Filters

Based on workload type:

#### Tool Calling Workloads

- Record must have tool calls in response with `type: "function"`
- Function arguments must be valid JSON
- Arguments are parsed from strings to JSON objects (when `parse_function_arguments` is enabled)

#### Generic Workloads

- No special validation required

### 4. Deduplication

Removes duplicate records based on user queries:

- Creates unique keys from the text `content` of user messages only
- Non-textual or multimodal content is not currently hashed or compared

### 5. Final Selection

- **If valid records ≥ limit**: Randomly selects `limit` records
- **If valid records < min_total_records**: Raises an error with detailed statistics

## Usage

### Loading Data

Load data via the API or the example notebook at [`notebooks/ai-model-distillation-financial-data.ipynb`](../notebooks/ai-model-distillation-financial-data.ipynb). Data validation happens automatically during the flywheel pipeline.

## Features

The validator implements the following logic based on the `limit` parameter from the configuration:

1. **If valid records ≥ limit**: Randomly selects `limit` records from valid ones
2. **If valid records < min_total_records**: Raises an exception asking for more valid records

### Statistics Tracked

```python
{
    "total_records": 0,
    "valid_openai_format": 0,
    "invalid_format": 0,
    "removed_quality_filters": 0,
    "deduplicated_queries": 0,
    "final_selected": 0,
}
```

### Error Messages

When there are insufficient records:

```sh
Insufficient valid records. Found {deduplicated} but need {min_records}.
Total records: {total}, valid OpenAI format: {valid_openai}, 
after quality filters: {quality_filtered}.
Please provide more valid records.
```

### Configuration

Add the following to your `config/config.yaml`:

```yaml
data_split_config:
  eval_size: 100
  val_ratio: 0.1
  min_total_records: 50
  random_seed: null
  limit: 1000
  parse_function_arguments: true
  stratify_enabled: true
  min_samples_per_class: 2
  rare_class_threshold: 1
```

## Implementation Details

The validation is implemented in two classes:

1. **OpenAIFormatValidator**: Validates the OpenAI Chat Completion format
   - Validates the request and response structure
   - Checks message roles and content
   - Applies workload-specific quality filters

2. **DataValidator**: Orchestrates the validation process
   - Uses OpenAIFormatValidator for format validation
   - Applies quality filters based on workload type
   - Handles deduplication
   - Performs final selection

## Example Usage

```python
from src.lib.integration.data_validator import DataValidator
from src.api.models import WorkloadClassification
from src.config import DataSplitConfig

validator = DataValidator()
split_config = DataSplitConfig(limit=1000, min_total_records=50)
validated_records = validator.validate_records(
    records=raw_records,
    workload_type=WorkloadClassification.GENERIC,
    split_config=split_config,
)
```

## Additional Notes

### Configuration Reference

The `DataSplitConfig` object, defined in `src/config.py`, controls parameters such as `eval_size`, `min_total_records`, `limit`, and others used during validation. Adjust these values in your configuration file (`config/config.yaml`) to change validation behavior.

### Error Handling and Logging

All validation steps and errors are logged using the project's logging system. Check your log output (as configured in the project) for detailed statistics and troubleshooting information.

### Random Seed and Reproducibility

Setting the `random_seed` parameter in your configuration ensures that the random selection of records is reproducible across runs. This is useful for consistent evaluation and debugging.

### Extending Validation

To add new workload types or custom validation rules, extend the `DataValidator` or `OpenAIFormatValidator` classes in `src/lib/integration/`. Add new methods or modify existing ones as needed to implement your custom logic.

### Example Data

Example datasets for testing can be found in the `tests/fixtures/` directory or generated using the provided scripts (see `notebooks/` and `src/scripts/`).

### Deduplication Logic

Deduplication is performed using the `content` of user messages only. Non-textual or multimodal content is not currently hashed or compared; only the text content of user messages is used to identify duplicates.

### Logging Output

Validation statistics and errors are output to the log (see your project logging configuration for details on where logs are written).
