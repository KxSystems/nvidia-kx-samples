# KDB-X Document Search agent (`kdb_docs`)

`kdb_docs` answers qualitative document questions (filings, risk factors, disclosures)
by running GPU vector search **directly inside the KDB-X engine** over a collection that
was ingested through the standard RAG document pipeline.

## How documents get in
Upload documents in the **Collections** tab (the RAG document UI). nv-ingest chunks and
embeds them and registers the collection in KDB-X (`.rag.collections`). There is no
separate KDB-X upload step.

## Enabling the agent
1. Open **Settings → KDB-X Document Search**.
2. Pick the collection the agent should search and click **Save**.
3. The `kdb_docs` agent becomes available in the agent picker. With no collection
   selected, it stays unavailable (so it never appears as a dead toggle).

`kdb_docs` and the `rag` agent read the **same** collection via two retrieval strategies:
`kdb_docs` does direct in-engine GPU vector search (cuVS/CAGRA); `rag` goes through the
full rag-server pipeline (reranking, table/chart preservation). They are not separate
knowledge bases.

## Required configuration
- `KDB_DB_HOST` (+ `KDB_DB_PORT`, default 5000) — direct kdb+ IPC to the KDB-X engine
  that hosts the RAG collections (the blueprint `kdbx` pod).
- The query embedder must match the collection's embedding model/dimension. The RAG
  blueprint embeds with `nvidia/llama-nemotron-embed-1b-v2` (2048-dim) on the NVIDIA
  cloud endpoint, so set:
  - `KDB_VECTOR_EMBED_MODEL=nvidia/llama-nemotron-embed-1b-v2`
  - `KDB_VECTOR_EMBED_URL=https://integrate.api.nvidia.com`
  - `NVIDIA_API_KEY=…`
  A mismatch (e.g. the 1024-dim default `nvidia/nv-embedqa-e5-v5`) will fail the search.

## Selecting / inspecting the collection (API)
- `GET /settings/kdb-docs` → `{ "collection": <name|null>, "available_collections": [...] }`
- `PUT /settings/kdb-docs` `{ "collection": "<name>" }` → persists the selection (Redis).

## Legacy SEC→KDB-X ingest
The old best-effort path that auto-wrote SEC filings into a separate `KDB_VECTOR_TABLE`
collection is **off by default** (it created a corpus that diverged from the RAG UI).
Set `KDB_DOCS_LEGACY_SEC_INGEST=true` to re-enable it.
