# AI-Q NVIDIA Research Assistant

## Project Overview

AI-Q Research Assistant is an on-premise deep research assistant that generates detailed, publication-quality research reports. It combines AI-driven research planning, parallel document/web search, LLM-based writing, and reflection loops to produce comprehensive reports with citations.

**Key Capabilities:**
- Deep research report generation from on-premise data sources
- Human-in-the-loop research workflows (interactive report editing, Q&A)
- Retrieval-augmented generation (RAG) with web search fallback
- Multi-modal document analysis (text, tables, charts via NeMo Retriever)
- Factually grounded reports with proper source attribution
- **KDB-X Integration** - Real-time financial data queries via MCP (Model Context Protocol)
- **Natural language to SQL** - Ask financial questions in plain English
- **Hybrid Search** - Parallel KDB+ and RAG queries with intelligent result merging

## Tech Stack

- **Python 3.12+** with `uv` package manager
- **NVIDIA NAT (NeMo Agent Toolkit)** - Core framework for API services and observability
- **LangGraph** - State machine framework for AI workflows
- **LangChain** - LLM chains and agents
- **Pydantic v2** - Data validation
- **FastAPI** - REST API (via NAT)
- **Redis** - Session/caching backend
- **LiteLLM** - Multi-provider LLM abstraction

### LLM Models Used
- **Llama 3.3 Instruct 70B** - Report writing and Q&A
- **Llama 3.3 Nemotron Super 49B v1.5** - Reasoning model with thinking tokens for query planning and reflection

### External Integrations
- **NVIDIA RAG Blueprint** - Document retrieval with citations
- **Tavily Search API** - Web search fallback
- **OpenTelemetry** - Distributed tracing
- **KDB-X MCP Server** - Financial time-series data via Model Context Protocol
- **Yahoo Finance** - Historical stock data for demo data loading

## Directory Structure

```
aiq-research-assistant/
├── aira/                           # Main Python package
│   ├── src/aiq_aira/              # Source code
│   │   ├── functions/             # Main workflow endpoints
│   │   │   ├── generate_queries.py
│   │   │   ├── generate_summary.py
│   │   │   └── artifact_qa.py
│   │   ├── eval/                  # Evaluation framework
│   │   ├── fastapi_extensions/    # FastAPI middleware & routes
│   │   │   └── routes/
│   │   │       ├── kdb_chat.py    # KDB natural language chat
│   │   │       └── kdb_data.py    # KDB data loader routes
│   │   ├── nodes.py               # LangGraph workflow nodes
│   │   ├── schema.py              # Pydantic data models
│   │   ├── prompts.py             # LLM prompt templates
│   │   ├── tools.py               # RAG and web search tools
│   │   ├── kdb_tools_nat.py       # KDB MCP client (NAT 1.3.0+)
│   │   ├── artifact_utils.py      # Report editing utilities
│   │   ├── search_utils.py        # Query execution & relevancy
│   │   ├── report_gen_utils.py    # Report writing utilities
│   │   └── register.py            # NAT plugin registration
│   └── test_aira/                 # Unit tests
├── configs/                        # Configuration files
│   ├── config.yml                 # Main service config
│   ├── hosted-config.yml          # For hosted NIMs
│   ├── eval_config.yml            # Evaluation config
│   └── security_config.yml        # Prompt injection patterns
├── deploy/                         # Deployment configurations
│   ├── compose/                   # Docker Compose
│   │   ├── docker-compose.yaml           # Main compose file
│   │   ├── docker-compose-kx-local.yaml  # Full local KDB deployment
│   │   └── docker-compose-kx-reuse-nim.yaml  # Reuse existing NIMs
│   ├── helm/                      # Kubernetes Helm charts
│   │   ├── aiq-aira/              # Main application chart
│   │   └── kdb-x-mcp-server/      # KDB-X MCP server chart
│   └── Dockerfile
├── frontend/                       # React/Vite frontend
│   └── src/components/kdb/        # KDB UI components
│       ├── KDBChatPanel.tsx       # Natural language chat UI
│       └── KDBChatMessage.tsx     # Chat message component
├── data/                           # Data ingestion utilities
├── docs/                           # Documentation
├── notebooks/                      # Jupyter tutorials
└── pyproject.toml                 # Package config
```

## Architecture

The system exposes **three stateless REST API endpoints**, each handling a stage of research:

### Stage 1: Generate Queries (`/generate_query`)
- Takes research topic and desired report structure
- Uses Nemotron reasoning model with thinking tokens
- Generates structured research queries with rationales
- Streaming response for real-time progress

### Stage 2: Generate Summary (`/generate_summary`)
- Executes parallel query searches against RAG collection
- Uses LLM-as-judge for relevancy checking
- Falls back to Tavily web search if RAG results insufficient
- Writes report incrementally using Llama 3.3 Instruct
- Runs reflection loops to identify and fill gaps
- Formats final report with source citations

### Stage 3: Artifact Q&A (`/artifact_qa`)
- Answers questions about generated queries/reports
- Rewrites artifacts based on user instructions
- Can perform supplementary RAG/web search

## Key Files

| File | Purpose |
|------|---------|
| `aira/src/aiq_aira/nodes.py` | LangGraph workflow nodes and state management |
| `aira/src/aiq_aira/schema.py` | Pydantic models with input validation |
| `aira/src/aiq_aira/prompts.py` | All LLM prompt templates |
| `aira/src/aiq_aira/tools.py` | RAG and web search tool implementations |
| `aira/src/aiq_aira/kdb_tools_nat.py` | KDB MCP client using NAT 1.3.0+ mcp package |
| `aira/src/aiq_aira/fastapi_extensions/routes/kdb_chat.py` | Natural language to SQL chat endpoint |
| `aira/src/aiq_aira/fastapi_extensions/routes/kdb_data.py` | Historical data loader with progress streaming |
| `aira/src/aiq_aira/register.py` | NAT plugin registration |
| `configs/config.yml` | Main service configuration |
| `configs/security_config.yml` | Prompt injection detection patterns |

## Development Setup

```bash
# Install uv package manager
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create virtual environment
uv python install 3.12
uv venv --python 3.12 --python-preference managed
uv pip install -e ".[dev]"

# Configure LLM endpoints in configs/config.yml

# Run the service
export TAVILY_API_KEY=your-tavily-api-key  # Optional
uv run nat serve --config_file configs/config.yml --host 0.0.0.0 --port 3838

# Access API docs at http://localhost:3838/docs
```

## Testing

```bash
# Install test dependencies
uv sync

# Run all tests
uv run pytest test_aira/ -s

# Specific test suites
uv run pytest test_aira/test_security_prompts.py -s    # Security tests
uv run pytest test_aira/test_web_search.py -s          # Web search (mock RAG)
uv run pytest test_aira/test_artifact_qa.py -s         # Q&A functionality
uv run pytest test_aira/test_generate_query.py -s      # Query generation
uv run pytest test_aira/test_generate_summary.py -s    # Summary generation
uv run pytest test_aira/test_module_loads.py           # Docker image test
uv run pytest test_aira/test_configmap_matches_config.py -s  # Helm config validation
```

**Note:** Some tests require a running RAG server and properly configured `configs/config.yml`.

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `NVIDIA_API_KEY` | NVIDIA API access | Required for containers |
| `NGC_API_KEY` | NVIDIA NGC registry | Required for containers |
| `TAVILY_API_KEY` | Tavily web search | Optional |
| `RAG_SERVER_URL` | RAG service URL | `http://rag-server:8081/v1` |
| `RAG_INGEST_URL` | RAG ingestor URL | `http://ingestor-server:8082/v1` |
| `INSTRUCT_LLM_BASE_URL` | Instruct LLM endpoint | `http://aira-instruct-llm:8000/v1` |
| `NEMOTRON_LLM_BASE_URL` | Nemotron endpoint | `http://nim-llm-ms:8000/v1` |
| `AIRA_APPLY_GUARDRAIL` | Enable relevancy guardrails | `false` |
| `KDB_ENABLED` | Enable KDB-X data source | `false` |
| `KDB_USE_NAT_CLIENT` | Use NAT MCP client (recommended) | `true` |
| `KDB_MCP_ENDPOINT` | KDB-X MCP server URL | `https://kdbxmcp.kxailab.com/mcp` |
| `KDB_MCP_INTERNAL` | Set `true` only when using blueprint's MCP (enables data loader) | `false` |
| `KDB_TIMEOUT` | Query timeout in seconds | `30` |
| `REDIS_URL` | Redis for job tracking | `redis://localhost:6379` |

## Code Conventions

- **Formatting:** `yapf` (PEP8 style, 120 char line limit)
- **Import sorting:** `isort` with first-party = `aiq_aira`
- **Linting:** `flake8` with custom ignores (see pyproject.toml)
- **Type checking:** Pydantic v2 for runtime validation

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/generate_query/stream` | POST | Stream query generation |
| `/generate_summary/stream` | POST | Stream report generation |
| `/artifact_qa` | POST | Q&A and artifact editing |
| `/aiqhealth` | GET | Health check |
| `/default_collections` | GET | Demo collection metadata |
| `/kdb/chat/stream` | POST | KDB natural language chat (SSE) |
| `/kdb/data/load` | POST | Load historical stock data (SSE) |
| `/kdb/data/jobs` | GET | List data loading jobs |
| `/kdb/data/jobs/{job_id}` | GET | Get job status |
| `/kdb/data/jobs/{job_id}` | DELETE | Cancel running job |

## Docker Deployment

```bash
# Set environment variables
export NVIDIA_API_KEY=nvapi-xxx
export NGC_API_KEY=$NVIDIA_API_KEY
export TAVILY_API_KEY=your-tavily-key
export USERID=$(id -u)

# Deploy with Docker Compose (standard)
docker compose -f deploy/compose/docker-compose.yaml \
  --profile aira-instruct-llm --profile aira up -d

# Deploy with KDB-X integration (reusing existing NIMs)
docker compose -f deploy/compose/docker-compose-kx-reuse-nim.yaml up -d

# Deploy with KDB-X (full local, requires KDB credentials)
export KDB_BEARER_TOKEN=your-kx-portal-token
export KDB_LICENSE_B64=$(cat kc.lic | base64 | tr -d '\n')
docker compose -f deploy/compose/docker-compose-kx-local.yaml up -d
```

## Kubernetes Secrets

For Kubernetes deployments, sensitive credentials are stored in secrets:

| Secret Name | Key | Purpose |
|-------------|-----|---------|
| `ngc-api` | `NVIDIA_API_KEY` | LLM API authentication |
| `tavily-secret` | `TAVILY_API_KEY` | Web search API |
| `kdb-secret` | `KDB_API_KEY` | Authenticated KDB-X servers |
| `kdb-license-secret` | `KDB_LICENSE_B64` | PyKX license |

### Creating/Updating Secrets

```bash
# Create NVIDIA API secret
kubectl -n aiq create secret generic ngc-api \
  --from-literal=NVIDIA_API_KEY="nvapi-xxx" \
  --dry-run=client -o yaml | kubectl apply -f -

# Update existing secret
kubectl -n aiq patch secret ngc-api --type='json' -p='[
  {"op": "replace", "path": "/data/NVIDIA_API_KEY",
   "value": "'$(echo -n "nvapi-NEW-KEY" | base64)'"}
]'

# Restart deployment to pick up changes
kubectl -n aiq rollout restart deployment/aiq-kx-aira-backend
```

See `/docs/aiq-kx-deployment-guide.md#kubernetes-secrets-configuration` for detailed documentation.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Sign commits with `git commit -s -m "message"` (DCO required)
4. Submit a pull request

See `CONTRIBUTING.md` for full guidelines.

## Security

- Input validation via Pydantic with prompt injection filtering
- Security patterns defined in `configs/security_config.yml`
- Blocks: instruction overrides, SQL injection, XSS, code execution attempts
- Report security issues via `SECURITY.md`

## Useful Commands

```bash
# Format code
uv run yapf -ir aira/src/

# Sort imports
uv run isort aira/src/

# Seed demo RAG collections
uv run python data/zip_to_collection.py

# Build Docker image
docker build -f deploy/Dockerfile -t aira-backend .
```

## Documentation

- `/docs/local-development.md` - Development setup guide
- `/docs/FAQ.md` - Frequently asked questions
- `/docs/troubleshooting.md` - Common issues and solutions
- `/docs/evaluate.md` - Evaluation framework guide
- `/docs/rest-api.md` - API documentation
- `/docs/aiq-kx-deployment-guide.md` - KDB-X integration deployment guide
- `/docs/hybrid-search-enhancement-plan.md` - Hybrid search roadmap and implementation guide
- `/notebooks/get_started_nvidia_api.ipynb` - Quick start tutorial
