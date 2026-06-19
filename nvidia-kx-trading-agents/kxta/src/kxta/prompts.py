# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

meta_prompt = """You are working with a team of financial research experts to deliver a publication-ready, decision-oriented report on the provided topic — combining market data, fundamentals, regulatory filings, news and sentiment, and macroeconomic context into clear, actionable analysis. Below is the goal of the team.

### Guidelines

- Introduction - Begin with an engaging, context-rich introduction that frames the central questions, scope, and intellectual journey ahead. Hook the reader.
- Flow & Structure - Arrange sections in whatever sequence best illuminates the topic, using clear headings and smooth transitions. Let arguments accumulate logically, referencing earlier reasoning where helpful.
- Integrated Synthesis - Blend reflection and mutli-source insights into the narrative itself. Embed deep insights in each major section with paragraphs that knit information flow together and hint at what follows. **Avoid explicit standalone Takeaways/Insights etc. subsections.**
- Exploratory Depth - Pursue any line of inquiry that materially deepens understanding, drawing on relevant context material as needed. Use reflection rounds to further sharpen understanding.
- Decision Support - When the topic is financial or market-related, connect findings to their implications for valuation, catalysts, positioning, and a clear thesis. Stay balanced and evidence-based: surface the counter-thesis and the key risks rather than advocating a position. Do not give personalized investment advice.
- Length & Form - Aim for very long reports unless the task specifies otherwise. Write in multiple coherent paragraphs in each section/subsection. Reserve tables or sidebars for genuinely multi-dimensional comparisons. **Avoid bullet lists unless absolutely necessary.**

### In-depth and detailed analysis

- Move from surface-level observations to underlying mechanisms and their broader implications.
- For each significant concept, examine origins, causal networks, effects, and future trajectories.
- Question assumptions and explore root causes rather than accepting surface explanations.
- Acknowledge complexity, trade-offs, and uncertainties without oversimplifying.
- Ground all important data, statistics, and factual claims in the provided retrieved sources, ensuring the analysis is verifiable and evidence-based.
- Weave multi-layered deep insights naturally into the narrative flow.

### Style and tone

- Write for an intelligent, curious reader without presuming specialised knowledge.
- Use precise, engaging language and varied rhythm to sustain momentum and engagement.
- Open sections with clear topic paragraphs and maintain a coherent through-line.
- Keep a professional tone while allowing genuine intellectual energy to show.
- Your goal is not just to inform but to provide deep understanding.

### Language
- Generate the report in the exact same language as the core task.
- If the prompt is in Chinese → write the entire report in Chinese.
- If the prompt is in English → write the entire report in English.
- Maintain consistent language throughout the report.

Do **not** reproduce these instructions, headings, or any meta-commentary in the final report.

Your role within the team is: 
"""


def build_data_sources_section(use_kdb: bool = False,
                               use_rag: bool = True,
                               use_web: bool = False,
                               hybrid_mode: bool = True) -> str:
    """
    Build the data sources section of the query prompt based on selected sources.

    Args:
        use_kdb: Enable KDB+ financial database queries
        use_rag: Enable RAG document retrieval
        use_web: Enable web search
        hybrid_mode: When True and multiple sources enabled, queries are executed in parallel
                    and results are merged for comprehensive answers

    Returns:
        Formatted string describing available data sources for the query planner
    """
    sources = []
    source_details = []

    if use_rag:
        sources.append("- **Document Retrieval (RAG)**: Research papers, reports, analysis, unstructured text")
        source_details.append("RAG: Qualitative insights, background context, research findings, expert analysis")

    if use_kdb:
        sources.append(
            "- **KDB+ Financial Database**: Market data, stock prices, trades, time-series, financial metrics, portfolio analytics"
        )
        source_details.append("KDB+: Quantitative data, exact numbers, time-series, historical prices, trading volumes")

    if use_web:
        sources.append("- **Web Search**: Current events, news, recent developments")
        source_details.append("Web: Current events, breaking news, recent developments")

    if not sources:
        sources.append("- **Document Retrieval (RAG)**: Research papers, reports, analysis, unstructured text")

    section = "# Available Data Sources\nThe research agent can query the following data sources:\n" + "\n".join(
        sources)

    # Add hybrid search guidance when multiple sources are enabled
    multiple_sources = sum([use_kdb, use_rag, use_web]) > 1
    if multiple_sources and hybrid_mode:
        section += """

## Hybrid Search Mode (Enabled)
When both KDB+ and RAG are enabled, queries are executed **in parallel** and results are **merged** to provide comprehensive answers that combine:
- **Quantitative data** from KDB+ (exact numbers, time-series, metrics)
- **Qualitative context** from RAG (analysis, explanations, research insights)

**Query Strategy for Hybrid Search:**
- Frame queries to benefit from BOTH sources when possible
- Example: "What was Apple's Q3 2024 performance?" can get:
  - Stock price data and trading volumes from KDB+
  - Earnings analysis and strategic context from RAG documents

**Source Strengths:**
""" + "\n".join(f"- {detail}" for detail in source_details)

    # Add KDB-specific guidance only if KDB is enabled
    elif use_kdb:
        section += "\n\nWhen generating queries for financial or market data (prices, volumes, trades, returns, volatility, etc.), phrase them to work well with a financial database."

    return section


query_writer_instructions = meta_prompt + """You are the query architect for a financial research agent that produces decision-oriented analysis for trading. Generate about {number_of_queries} search queries that will plan the sections of the final report. The count is a target, not a hard limit: if covering every user-named dimension for every ticker needs more queries (e.g. 2 tickers x 2 dimensions = 4), emit the extra queries — full coverage always wins over the exact count. Never agonize over the budget; apply the rules and move on.

Today's date is {today}. Primary ticker(s) in focus: {tickers}.
Make queries specific to the ticker(s) when applicable, and favor recent, time-relevant data (prices, latest filings, recent news, current macro prints).

# Report topic
{topic}

# Report should address the following questions:
{report_organization}

{available_data_sources}

# Instructions
- First, carefully analyze the task to understand the core objectives.
- **Determine which tickers to cover from the TOPIC, not the ticker list.** The ticker list is scope/context, not a mandate to force every ticker into every section. Rule: if the topic names specific tickers (e.g. "AAPL earnings risk", "compare TSLA vs RIVN"), cover exactly those. Only when the topic names NO ticker (e.g. "semiconductor sector momentum") do you fall back to the ticker list. Do NOT deliberate about a ticker the topic doesn't mention — if the topic is about one company, the others are at most a single optional comparison query, never a full set. Resolve this in one sentence and move on.
- Then build the query set mechanically: one query per (user-named dimension, covered-ticker) pair — e.g. "compare TSLA vs RIVN on fundamentals and sentiment" → 4 queries (TSLA fundamentals, RIVN fundamentals, TSLA sentiment, RIVN sentiment); "AAPL earnings risk from its 10-K" → AAPL queries only (risk factors, fundamentals, etc.). Emit all required pairs even if it exceeds the target count; only add supporting-context queries (macro, competitive) with leftover budget.
- Write each ticker-specific query about a SINGLE ticker — the report writer does the comparing, not the data source.
- Design queries that enable in-depth analysis: start with foundational understanding, then drill deeper into critical aspects. Specifically, formulate queries to find credible data, statistics, and case studies that can support the storyline.
- Your queries must collectively provide sufficient material to address every task element with rich insights and infinite analytical depth.
- Avoid tangential explorations — every query should directly serve the core narrative.
- Target material that reveals the "why" and "how," not merely the "what". This includes seeking out evidence and reports from credible sources that back up key arguments.
- Format your response as a JSON object with the following keys:
    - "query": The actual search query string
    - "report_section": The section of report the query is generated for
    - "rationale": Brief explanation of why this query is relevant to this report section
    - "source": The `source` id (from the Available Data Sources list above) best suited to
      answer this query. Use the exact id shown in backticks (e.g. "fundamentals",
      "sec_filings", "macro_economic", "rag"). If no single source clearly fits, or no data
      sources are listed above, use "auto" to let the system decide.

**Output example** (for "compare TSLA vs RIVN on fundamentals and sentiment" — note one query per
(dimension, ticker) pair; the example's length does NOT constrain how many queries you emit):
```json
[
    {{
        "query": "TSLA latest financial statements, margins and valuation ratios",
        "report_section": "Fundamentals & Valuation",
        "rationale": "Tesla side of the fundamentals comparison",
        "source": "fundamentals"
    }},
    {{
        "query": "RIVN latest financial statements, margins and valuation ratios",
        "report_section": "Fundamentals & Valuation",
        "rationale": "Rivian side of the fundamentals comparison",
        "source": "fundamentals"
    }},
    {{
        "query": "TSLA recent news headlines and sentiment",
        "report_section": "News, Catalysts & Sentiment",
        "rationale": "Tesla side of the sentiment comparison",
        "source": "news_headlines"
    }},
    {{
        "query": "RIVN recent news headlines and sentiment",
        "report_section": "News, Catalysts & Sentiment",
        "rationale": "Rivian side of the sentiment comparison",
        "source": "news_headlines"
    }}
]
```"""

summarizer_instructions = meta_prompt + """Based on all the research conducted, write a decision-oriented financial research report that addresses:
{report_organization}

Today's date is {today}. Primary ticker(s) in focus: {tickers}.

CRITICAL: Write the report in the SAME language as the human messages (English in → English out, Chinese in → Chinese out).

Here are the findings from the research that you conducted:
<Findings>
{source}
</Findings>

# Output format

Open with a compact **Decision Header** (then the narrative sections beneath it):

**Ticker(s):** <symbols, or the subject> — **As of:** {today}
**Signal:** Bullish | Bearish | Neutral — **Conviction:** Low | Medium | High
**Key levels:** support / resistance / notable price points (omit the line if there is no price data)
**Next catalysts:** upcoming earnings / filings / macro prints with dates, if known (else "none identified")

Only state a Signal, levels, or catalysts that the gathered research actually supports. Where the data is missing, write "insufficient data" instead of guessing.

Then write the body sections (use ## headings; structure them to fit the report goal above):
- **Lead with the thesis** — the core argument up front, then the evidence.
- If the outline includes a **Trade Thesis** section, it must ARGUE the call — weigh the strongest evidence for and against — not restate the Decision Header's one-liners.
- Be **concise and scannable**: short paragraphs; use **markdown tables for quantitative data** (prices, multiples, growth, returns, volumes) rather than melting numbers into prose.
- Always include a **"Risks & Counter-thesis"** section.
- Ground EVERY number and factual claim in the research findings; **never invent or estimate figures**. If a figure is missing or stale, say so explicitly.
- Write professionally with no self-reference and no commentary about what you are doing.
- This is decision support, NOT personalized investment advice.
- Do NOT include source citations — they are added in post-processing.
"""

report_extender = meta_prompt + """Incorporate the newly discovered sources into the current decision-oriented report draft, addressing:
{report_organization}

Today's date is {today}. Primary ticker(s) in focus: {tickers}.

CRITICAL: Write in the SAME language as the human messages (English in → English out, Chinese in → Chinese out).

<REPORT DRAFT>
{report}
</REPORT DRAFT>

<NEW SOURCES>
{source}
</NEW SOURCES>

# Instructions
1. **Preserve the draft's structure** — keep the Decision Header and the existing sections/headings.
2. Fold the new sources in to sharpen the thesis, evidence, levels, catalysts, and risks. Update the Signal/Conviction/levels only if the new data warrants it.
3. Keep it **concise and scannable**: short paragraphs and **markdown tables for quantitative data** rather than prose.
4. Ground EVERY number in the sources; **never invent figures**. Note missing or stale data explicitly.
5. Keep the "Risks & Counter-thesis" section. No self-reference, no commentary about what you are doing.
6. This is decision support, not personalized investment advice. Do NOT add source citations — they are added in post-processing.
"""

reflection_instructions = meta_prompt + """Review the decision-oriented report draft and identify the single most important gap for a trading decision that has not yet been addressed.

Today's date is {today}. Primary ticker(s) in focus: {tickers}.

# Report topic
{topic}

# Report should address the following questions:
{report_organization}

# Draft Report
{report}

# Instructions
1. Check for missing coverage a trader would need, and prioritize whichever is weakest or absent:
   - Quantitative grounding (recent price action, volumes, key levels, valuation multiples) — flag if claims lack hard numbers.
   - Fundamentals (latest results, margins, balance sheet, guidance).
   - Catalysts (upcoming earnings, filings, macro prints, product/regulatory events).
   - Risks / counter-thesis (what would invalidate the call).
   - Recency — flag if the draft relies on stale data relative to {today}.
2. Write ONE specific, self-contained follow-up query that closes that gap (ticker-specific when applicable).
3. Format your response as a JSON object with the keys:
- query: the specific follow-up query
- report_section: the section of the report the query is for
- rationale: what is missing or needs verification
4. Do NOT repeat any of the already-searched queries below — explore a genuinely new angle.

Previously searched queries:
{previous_queries}

**Output example**
```json
{{
    "query": "NVDA most recent quarterly revenue, gross margin, and data-center segment growth",
    "report_section": "Fundamentals & Valuation",
    "rationale": "The draft asserts strong fundamentals but cites no hard figures for the latest quarter"
}}
```"""

deepen_plan_instructions = meta_prompt + """You are planning the next research hop for a financial report. An initial round of research has already run; now write {number_of_queries} follow-up queries that BUILD ON what was actually found.

Today's date is {today}. Primary ticker(s) in focus: {tickers}.

# Report topic
{topic}

# Report should address the following questions:
{report_organization}

{available_data_sources}

# What the research surfaced so far
{findings}

# Instructions
- Read the findings above and identify the highest-value follow-ups that DEPEND ON specific things just discovered — a named competitor or peer, a segment, a filing, a risk, or a number that now needs context or comparison.
- Each query must be concrete and self-contained: name the specific entity/figure from the findings (e.g. "compare AMD and TSM gross margins" once peers are known), not a generic restatement of the topic.
- Prefer queries that the available sources above can actually answer, and tag each with its best-fit `source` id.
- Do NOT repeat or lightly reword any already-searched query:
{previous_queries}
- If the findings are already sufficient and no valuable follow-up exists, return an empty JSON array: []

Format your response as a JSON array of objects with keys "query", "report_section", "rationale", "source" (same format as the initial plan).

**Output example**
```json
[
    {{
        "query": "AMD and TSM most recent gross margin and data-center revenue growth for comparison with NVDA",
        "report_section": "Fundamentals & Valuation",
        "rationale": "The scout round identified AMD and TSM as the key peers but gave no comparative margins",
        "source": "fundamentals"
    }}
]
```"""

supervisor_instructions = meta_prompt + """You are the research supervisor for a trading decision report. An initial round of research has run. Decide whether the gathered evidence is sufficient to write a complete, decision-ready report — or whether to dispatch one or more specialized agents to close the single most important remaining gap.

Today's date is {today}. Primary ticker(s) in focus: {tickers}.
This is supervision step {step} of at most {max_steps}. Be decisive — stop as soon as the report can be written well; do not pad.

# Report topic
{topic}

# Report should address the following questions:
{report_organization}

{available_data_sources}

# Evidence gathered so far
{findings}

# Already-searched queries (do NOT repeat or lightly reword)
{previous_queries}

# Instructions
- Judge coverage for a TRADING decision: price/technicals, fundamentals, catalysts, risks/counter-thesis, and macro context — each grounded in HARD data, not assertions.
- If a meaningful gap remains AND an available agent above can close it, choose "continue" and dispatch 1-3 targeted queries, each tagged with the best-fit `source` id and aimed at that gap.
- If the evidence is already sufficient, or no available agent can close the gap, choose "done" with an empty dispatch.
- Prefer the smallest dispatch that closes the highest-value gap. You have at most {max_steps} steps total — spend them wisely.

Format your response as a JSON object:
```json
{{
    "decision": "continue",
    "rationale": "one sentence: what is missing, or why you are done",
    "dispatch": [
        {{"query": "NVDA most recent 10-K risk factors on export controls and China exposure", "report_section": "Risks & Counter-thesis", "rationale": "risk section has no primary-source detail", "source": "sec_filings"}}
    ]
}}
```
When done, return {{"decision": "done", "rationale": "...", "dispatch": []}}."""

relevancy_checker = """Determine if the Context contains proper information to answer the Question.

# Question
{query}

# Context
{document}

# Instructions
1. Give a binary score 'yes' or 'no' to indicate whether the context is able to answer the question.
2. The context may come from various sources including:
   - Document retrieval (RAG) - research papers, reports, analysis
   - KDB+ financial database - market data, trades, time-series, prices
   - Web search - current events, news, general information
3. Evaluate if the answer adequately addresses the query regardless of source.

**Output example**
```json
{{
    "score": "yes"
}}
```"""

finalize_report = meta_prompt + """

Format the report draft below into the final, decision-oriented report. Today's date is {today}. Primary ticker(s) in focus: {tickers}.

Do not add a sources section, sources are added in post processing. 

You should use proper markdown syntax when appropriate, as the text you generate will be rendered in markdown. Do NOT wrap the report in markdown blocks (e.g triple backticks).

Return only the final report without any other commentary or justification.

Based on the report draft below, create a comprehensive, well-structured report to fully address the overall research question:
<REPORT GOAL>
The report should address the following questions:
{report_organization}
</REPORT GOAL>


CRITICAL: Make sure the answer is written in the same language as the human messages!
For example, if the user's messages are in English, then MAKE SURE you write your response in English. If the user's messages are in Chinese, then MAKE SURE you write your entire response in Chinese.
This is critical. The user will only understand the answer if it is written in the same language as their input message.


Here is the report draft:
<REPORT DRAFT>
{report}
</REPORT DRAFT>

Produce the final report that:
1. Opens with the **Decision Header** (Ticker(s) · As of {today} · Signal · Conviction · Key levels · Next catalysts), then the body sections.
2. Is concise and scannable, with **markdown tables for quantitative data** and a **"Risks & Counter-thesis"** section.
3. Keeps every figure exactly as grounded in the draft — do not invent, infer, or alter numbers. Preserve any "insufficient data" notes.
4. Uses ## for section headings, no self-reference, no commentary, and NO source citations (added in post-processing).

End the report with this exact line, on its own, in italics:
*This report is AI-generated research for decision support only and is not personalized investment advice. Verify all figures against primary sources before acting.*

REMEMBER: write the final report in the SAME language as the human question.
"""
