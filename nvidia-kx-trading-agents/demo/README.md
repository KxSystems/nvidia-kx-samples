# Create Research Reports with AI Trading Agents

AI Trading Agents builds off of the NVIDIA RAG Blueprint, allowing users to upload multi-modal PDFs and then create detailed research reports, with KDB-X financial data integration for time-series analysis.

## Getting Started

### Step 1: Select Data Sources

Choose one or more data sources for your research. You can combine multiple sources for comprehensive results.

Core sources:

- **KDB-X Database** - Query financial time-series data (stocks, trades, quotes)
- **Documents (RAG)** - Search through your uploaded document collections
- **Web Search** - Search the internet for up-to-date information using Tavily

Additional **source agents** appear in the selector when their backend credentials are configured — for example market data, news headlines, fundamentals, SEC filings, macroeconomic data (FRED), OneTick, and KDB-X documentation/point-in-time agents. The full list and live availability are served by the `/source_agents` endpoint.

### Step 2: Define Report Topic and Structure

Enter your research topic and customize the report structure. You can specify:

- **Report Topic** - The main subject of your research (e.g., "Compare the trade volume of NVIDIA in 2023 vs 2024")
- **Report Structure** - Define sections, target audience, and tone
- **Research breadth** - How many queries the planner targets: *Focused* (~3), *Standard* (~5), or *Broad* (~8)
- **Research depth** - *Fast* (1 pass), *Deep* (2 passes — a second "deepen" hop built on the first round), or *Autonomous* (a supervisor agent decides which agents to call and when to stop)

```
# Example Report Topic
Compare the trade volume of NVIDIA in 2023 vs 2024

# Example Report Structure
Sections:
1. Executive Summary
2. Background & Context
3. Key Findings
4. Analysis
5. Conclusions & Recommendations

Audience: Business executives and technical leaders
Tone: Professional, data-driven
```

### Step 3: Generate Research Plan

AI Trading Agents uses the **Llama Nemotron Super** reasoning model to generate a research plan. You can watch the model's thinking process in real-time as it plans your queries.

### Step 4: Review and Execute Research Plan

Once reasoning is complete, review the generated research queries. Each query includes:

- **Query** - The specific question to research
- **Report Section** - Which report section this query supports
- **Rationale** - Why this query is important

You can add, edit, or remove queries before executing the plan.

```
# Example Research Plan

Query 1: Retrieve NVIDIA's daily trade volume (in shares and USD value) for the full years 2023 and 2024
Section: Background & Context
Rationale: Provides raw data for comparison

Query 2: Identify all material events, earnings reports, product launches, regulatory changes...
Section: Key Findings
Rationale: Context for volume fluctuations

Query 3: Compare NVIDIA's trade volume volatility (standard deviation of daily volumes)...
Section: Analysis
Rationale: Deeper statistical analysis
```

### Step 5: Monitor Report Generation

Click **Execute Plan** to start generating the report. The Agent Activity panel shows real-time progress as the system works through the plan — searching the selected sources, writing report content, reflecting and gap-filling, and finalizing formatting and citations. The exact step labels are driven by the backend and reflect which agents are running.

### Step 6: Q&A with Your Report

After the report is generated, use the Q&A interface to:

- Ask follow-up questions about the report
- Request summaries of specific sections
- Rewrite sections with different focus
- Export or share the final report

## KDB-X Data Management

KDB-X has its own workspace, reachable from the top navigation (not from Settings). It provides two tabs:

- **Chat** - Natural-language queries against your financial data
- **Load Data** - Historical-data loader, shown only when the internal data loader is enabled (`KDB_MCP_INTERNAL=true`)

### Loading Historical Data

When the **Load Data** tab is available:

1. Open the **KDB-X** workspace from the top navigation
2. Switch to the **Load Data** tab
3. Select stock symbols (AAPL, GOOG, MSFT, TSLA, AMZN, etc.)
4. Click to load historical data

> **Note:** The data loader is for testing and demonstration purposes only. Data is sourced from Yahoo Finance with synthetic intraday generation.

### KDB Chat - Natural Language Queries

The **Chat** tab lets you query your financial data using natural language:

- Ask about available tables and their schemas
- Query stock prices, trade volumes, and market data
- The system translates your questions to q/SQL automatically (subject to the SQL execution guardrail)

```
# Example KDB Chat Queries

User: What tables are available?
System: Lists the tables currently loaded in the database (e.g. daily, fundamentals,
        news, quote, t, recommendations, trade), discovered at query time.

User: Show me NVIDIA's highest trading volume day in 2024
System: [Executes SQL query and returns results]
```

## Features Summary

| Feature | Description |
|---------|-------------|
| Multi-Source Research | Combine KDB-X, RAG, Web Search, and additional source agents |
| Reasoning Transparency | Watch AI thinking in real-time |
| Agent Activity | Track search operations with timing |
| Interactive Q&A | Ask questions about generated reports |
| Natural Language to SQL | Query KDB-X in plain English |
| Batch Data Loading | Load historical stock data with progress |

## Example Use Cases

1. **Financial Analysis**: "Compare AAPL and MSFT stock performance in Q4 2024"
2. **Market Research**: "Analyze trading volume patterns for tech stocks during earnings season"
3. **Multi-Source Reports**: "Research NVIDIA's AI strategy combining financial data and news articles"
4. **Historical Trends**: "Show year-over-year revenue growth for Amazon from SEC filings"
