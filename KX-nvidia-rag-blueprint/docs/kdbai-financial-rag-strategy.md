# KDB.AI Financial RAG - Strategic Summary

## The Problem: "Death by a Thousand Chunks"

Standard RAG retrieves many small, fragmented chunks without context. LLMs get overwhelmed with disconnected snippets, producing poor answers for complex financial queries.

---

## The Opportunity: Analytical RAG

**Standard RAG:** Search chunks → Send to LLM

**Analytical RAG:** Analyze + Search + Compute (server-side) → Enriched context to LLM

---

## Three Tiers of Implementation

| Tier | Capability | KDB.AI Unique? | Effort |
|------|------------|----------------|--------|
| **Tier 1** | Temporal metadata filtering (year, quarter, ticker) | No - any vector DB | Low |
| **Tier 2** | Server-side analytics + vector search in one query | Yes | Medium |
| **Tier 3** | Event correlation, time-series joins, real-time + historical | Yes | High |

---

## Tier 1: Temporal RAG (Commodity)

- Extract metadata from filenames (ticker, fiscal_year, filing_type)
- Store as filterable columns in KDB.AI
- Filter BEFORE vector search to reduce chunk noise
- **Not a differentiator** - Milvus, Pinecone, etc. can do this

---

## Tier 2: Analytical RAG (Differentiator)

- Combine vector search with computed metrics in single query
- Example: "Why did Boeing stock drop?" returns chunks + computed price change + exact dates
- Leverage q language for server-side aggregations
- **Requires:** Custom q functions, hybrid queries

---

## Tier 3: Event-Driven RAG (Unique)

- **Cross-temporal analysis:** Compare documents across time periods
- **Event correlation:** Link filing content to market events (earnings, price moves)
- **As-of queries:** Point-in-time document retrieval
- **Real-time + historical:** Streaming data + vector search
- **Requires:** Additional data tables (prices, earnings), complex q logic

---

## Data Requirements

### Current (Tier 1)
- SEC 10-K filings (already have)
- Temporal metadata extraction (filename parsing)

### For Tier 2-3
- Stock price history (daily OHLCV)
- Earnings dates and estimates
- Index membership/sector data
- Real-time price feed (optional)

---

## Schema Evolution

```
Current:
┌─────────────────────────────────┐
│ chunks                          │
│ - id, text, vector, source      │
└─────────────────────────────────┘

Tier 1:
┌─────────────────────────────────┐
│ chunks                          │
│ - id, text, vector, source      │
│ - ticker, fiscal_year, quarter  │
│ - filing_type, filing_date      │
│ - section                       │
└─────────────────────────────────┘

Tier 2-3:
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ chunks       │    │ prices       │    │ earnings     │
│ (vectors)    │◄──►│ (time-series)│◄──►│ (events)     │
└──────────────┘    └──────────────┘    └──────────────┘
        Cross-table temporal joins via q
```

---

## Key Differentiating Queries (Tier 2-3)

1. **Comparative:** "How did risk factors change post-COVID across tech companies?"
2. **Causal:** "What did Tesla disclose before each earnings miss?"
3. **Analytical:** "Is NVDA's current valuation justified vs historical?"
4. **Temporal:** "What was said about supply chain within 30 days of stock drops?"

---

## Implementation Priority

1. **Quick Win (1-2 days):** Tier 1 temporal filtering - immediate improvement, portable
2. **Medium Term (1-2 weeks):** Tier 2 analytics - true KDB.AI value, requires q knowledge
3. **Long Term (1+ month):** Tier 3 event-driven - full financial analyst assistant

---

## Files to Modify

| File | Changes |
|------|---------|
| `src/nvidia_rag/utils/vdb/kdbai/kdbai_vdb.py` | Schema update, temporal columns, hybrid query support |
| `src/nvidia_rag/ingestor_server/main.py` | Metadata extraction from filenames |
| `src/nvidia_rag/rag_server/main.py` | Query understanding, temporal filter injection |
| `NEW: src/nvidia_rag/utils/vdb/kdbai/analytics.q` | Server-side q functions for Tier 2-3 |

---

## Bottom Line

- **Tier 1** = Table stakes, not a selling point
- **Tier 2-3** = True KDB.AI differentiation, but requires investment
- **Unique value** = Combining vector search with kdb+'s analytical/temporal engine
- **Target user** = Financial analysts who need computed insights, not just document search

---

## Today's Session Accomplishments

### cuVS Fixes Implemented
1. Updated KDB.AI image to `1.8.1-rc.2-cuvs`
2. Fixed `itopk_size` parameter passing via `index_params={"itopk_size": 128}`
3. Confirmed multi-batch CAGRA extend fix works (no more crashes)
4. Deployed and tested on EKS with GPU acceleration

### Test Results
- 16,164 SEC filing chunks ingested with cuVS CAGRA index
- Multi-batch ingestion (200 records/batch) working
- GPU search with configurable itopk_size operational

---

# Implementation Plan

## Phase 1: Tier 1 - Temporal Metadata (1-2 days)

### Step 1.1: Update KDB.AI Schema
**File:** `src/nvidia_rag/utils/vdb/kdbai/kdbai_vdb.py`

**Tasks:**
- [ ] Add new columns to `DEFAULT_TABLE_SCHEMA`:
  - `ticker` (str) - Company symbol
  - `fiscal_year` (int) - Fiscal year of filing
  - `fiscal_quarter` (str) - Q1/Q2/Q3/Q4 or FY for annual
  - `filing_type` (str) - 10-K, 10-Q, 8-K
  - `filing_date` (date) - Date filed with SEC
  - `section` (str) - Document section (Risk Factors, MD&A, etc.)
- [ ] Update `create_collection()` to use new schema
- [ ] Update `write_to_index()` to accept and store metadata fields
- [ ] Add index on `ticker` and `fiscal_year` for fast filtering

### Step 1.2: Metadata Extraction at Ingestion
**File:** `src/nvidia_rag/ingestor_server/main.py`

**Tasks:**
- [ ] Create `extract_sec_metadata(filename)` function:
  - Parse filename pattern: `{TICKER}_{FILING_TYPE}_{YEAR}.html`
  - Example: `NVDA_10K_2023.html` → ticker=NVDA, filing_type=10-K, fiscal_year=2023
- [ ] Optionally parse filing date from document content
- [ ] Pass extracted metadata to VDB write operations
- [ ] Add section detection (parse HTML structure for 10-K sections)

### Step 1.3: Temporal Filtering in Retrieval
**File:** `src/nvidia_rag/rag_server/main.py`

**Tasks:**
- [ ] Add optional filter parameters to `/search` and `/generate` endpoints:
  - `ticker_filter`: List of tickers
  - `year_from` / `year_to`: Fiscal year range
  - `filing_types`: List of filing types
- [ ] Modify `retrieval_langchain()` to build KDB.AI filter expressions
- [ ] Update API documentation

### Step 1.4: Query Understanding (Basic)
**File:** `src/nvidia_rag/rag_server/query_parser.py` (NEW)

**Tasks:**
- [ ] Create simple regex/rule-based temporal extractor:
  - "NVDA 2023" → ticker=NVDA, year=2023
  - "last year" → year=current_year-1
  - "Boeing before 2020" → ticker=BA, year_to=2019
- [ ] Integrate with retrieval pipeline

### Step 1.5: Re-ingest SEC Filings
**Tasks:**
- [ ] Delete existing collections
- [ ] Run batch ingestion with metadata extraction enabled
- [ ] Verify metadata stored correctly

### Deliverables - Phase 1:
- Temporal filtering working via API parameters
- Basic query understanding for time expressions
- SEC filings re-ingested with full metadata

---

## Phase 2: Tier 2 - Analytical RAG (1-2 weeks)

### Step 2.1: Additional Data Tables
**Tasks:**
- [ ] Create `prices` table in KDB.AI:
  - Schema: `ticker`, `date`, `open`, `high`, `low`, `close`, `volume`
  - Source: Yahoo Finance, Alpha Vantage, or similar
- [ ] Create `earnings` table:
  - Schema: `ticker`, `report_date`, `fiscal_quarter`, `eps_estimate`, `eps_actual`, `surprise_pct`
  - Source: Financial APIs
- [ ] Create data ingestion scripts for these tables

### Step 2.2: Server-Side q Functions
**File:** `src/nvidia_rag/utils/vdb/kdbai/analytics.q` (NEW)

**Tasks:**
- [ ] `getStockPerformance[ticker; startDate; endDate]` - Returns price change %
- [ ] `getEarningsSurprises[ticker; n]` - Returns last n earnings surprises
- [ ] `getPriceAroundDate[ticker; date; daysBefore; daysAfter]` - Price window
- [ ] `compareDocuments[ticker; year1; year2; section]` - Text similarity
- [ ] Deploy q functions to KDB.AI server

### Step 2.3: Hybrid Query Interface
**File:** `src/nvidia_rag/utils/vdb/kdbai/kdbai_vdb.py`

**Tasks:**
- [ ] Add `execute_analytics(q_expression)` method
- [ ] Create `hybrid_search(query_vec, analytics_query)` method
- [ ] Return combined results: chunks + computed metrics

### Step 2.4: Enhanced Query Understanding
**File:** `src/nvidia_rag/rag_server/query_parser.py`

**Tasks:**
- [ ] Use LLM to classify query intent:
  - `FACTUAL` - Simple document lookup
  - `COMPARATIVE` - Cross-time/company comparison
  - `CAUSAL` - Why did X happen?
  - `ANALYTICAL` - Requires computation
- [ ] Extract entities: tickers, dates, metrics
- [ ] Generate appropriate analytics query

### Step 2.5: Context Enrichment
**File:** `src/nvidia_rag/rag_server/main.py`

**Tasks:**
- [ ] For ANALYTICAL queries, fetch computed data alongside chunks
- [ ] Format analytics results for LLM context
- [ ] Example prompt injection: "Stock data shows BA dropped 24% in March 2019. Relevant documents:"

### Deliverables - Phase 2:
- Price and earnings data loaded in KDB.AI
- Server-side q analytics functions
- Query intent classification
- Enriched context with computed metrics

---

## Phase 3: Tier 3 - Event-Driven RAG (1+ month)

### Step 3.1: Event Detection System
**Tasks:**
- [ ] Define event types:
  - Earnings miss/beat (>5% surprise)
  - Stock price drop (>10% in week)
  - Significant filing (8-K material events)
- [ ] Create event detection queries in q
- [ ] Build event timeline table

### Step 3.2: Temporal Correlation Engine
**File:** `src/nvidia_rag/utils/vdb/kdbai/correlation.q` (NEW)

**Tasks:**
- [ ] `findFilingsBeforeEvent[eventType; ticker; daysBefore]`
- [ ] `correlateDisclosures[eventType; section; threshold]`
- [ ] `detectPatterns[ticker; eventType; nEvents]`
- [ ] As-of join functions for point-in-time queries

### Step 3.3: Cross-Document Analysis
**Tasks:**
- [ ] Implement document diff: compare same section across years
- [ ] Compute similarity scores for change detection
- [ ] Identify new disclosures vs boilerplate

### Step 3.4: Real-Time Integration (Optional)
**Tasks:**
- [ ] Connect to real-time price feed (kdb+ tick)
- [ ] Streaming event detection
- [ ] Alert-triggered RAG queries

### Step 3.5: Advanced Query Patterns
**Tasks:**
- [ ] Natural language → complex q query translation
- [ ] Multi-step reasoning chains
- [ ] Automated insight generation

### Deliverables - Phase 3:
- Event detection and correlation
- Cross-temporal document analysis
- Pattern recognition across filings
- (Optional) Real-time streaming integration

---

## Testing Plan

### Phase 1 Tests
- [ ] Verify metadata extracted correctly from filenames
- [ ] Test temporal filters return correct date ranges
- [ ] Benchmark retrieval with/without filters (measure chunk reduction)

### Phase 2 Tests
- [ ] Verify analytics queries return correct calculations
- [ ] Test hybrid search returns both chunks and metrics
- [ ] Evaluate answer quality for analytical queries

### Phase 3 Tests
- [ ] Validate event correlation accuracy
- [ ] Test cross-document comparison results
- [ ] End-to-end tests for complex financial queries

---

## Success Metrics

| Metric | Phase 1 Target | Phase 2 Target | Phase 3 Target |
|--------|---------------|----------------|----------------|
| Chunk noise reduction | 50% fewer irrelevant chunks | 70% | 85% |
| Query latency | <500ms | <1s | <2s |
| Answer accuracy (eval set) | 70% | 85% | 90% |
| Unique KDB.AI features used | 1 (filtering) | 3+ (analytics) | 5+ (full q) |

---

## Dependencies & Prerequisites

### Technical
- [ ] KDB.AI server with q function deployment capability
- [ ] Access to financial data APIs (prices, earnings)
- [ ] LLM for query understanding (existing)

### Knowledge
- [ ] q/kdb+ programming for Phase 2-3
- [ ] SEC filing structure understanding
- [ ] Financial domain knowledge

### Infrastructure
- [ ] Storage for additional tables (~10GB for 10 years of price data)
- [ ] (Optional) Real-time feed infrastructure for Phase 3

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| q learning curve | Start with simple functions, iterate |
| Data quality (prices/earnings) | Use established data providers, validate |
| Query understanding errors | Fallback to standard RAG if classification fails |
| Performance degradation | Benchmark each phase, optimize hot paths |

---

## Open Questions

1. **Data sources:** Which financial data provider to use? (Yahoo Finance free vs paid APIs)
2. **Section parsing:** How accurate does 10-K section detection need to be?
3. **q deployment:** How to deploy custom q functions to KDB.AI Cloud vs Server?
4. **Real-time scope:** Is Phase 3 real-time integration in scope for MVP?

---

*Document created: 2025-01-09*
*Status: Planning document - not committed*
