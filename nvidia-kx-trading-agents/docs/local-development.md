# Local Development Guide

## Getting Started

To run locally, start by [installing the uv python package and project manager](https://docs.astral.sh/uv/getting-started/installation/). 

Next create a virtual environment using Python 3.12:

```bash
uv python install 3.12
uv venv --python 3.12 --python-preference managed
uv pip install -e ".[dev]"
```

Update the configuration file located at `configs/config.yml`, providing values for a RAG deployment and your reasoning and instruct LLMs. The configuration file includes comments on what values to update.

**Note**: Both NVIDIA Build and local deployments use the same model name format:
- **NVIDIA Build**: `nvidia/llama-3.3-nemotron-super-49b-v1.5` (with dots)  
- **Local Deployment**: `nvidia/llama-3.3-nemotron-super-49b-v1.5` (with dots)

The configuration files are set up for local deployments using the dot format.

Run the backend service:

```bash
# optionally export the Tavily search key
export TAVILY_API_KEY=your-tavily-api-key
# run the service
uv run nat serve --config_file configs/config.yml --host 0.0.0.0 --port 3838
```

You can now access the backend at `http://localhost:3838/docs`. 

### Test with the KXTA demo web application

To test your custom backend against the pre-built KXTA demo web application, you need to use Docker to run the nginx proxy and frontend.

1. Run the nginx proxy that sits between the frontend, backend, and RAG. Update the value `UPDATE-TO-YOUR-RAG-SERVER-IP` below:

```bash
docker run \
  -v $(pwd)/deploy/compose/nginx.conf.template:/etc/nginx/templates/nginx.conf.template \
  -e RAG_INGEST_URL=http://UPDATE-TO-YOUR-RAG-SERVER-IP:8082 \
  -e KXTA_BASE_URL=http://localhost:3838 \
  --network host \
  nginx:latest
```

> Tip: Local development requires the Docker network host. If you are using Docker for Desktop, ensure you have enabled the network host under Settings -> Network

2. Run the KXTA frontend 

```bash
docker run \
  -e INFERENCE_ORIGIN=http://localhost:3838 \
  nvcr.io/nvidia/blueprint/aira-frontend:v1.2.0
```

## Unit Tests

To run the developer unit tests, follow the instructions in `test_kxta/README.md`

## Developer Architecture

One of the main benefits of the AI Trading Agents is the ability to do human-in-the-loop intervention in the deep research process, and to do so at scale via a stateless REST interface. This capability is achieved by breaking the deep research process into 3 distinct steps:

1. `generate_queries` (**Plan**) - takes the user's desired report structure and asks the reasoning model (Nemotron 49B) to create relevant research queries. The planner is told which source agents are enabled/available and tags each query with a preferred source.
2. `generate_summary` (**Route → Reflect → Write**) - takes the research questions and desired report structure and performs deep research: each query is routed to the best-fit source agent(s), results are relevance-checked and rerouted on a miss, gaps are filled in reflection loops, and the findings are written into a citation-backed report (Llama 3.3 70B).
3. `artifact_qa` - takes either the draft queries or the draft report, along with user chat input, and provides for HITL updates to the artifacts or general Q&A about them 

Each step is served as a stand-alone stateless API endpoint using the NeMo Agent Toolkit. The frontend manages the user state, tracking the queries and generated artifact over time. 

See the [FAQ](/docs/FAQ.md) for more information on customization or developer options, and the [sequence diagrams](/docs/sequence-diagram.md) for the full runtime flow.

### Source-agent routing

Data sources are not hard-wired. A **source-agent registry**
(`kxta/src/kxta/source_agents/`) exposes 11 agents — `rag`, `kdb`,
`kdb_docs`, `kdb_pit`, `onetick`, `web_search`, `market_data`, `news_headlines`,
`fundamentals`, `sec_filings`, `macro_economic` — each gated by availability
(module present, API key set, service reachable, data loaded, or collection
selected). The UI agent picker reflects this state via `GET /source_agents`, and
data-bound selections persist via `GET/PUT /settings/kdb-docs` and
`/settings/kdb-tables`.

For each query, `process_single_query()` (in `search_utils.py`) resolves the
enabled agents, picks the best-fit source via `select_sources()` (planner tag →
keyword → semantic similarity using the embedding NIM), runs the chosen agent(s),
and scores relevance with `check_relevancy()` — a **NeMo Retriever reranker NIM**
when configured, otherwise an LLM judge. On a miss it reroutes to up to two
fallback agents and, finally, a web search. The agent activity tree in the
frontend (`AgentActivity.tsx`) shows each agent's live steps converging into
synthesis.

### Parallel Search

During the research phase, multiple research questions are searched in parallel,
and the agents chosen for a given query also run concurrently. Relevant on-premise
sources are preferred over generic web results (web search is a fallback only when
no enabled source returns a relevant answer). Running queries and agents in
parallel lets many data sources be consulted efficiently.

## Repository Layout & Module Responsibilities

Where the code lives and what each part is responsible for. The backend Python
package is `kxta` (under `kxta/src/kxta/`); the KX additions are
deliberately isolated in `source_agents/` plus thin hooks so upstream changes stay
mergeable.

```
aiq-research-assistant/
├── kxta/src/kxta/          # Backend package (kxta)
│   ├── register.py             # Entry wiring: registers NAT functions + mounts FastAPI routes
│   ├── nodes.py                # LangGraph nodes: generate_query → web_research → summarize → reflect → finalize
│   ├── search_utils.py         # process_single_query(): route → score → reroute → web fallback → merge
│   ├── schema.py / prompts.py  # Pydantic models / LLM prompt templates
│   ├── tools.py                # RAG + web search tool implementations
│   ├── report_gen_utils.py / artifact_utils.py   # Report writing + edit helpers
│   ├── reranker.py             # Relevancy gate via NeMo Retriever reranker NIM (else LLM judge)
│   ├── embeddings.py           # Embedding NIM: semantic routing + query dedup
│   ├── guardrails.py           # Input rail (LLM gate or NemoGuard content safety)
│   ├── kdb_tools_nat.py        # KDB-X MCP client + _visible_tables() allowlist (the kdb agent)
│   ├── kdb_vector.py           # KDB-X document vector search (the kdb_docs agent)
│   ├── kdb_direct_write.py     # Typed q-IPC writes + table row counts (the loader)
│   ├── kdb_docs_settings.py / kdb_tables_settings.py   # Redis-persisted picker selections
│   ├── functions/              # NAT-registered workflow functions (generate_query, generate_summary, artifact_qa)
│   ├── source_agents/          # ★ Pluggable agent registry (the KX extension surface)
│   │   ├── registry.py         #   SourceRegistry, enabled_sources(), per-agent is_available()/run()
│   │   ├── routing.py          #   select_sources() (planner tag → keyword → semantic) + fallback_sources()
│   │   ├── agent_base.py       #   Base class: requires_env / requires_modules availability gating
│   │   ├── <agent>.py          #   One module per agent: market_data, news_headlines, fundamentals,
│   │   │                       #     sec_filings, macro_economic, web_search, onetick, kdb_docs, kdb_pit
│   │   └── _vendor/            #   Borrowed tool implementations (config.py drives the summarization NIM)
│   ├── fastapi_extensions/routes/   # Extra REST routes mounted by register.py:
│   │   │                       #   source_agents, kdb_chat, kdb_data (loader/jobs),
│   │   │                       #   kdb_docs_settings, kdb_tables_settings, sec_ingest, collections, documents
│   └── eval/                   # Evaluation framework (generators + evaluators; NAT eval plugin)
├── kxta/test_kxta/             # Pytest suite — roughly one module per agent/feature
├── frontend/src/               # React/Vite demo app
│   ├── api/                    #   Typed REST/SSE clients (summary, queries, sourceAgents, kdbChat, kdbDocs, kdbTables, …)
│   ├── components/             #   sources/SourceSelector, report/AgentActivity, kdb/, settings/, collections/, qa/, queries/
│   ├── pages/                  #   Home, Research, KDB, Settings
│   └── store/                  #   Zustand workflow store (selected agents/collections/tables)
├── configs/                    # config.yml (local), hosted-config.yml (cloud), docker-config.yml, eval_config.yml, security_config.yml
├── deploy/                     # Dockerfile + compose/ + helm/ (kxta incl. nim-llm[-nemotron] subcharts; kdb-x-mcp-server)
├── data/                       # zip_to_collection.py demo-collection seeder
└── docs/                       # This documentation set
```

**Adding a source agent:** create `source_agents/<name>.py` with a class exposing
`name`, `label`, `description`, `is_available()`, `run()`, and (optionally)
`requires_env`/`requires_modules` + routing keywords; register it in
`registry.py`. Every call site routes through `process_single_query()` →
`select_sources()`, so no node changes are needed. Per-request data selection that
must persist (e.g. a collection or table set) follows the `kdb_docs_settings.py`
pattern (Redis + a `/settings/...` route) rather than threading fields through
`/generate_summary`.

## Seeding the RAG knowledge base

The frontend is designed to work with custom RAG collections and PDFs as well as two example collections:

- `Financial_Reports` - contains information from public earnings reports for Alphabet, Meta, and Amazon
- `Cystic_Fibrosis_Reports` - contains research publications of Cystic Fibrosis 

To seed these into your RAG database: 

```bash
uv python install 3.12
uv venv --python 3.12 --python-preference managed
uv run pip install -r data/requirements.txt
uv run python data/zip_to_collection.py
```

