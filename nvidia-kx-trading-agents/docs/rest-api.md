# API Documentation for AI-Q NVIDIA Research Assistant Blueprint

The AI Trader Agents uses APIs provided by the NVIDIA RAG blueprint and the AI Trader Agents backend. An [example notebook](/notebooks/test_rest_apis.ipynb) is also provided for testing the backend service.

## AI Trader Agents Service Endpoints 

1.  **Generate Summary (Stream)**
    *   **Method**: `POST`
    *   **Default Path**: `/generate_summary/stream`
    *   **Description**: Generates a stream of steps taken during report generation and concludes by sending a payload with the final report 
    *   **Request**: JSON payload including:
        *   `topic` (string)
        *   `report_organization` (string, a prompt containing the desired report structure and details) 
        *   `queries` (array of query objects from `generate_query`)
        *   `search_web` (boolean)
        *   `rag_collection` (string, name of the collection to use for RAG)
        *   `reflection_count` (integer, number of times the agent should revise the first draft with new queries and sections)
        *   `llm_name` (string, name of the LLM in the AI Trader Agents configuration file to use for report generation, typically "nemotron")
    *   **Response**: Server-Sent Events (SSE) stream. JSON objects within the stream can represent intermediate thinking steps (e.g., `{"intermediate_step": "..."}`) or the final report content (e.g., `{"final_report": "...", "citations": [...]}`).

2.  **Generate Query (Stream)**
    *   **Method**: `POST`
    *   **Default Path**: `/generate_query/stream`
    *   **Env Var**: `GENERATE_QUERY_STREAM_ENDPOINT`
    *   **Description**: Generates research queries based on a topic and report structure, streaming tokens.
    *   **Request**: JSON payload including:
        *   `topic` (string)
        *   `report_organization` (string, a prompt containing the desired report structure and details) 
        *   `num_queries` (integer)
        *   `llm_name` (string, name of the LLM in the AI Trader Agents configuration file to use for report generation, typically "nemotron")
    *   **Response**: Server-Sent Events (SSE) stream. JSON objects within the stream can represent intermediate thinking steps (e.g., `{"intermediate_step": "..."}`) or the final list of queries (e.g., `{"queries": [...]}`).

3.  **Artifact Q&A / Edit**
    *   **Method**: `POST`
    *   **Default Path**: `/artifact_qa`
    *   **Env Var**: `ARTIFACT_QA_ENDPOINT`
    *   **Description**: Performs question/answering about a given text artifact or allows editing the artifact based on instructions.
    *   **Request**: JSON payload including:
        *   `artifact` (string, the current text of the report or queries)
        *   `question` (string, user's query or instruction)
        *   `chat_history` (array of strings, previous conversation messages)
        *   `use_internet` (boolean)
        *   `rewrite_mode` (optional string, set to "entire" if editing the report queries or report draft, omit if Q&A only)
        *   `additional_context` (optional string, typically omitted)
        *   `rag_collection` (string, name of RAG collection to use for search)
    *   **Response**: JSON object with `assistant_reply` (string) and optionally `updated_artifact` (string or structured data, if `rewrite_mode` was active).

*   **Artifact Q&A (streaming)**
    *   **Method**: `POST`
    *   **Default Path**: `/artifact_qa/stream`
    *   **Description**: Same as `/artifact_qa` but streams the answer token-by-token (SSE). Each event is a serialized `ArtifactQAOutput`; intermediate events carry `delta: true` (the `assistant_reply` is a token delta), the final event carries `delta: false` with the complete cleaned reply (and the artifact). Rewrite mode emits a single event.

*   **Source Agents**
    *   **Method**: `GET`
    *   **Default Path**: `/source_agents`
    *   **Description**: Lists all 11 research source agents with availability state (`available` / `needs_key` / `unavailable`), used by the UI agent picker, plus a synthetic `web` (Tavily) fallback entry. Agents: `rag` (Documents), `kdb` (KDB-X time-series), `kdb_docs` (KDB-X documents), `kdb_pit` (KDB-X point-in-time), `onetick` (OneTick Cloud), `web_search`, `market_data`, `news_headlines`, `fundamentals`, `sec_filings`, `macro_economic`.

## SEC Filings Ingestion (NeMo Retriever / nv-ingest)

These endpoints ingest SEC filings into per-ticker RAG collections so the Documents (RAG)
agent can retrieve structured filing content (nv-ingest preserves tables). Requires
`RAG_INGEST_URL` and the `filings` extra (edgartools).

*   **Ingest filings**
    *   **Method**: `POST`
    *   **Default Path**: `/sec/ingest`
    *   **Request**: `{ "ticker": "NVDA", "forms": ["10-K","10-Q"], "count": 1 }`
    *   **Description**: Fetches the latest `count` filings per form via edgartools (HTML), uploads them through the RAG ingestor into collection `sec_<ticker>` (created at 2048-dim to match the embedder). Returns per-filing status + the ingestor response.
*   **List ingested collections**
    *   **Method**: `GET`
    *   **Default Path**: `/sec/collections`
    *   **Description**: Lists existing `sec_*` collections with entity counts.

## KDB-X Document agent settings

*   **Get / set the kdb_docs collection**
    *   **Method**: `GET` / `PUT`
    *   **Default Path**: `/settings/kdb-docs`
    *   **PUT Request**: `{ "collection": "smoke_cloud" }`  (null clears the selection)
    *   **Response**: `{ "collection": "smoke_cloud", "available_collections": ["smoke_cloud", "sec_docs"] }`
    *   **Description**: Selects which RAG-ingested KDB-X collection the `kdb_docs` agent searches. Persisted in Redis; the agent is available only when a collection is selected. See `docs/kdb-docs-agent.md`.

*   **Get / set the visible kdb tables**
    *   **Method**: `GET` / `PUT`
    *   **Default Path**: `/settings/kdb-tables`
    *   **PUT Request**: `{ "tables": ["trade", "quote"] }`  (empty list clears the selection)
    *   **Response**: `{ "selected_tables": ["trade", "quote"], "available_tables": ["daily", "trade", "quote"], "table_rows": {"trade": 62230, "quote": 124460} }`
    *   **Description**: Narrows which KDB-X tables the `kdb` (time-series) agent and KDB chat may see/query. Persisted in Redis; selection can only narrow within the configured allowlist (`KDB_VISIBLE_TABLES` / `KXTA_OWNED_TABLES`). Used by the inline table picker (with per-table row counts).

## KDB-X Chat & Data Loader

These FastAPI routes back the KDB-X chat panel and historical-data loader. They are
only useful when KDB-X is enabled (`KDB_ENABLED=true`); the loader additionally
requires `KDB_MCP_INTERNAL=true` and a direct `KDB_DB_HOST`.

*   **KDB natural-language chat** — `POST /kdb/chat`
    *   **Request**: `{ "message": "Show NVDA trades today", "session_id": "optional" }`
    *   **Description**: Translates the question to q/SQL, runs it over IPC on the licensed KDB-X, and streams (SSE) `thinking` / `query` / `result` events. The generated SQL passes an execution rail (length + statement guard).
*   **Database schema / status** — `GET /kdb/schema`, `GET /kdb/status`
    *   **Description**: Discovered AIRA-owned tables + columns/types; connectivity/health.
*   **Vector search** — `POST /kdb/vector_search`
    *   **Description**: Direct vector search against the KDB-X document table (the `kdb_docs` read path).
*   **Load historical data** — `POST /kdb/load-historical`, `POST /kdb/load-public`
    *   **Description**: Loads historical stock data into KDB-X with SSE progress (writes go direct to KDB-X over q-IPC, not the read-only MCP).
*   **Loader jobs** — `GET /kdb/jobs`, `GET /kdb/jobs/active`, `GET /kdb/jobs/{job_id}`, `POST /kdb/jobs/{job_id}/cancel`, `POST /kdb/jobs/{job_id}/retry`
    *   **Description**: List/inspect data-loading jobs and cancel or resume them (crash-recoverable from the last checkpoint).

## NVIDIA RAG Endpoints - RAG Server 

The NVIDIA RAG blueprint provides a rag server, typically running on port 8081. These endpoints are used by AI Trader Agents code to send queries to RAG, parsing the response and citation for use in report generation. See the NVIDIA RAG blueprint [API schema](https://github.com/KxSystems/nvidia-kx-samples/blob/main/KX-nvidia-rag-blueprint/docs/api_reference/openapi_schema_rag_server.json) for full details.

1.  **Generate**
    *   **Method**: `POST`
    *   **Default Path**: `/generate`
    *   **Request**: JSON payload including: 
        *   `messages` (OpenAI message, array of dictionaries, each dictionary contains a role and content attribute, where content is the RAG query)
        *   `use_knowledge_base` (boolean, always set to True)
        *   `enable_citations` (boolean, always set to True)
        *   `collection_name` (optional string, name of RAG collection for context)
    *   **Description**: Returns the answer to a user question along with citations.
    *   **Response**: JSON OpenAI chat completions response along with a citations element.


## NVIDIA RAG Endpoints - Ingestor Server

The NVIDIA RAG blueprint provides an ingestor service, typically running on port 8082. These endpoints are used by the demo frontend and the customizable frontend for creating collections, uploading files, and deleting files. See the NVIDIA RAG blueprint [API schema](https://github.com/KxSystems/nvidia-kx-samples/blob/main/KX-nvidia-rag-blueprint/docs/api_reference/openapi_schema_ingestor_server.json) for full details.

1.  **List Collections**
    *   **Method**: `GET`
    *   **Default Path**: `/collections`
    *   **Description**: Retrieves a list of all available data collections.
    *   **Response**: JSON array of collection objects (e.g., `[{"collection_name": "MyDocs", "id": "xyz"}, ...]`). Expected to be under a "collections" key in the response JSON.

2.  **Create Collection**
    *   **Method**: `POST`
    *   **Default Path**: `/collections`
    *   **Description**: Creates one or more data collections.
    *   **Request**: JSON payload with a list of collection names to create (e.g., `["NewCollectionName"]`).
    *   **Response**: JSON object confirming creation

3.  **List Files in Collection**
    *   **Method**: `GET`
    *   **Default Path**: `/documents`
    *   **Description**: Retrieves a list of all files (documents) within a specified collection.
    *   **Request**: Query parameter `collection_name` (e.g., `/documents?collection_name=MyDocs`).
    *   **Response**: JSON array of document objects (e.g., `[{"document_name": "file1.pdf", "id": "abc"}, ...]`). Expected to be under a "documents" key in the response JSON.

4.  **Upload Documents**
    *   **Method**: `POST`
    *   **Default Path**: `/v1/documents`
    *   **Description**: Uploads one or more documents to a specified collection. Supports blocking (synchronous) and non-blocking (asynchronous) modes.
    *   **Request**: `multipart/form-data` containing:
        *   One or more `documents` file parts.
        *   A `data` part (JSON string) with fields  `collection_name` (string), `blocking` (boolean), and `split_options` (object, e.g., `{"chunk_size": 512, "chunk_overlap": 150}`).
    *   **Response**:
        *   Non-blocking: JSON object with a `task_id` (e.g., `{"task_id": "task123"}`).
        *   Blocking: JSON object confirming success (e.g., `{"message": "Upload successful", "processed_files": [...]}`). 

5.  **Delete Document from Collection**
    *   **Method**: `DELETE`
    *   **Default Path**: `/documents`
    *   **Description**: Deletes a specified document from a collection.
    *   **Request**:
        *   Query parameter: `collection_name`.
        *   JSON payload: An array containing the `document_name` to be deleted (e.g., `["mydoc.txt"]`).
    *   **Response**: A success message or status code (e.g., 200 OK with a text body, or 204 No Content).

