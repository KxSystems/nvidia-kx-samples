<!--
  SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->

# Hybrid Search Enhancement Plan for AI-Q Research Assistant

This document outlines the current hybrid search implementation and the roadmap for future enhancements to the KDB-X MCP integration in AI-Q.

## Current Implementation (v1.0 - Quick Win)

### What's Implemented

The current implementation provides **parallel execution** of KDB+ and RAG searches with **result merging**:

```
Query → [Parallel Execution] → [Merge Results] → Unified Answer
              ↓                      ↓
         KDB+ Search           RAG Search
         (financial)           (documents)
```

#### Key Features

| Feature | Description |
|---------|-------------|
| **Parallel Execution** | KDB+ and RAG queries run simultaneously using `asyncio.gather()` |
| **Result Merging** | Combines quantitative (KDB+) and qualitative (RAG) results |
| **Source Attribution** | Merged results clearly indicate which source provided what data |
| **Relevancy Checking** | Both sources are checked for relevancy before merging |
| **Fallback Support** | Web search fallback if neither source has relevant results |
| **Backward Compatibility** | `hybrid_mode=False` preserves sequential behavior |

#### Files Modified

- `aira/src/aiq_aira/search_utils.py` - Core hybrid search logic
- `aira/src/aiq_aira/prompts.py` - Query planner instructions for hybrid mode

#### Usage

Hybrid mode is enabled by default when both KDB+ and RAG are available:

```python
# Automatic hybrid search (default)
result = await process_single_query(
    query="What was Apple's Q3 2024 performance?",
    config=config,
    writer=writer,
    collection="financial_reports",  # RAG collection
    llm=llm,
    search_web=True,
    use_kdb=True,  # Enable KDB+
    hybrid_mode=True  # Default: parallel execution
)
```

#### Example Output

When a query like "What was Apple's stock performance in Q3 2024?" is processed:

```
**Financial Data (KDB+):**
Apple (AAPL) stock price on September 30, 2024: $233.00
Q3 2024 trading range: $196.00 - $237.49
Average daily volume: 52.3M shares

**Document Analysis (RAG):**
According to Apple's Q3 2024 earnings report, the company reported
revenue of $85.8 billion, up 5% year-over-year. iPhone sales
remained strong at $43.3 billion, driven by iPhone 15 Pro demand...
```

---

## Future Enhancement Roadmap

### Phase 1: Semantic Query Classification (Target: Q2 2025)

**Goal:** Replace binary query classification with multi-label confidence scoring.

#### Current Behavior
```python
# Returns single source: 'kdb' | 'rag' | 'web'
query_type = classify_query_type(query)
```

#### Enhanced Behavior
```python
# Returns confidence scores for each source
scores = classify_query_sources(query)
# Example: {"kdb": 0.95, "rag": 0.45, "web": 0.10}
```

#### Implementation Plan

1. **Add embedding-based similarity** to data source descriptions
2. **Train lightweight classifier** on query-source pairs
3. **Use confidence thresholds** for source inclusion:
   - Score > 0.7: Primary source
   - Score 0.4-0.7: Secondary source (include if available)
   - Score < 0.4: Skip source

#### Benefits
- More accurate routing for ambiguous queries
- Reduced unnecessary API calls
- Better resource utilization

---

### Phase 2: Query Decomposition (Target: Q2 2025)

**Goal:** Split complex queries into sub-queries optimized for each data source.

#### Example

**Input Query:** "How did Apple's stock react to the iPhone 16 announcement and what are analysts saying?"

**Decomposed Queries:**
```json
{
  "kdb_queries": [
    "AAPL stock price September 9-15 2024",
    "AAPL trading volume around September 9 2024"
  ],
  "rag_queries": [
    "Apple iPhone 16 announcement analyst reactions",
    "iPhone 16 features and market expectations"
  ],
  "web_queries": [
    "Apple iPhone 16 announcement news September 2024"
  ]
}
```

#### Implementation Plan

1. **Add query decomposition prompt** in `prompts.py`
2. **Create query planner agent** that:
   - Analyzes query complexity
   - Identifies sub-queries for each source
   - Maintains query relationships for synthesis
3. **Parallel execution** of all sub-queries
4. **Intelligent synthesis** of sub-query results

---

### Phase 3: KDB-X Vector Search Integration (Target: Q3 2025)

**Goal:** Add semantic similarity search to KDB-X alongside SQL queries.

#### Architecture

```
KDB-X Query
    ├── SQL Path (structured queries)
    │   └── "SELECT price FROM daily WHERE sym='AAPL'"
    │
    └── Vector Path (semantic queries)
        └── "Find news similar to 'AI chip competition'"
```

#### Prerequisites
- KDB.AI integration (vector database extension)
- Embedding model deployment (e.g., sentence-transformers)
- Index creation for text columns (news, descriptions)

#### Implementation Plan

1. **Add embedding generation** for queries
2. **Create vector search MCP tool** in KDB-X server
3. **Hybrid ranking** combining SQL relevance + vector similarity
4. **Automatic routing** between SQL and vector based on query type

#### Benefits
- Semantic search over news headlines
- Similar company/event discovery
- Fuzzy matching for entity names

---

### Phase 4: Advanced Result Synthesis (Target: Q3 2025)

**Goal:** Intelligent merging with conflict resolution and source quality scoring.

#### Features

1. **Conflict Detection**
   ```python
   # Detect when sources disagree
   kdb_price = 233.00
   web_price = 232.50  # Slight difference (acceptable)

   # Flag significant conflicts
   if abs(kdb_price - web_price) / kdb_price > 0.05:
       flag_conflict(kdb_result, web_result)
   ```

2. **Source Quality Metrics**
   ```python
   quality_scores = {
       "kdb": 0.95,   # Authoritative for financial data
       "rag": 0.85,   # Document-backed analysis
       "web": 0.60    # Variable quality
   }
   ```

3. **Temporal Weighting**
   - Prefer recent data for time-sensitive queries
   - Weight historical accuracy for trend analysis

4. **Citation Confidence**
   - Track citation density per source
   - Flag unverified claims

#### Implementation Plan

1. **Create `HybridSynthesizer` class** with:
   - Conflict detection algorithms
   - Source quality scoring
   - Temporal analysis
2. **Add synthesis prompts** for LLM-based merging
3. **Implement provenance tracking** for all claims

---

### Phase 5: Progressive Search (Target: Q4 2025)

**Goal:** Return fast results immediately, enhance with slower sources.

#### User Experience

```
[0.5s] Quick answer from cached/fast source
[2.0s] Enhanced with KDB+ data
[3.5s] Enriched with RAG context
[5.0s] Final answer with web verification
```

#### Implementation Plan

1. **Streaming result updates** via SSE
2. **Priority queue** for source execution
3. **Incremental UI updates** showing progressive enhancement
4. **User control** for "quick" vs "thorough" mode

---

### Phase 6: Source Specialization Profiles (Target: Q4 2025)

**Goal:** Dynamic source selection based on query domain and user preferences.

#### Profile Examples

```yaml
# Financial Analysis Profile
financial_analysis:
  primary_sources:
    - kdb: {weight: 0.9, tables: [daily, trade, fundamentals]}
    - rag: {weight: 0.7, collections: [sec_filings, earnings_calls]}
  fallback_sources:
    - web: {weight: 0.4, domains: [bloomberg.com, reuters.com]}

# Research Profile
academic_research:
  primary_sources:
    - rag: {weight: 0.9, collections: [research_papers, patents]}
  fallback_sources:
    - web: {weight: 0.6, domains: [arxiv.org, pubmed.gov]}
```

#### Implementation Plan

1. **Create profile configuration schema**
2. **User preference storage** in session/user settings
3. **Domain detection** for automatic profile selection
4. **Profile inheritance** (user > domain > default)

---

## Configuration Reference

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `HYBRID_SEARCH_ENABLED` | Enable hybrid search mode | `true` |
| `HYBRID_SEARCH_TIMEOUT` | Max wait for all sources | `30s` |
| `HYBRID_MERGE_STRATEGY` | Merge strategy: `concat`, `weighted`, `llm` | `concat` |
| `KDB_SEARCH_WEIGHT` | KDB result weight (0-1) | `0.9` |
| `RAG_SEARCH_WEIGHT` | RAG result weight (0-1) | `0.8` |
| `WEB_SEARCH_WEIGHT` | Web result weight (0-1) | `0.6` |

### API Parameters

```python
# /generate_summary endpoint
{
    "topic": "Apple Q3 2024 Analysis",
    "collection": "financial_reports",
    "use_kdb": true,
    "use_web": true,
    "hybrid_mode": true,  # Enable parallel execution
    "hybrid_config": {    # Optional: fine-tuning
        "merge_strategy": "weighted",
        "source_weights": {
            "kdb": 0.9,
            "rag": 0.8
        },
        "min_confidence": 0.5
    }
}
```

---

## Benefits Summary

| Benefit | Current | Phase 1-2 | Phase 3-4 | Phase 5-6 |
|---------|---------|-----------|-----------|-----------|
| Parallel execution | ✅ | ✅ | ✅ | ✅ |
| Result merging | ✅ | ✅ | ✅ | ✅ |
| Semantic classification | ❌ | ✅ | ✅ | ✅ |
| Query decomposition | ❌ | ✅ | ✅ | ✅ |
| Vector search | ❌ | ❌ | ✅ | ✅ |
| Conflict resolution | ❌ | ❌ | ✅ | ✅ |
| Progressive results | ❌ | ❌ | ❌ | ✅ |
| Source profiles | ❌ | ❌ | ❌ | ✅ |

---

## Testing the Current Implementation

### Manual Testing

```bash
# 1. Start the backend with KDB enabled
export KDB_ENABLED=true
export KDB_MCP_ENDPOINT=https://kdbxmcp.kxailab.com/mcp
uv run nat serve --config_file configs/config.yml --host 0.0.0.0 --port 3838

# 2. Test hybrid search via API
curl -X POST http://localhost:3838/generate_summary/stream \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "Apple stock performance in 2024",
    "report_organization": "Analyze price trends and key events",
    "collection": "financial_reports",
    "use_kdb": true,
    "use_web": false
  }'
```

### Expected Log Output

```
INFO - HYBRID SEARCH: Running KDB+ and RAG in parallel for: Apple stock performance...
INFO - HYBRID SEARCH complete. Sources used: KDB+, RAG
```

### Unit Tests

```bash
# Run hybrid search tests
uv run pytest test_aira/test_search_utils.py -k "hybrid" -v
```

---

## Contributing

To contribute to hybrid search enhancements:

1. Review the phase you want to work on
2. Create a feature branch: `feature/hybrid-search-phase-X`
3. Implement with tests
4. Submit PR referencing this document

See [CONTRIBUTING.md](../CONTRIBUTING.md) for guidelines.
