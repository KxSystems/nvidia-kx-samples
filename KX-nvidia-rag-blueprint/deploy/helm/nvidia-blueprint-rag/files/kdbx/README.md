# KDB-X server image for NVIDIA RAG Blueprint (KX fork)

## Prerequisites
- KX Portal account with KDB-X CE entitlement (https://portal.kx.com)
- Bearer token from the portal
- Base64-encoded KDB-X license file

## Build

Run from the repo root (the `-f` path is relative to that).
`--platform linux/amd64` is **required** on Apple Silicon — KDB-X CE ships
x86_64 binaries only, and an arm64 build will silently fail at runtime on
EKS x86 nodes.

```bash
export KDB_BEARER_TOKEN="..."
export KDB_B64_LICENSE="$(base64 -i kc.lic)"

docker build --platform linux/amd64 \
  --secret id=bearer_token,env=KDB_BEARER_TOKEN \
  --secret id=license_b64,env=KDB_B64_LICENSE \
  -t <your-registry>/kdbx-rag:1.0.0 \
  -f deploy/helm/nvidia-blueprint-rag/files/kdbx/Dockerfile.kdbx \
  deploy/helm/nvidia-blueprint-rag/files/kdbx/

docker push <your-registry>/kdbx-rag:1.0.0
```

## Smoke test the image

The entrypoint loads `kdbx-init.q` at q startup (mounted from the ConfigMap).
Once the process is ready, `.rag.ping[]` returns `` `pong ``.

```bash
# Mount kdbx-init.q and run:
docker run --rm -p 5000:5000 \
  -v $(pwd)/kdbx-init.q:/opt/kx/conf/kdbx-init.q \
  <your-registry>/kdbx-rag:1.0.0

# In a q client:
q )5000
# > .rag.ping[]            / `pong
```

## Startup-Load Provisioning

`kdbx-init.q` must be loaded by q **at process startup**:

```bash
q /opt/kx/conf/kdbx-init.q -p 5000
```

The helm chart does this automatically via `kdbx-entrypoint.sh`. For
customer-managed KDB-X, add this to your q process launch configuration.
The file ships in this directory (`deploy/helm/nvidia-blueprint-rag/files/kdbx/kdbx-init.q`).

The adapter performs a one-time readiness check on first connect and raises
`KdbxNotBootstrappedError` with setup instructions if `.rag.*` is not loaded.

## GPU CAGRA Support (Phase 2)

Set `KDBX_USE_CUVS=1` to enable GPU-accelerated CAGRA vector search via `kx.cuvs`.
The q-layer automatically builds CAGRA collections when cuVS is loaded.
See the main KDB-X documentation at `docs/change-vectordb-kdbx.md` for full setup.

The chart sets `KDBX_USE_CUVS=1` via `kdbx.useCuvs=true`; the entrypoint installs
the cuVS module + CUDA libs at pod startup (it is NOT baked into the image — KX ships
cuVS separately). Only `nvidia.com/gpu: 1` plus a GPU node are additionally required.
The KDB-X process loads `kdbx-init.q` (which loads `kx.cuvs` server-side) at q
startup — the adapter no longer pushes it over IPC on connect.

## Environment Variables

Key server-side variables (set on the kdbx pod / kdb+ process):

| Variable | Default | Description |
|----------|---------|-------------|
| `KDBX_LISTEN_PORT` | `5000` | kdb+ process listen port (use this, not KDBX_PORT) |
| `KDBX_USE_CUVS` | `0` | `1` = enable GPU CAGRA via `kx.cuvs` |
| `KDBX_METRIC` | `L2` | Distance metric: `L2` or `CS` (cosine) |
| `KDBX_HNSW_M` | `32` | HNSW M parameter |
| `KDBX_HNSW_EF_CONSTRUCTION` | `64` | HNSW efConstruction |
| `KDBX_HNSW_EF_SEARCH` | `64` | HNSW efSearch |
| `KDBX_CAGRA_GRAPH_DEGREE` | `32` | CAGRA graph degree |
| `KDBX_CAGRA_ITOPK_SIZE` | `128` | CAGRA internal top-k (must be >= search k) |
| `KDBX_CAGRA_GPUID` | `0` | GPU device index |
| `KDBX_CAGRA_SKIP_PERSISTED_READ` | `0` | Kill-switch: `1` = skip .cagra read, rebuild from vectors |

Client-side variables (set on rag-server and ingestor pods):

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_VECTORSTORE_URL` | `http://kdbx:5000` | kdb+ endpoint the adapter connects to (host:port parsed from this URL). This is the client connection var — `KDBX_HOST` is **not** read at runtime (it only gates an integration test). |
| `APP_VECTORSTORE_ENABLEGPUINDEX` | `False` | `True` = request CAGRA index creation |
| `APP_VECTORSTORE_ENABLEGPUSEARCH` | `False` | `True` = use GPU for search |
