/ deploy/helm/nvidia-blueprint-rag/files/kdbx/kdbx-init.q
/ KDB-X RAG wrappers -- Phase 1 (HNSW via .ai.hnsw)
/ Loaded on container startup. Defines .rag.* functions invoked over IPC by KdbxVDB.
/ (Note: a line with just `/` would open a q block comment until matching `\`,
/  so leave at least one space after every leading `/` in this file.)
/ Conventions:
/   - Parameter `cname` is a symbol naming a collection. (Never `name` --
/     `.rag.collections` has a column called `name`, and a parameter of that
/     name would shadow column references inside qSQL `where` clauses.)
/   - One global table per collection (vectors + doc + ts), plus a sibling
/     `<cname>_meta` global for free-form metadata in tall form.
/   - HNSW graph object lives at `.rag.<cname>_idx`.  Vectors that built it
/     are the `vec` column of the collection table (kept separately per
/     kx.ai convention -- see ai-reference.md).
/   - Persistence: vector + meta tables (and the `_schema` slot) are `set`
/     to `DATA_DIR sv tableName`.  HNSW graphs are NOT persisted directly --
/     .rag.rehydrate (called once at startup) walks DATA_DIR and rebuilds
/     each graph from the persisted vector column via .ai.hnsw.put.  Phase 2
/     will persist the graph itself (.ai.hnsw.write) to avoid the cold-start
/     rebuild cost on large corpora.

/ ====== Module loading ======
/ NB: kx.ai's init.q references its siblings with relative `use\`.hnsw etc., and
/ the loader resolves those against the q process CWD -- not against the module's
/ own dir.  So we cd into the module dir for the load, then cd back.  Same for
/ kx.cuvs when KDBX_USE_CUVS=1.
.rag.loadMod:{[modSym; subdir]
  saved:first system"pwd";
  system"cd ",getenv[`QHOME],subdir;
  / Restore CWD even when `use` signals (TODO 1.9): the cuVS call-site traps
  / the error, and without this the process would stay chdir'd into the
  / module dir for the rest of its life.
  r:@[use; modSym; {[saved; e] system"cd ",saved; 'e}[saved;]];
  system"cd ",saved;
  r
 };

.ai:.rag.loadMod[`kx.ai; "/mod/kx/ai"];
-1 "[kdbx-init] kx.ai loaded";

/ SQL interface (.s) for external SQL clients -- the KDB-X MCP server's
/ startup check requires .s.init and crash-loops without it (found live:
/ aira's kdb-mcp integration). Trapped: a missing module degrades to a log
/ line and never blocks init.
@[{.rag.loadMod[`kx.sql; "/mod/kx/sql"]; .s.init[]; -1 "[kdbx-init] kx.sql loaded (.s.init OK)";};
  (::);
  {[e] -1 "[kdbx-init] kx.sql NOT loaded (",e,") -- SQL interface unavailable"}];

/ Phase 2 hook: load cuVS only if explicitly requested via env.  The load is
/ trapped so a missing GPU/driver/module degrades to HNSW instead of crashing
/ the whole init.  .rag.cuvs.enabled is the single readiness flag the rest of
/ the file branches on (note: `key `.` lists only root *variables*, not child
/ namespaces, so a `cuvs in key `.` test would be a false negative -- use the
/ load outcome directly).
$[getenv[`KDBX_USE_CUVS]~enlist"1";
  @[{.cuvs:.rag.loadMod[`kx.cuvs; "/mod/kx/cuvs"]; .rag.cuvs.enabled:1b;
     -1 "[kdbx-init] kx.cuvs loaded"};
    ::;
    {[e] .rag.cuvs.enabled:0b; -1 "[kdbx-init] kx.cuvs load FAILED (degrading to hnsw): ",e}];
  [.rag.cuvs.enabled:0b; -1 "[kdbx-init] kx.cuvs NOT loaded (KDBX_USE_CUVS!=1)"]];
-1 "[kdbx-init] cuvs.enabled = ",string .rag.cuvs.enabled;

/ ====== Data directory ======
/ getenv returns "" when unset (not a null) so `^` (fill) is the wrong default
/ operator here -- its length-matching rules would error on a "" left arg.
/ Use $[] explicitly.
DATA_DIR:hsym `$$[0<count v:getenv[`KDBX_DATA_DIR]; v; "/opt/kx/data"];
-1 "[kdbx-init] data dir: ",string DATA_DIR;

/ ====== Catalogue ======
/ name      symbol  the collection identifier
/ dim       long    embedding dimensionality
/ metaSchema list   optional declared schema for metadata (free-form for now)
/ indexFP   symbol  name of the global holding the HNSW graph (`.rag.<n>_idx`)
/ indexType symbol  one of `hnsw (Phase 1) or `cagra (Phase 2)
/ metric    symbol  the distance metric this collection was BUILT with (L2/CS/IP).
/           Stamped at create time and persisted via a `<n>_metric` sidecar, so
/           rebuild/search/rehydrate use the collection's own metric -- never the
/           current pod global. A pod whose KDBX_METRIC default later flips would
/           otherwise silently rebuild with the wrong metric and corrupt retrieval
/           (WS-METRIC; latent in Phase 1 too).
.rag.collections:([name:`symbol$()]
  dim       :`long$();
  metaSchema:();
  indexFP   :`symbol$();
  indexType :`symbol$();
  metric    :`symbol$());

/ HNSW + index params.  Defaults preserve prior behavior; override per-pod via
/ env (no image rebuild needed).  efConstruction (build) and efSearch (query)
/ are SEPARATE knobs -- query-time ef can be raised for higher recall without
/ rebuilding the graph.
.rag.envInt:{[name; dflt] $[0<count v:getenv name; "J"$v; dflt]};
.rag.hnsw.M              :.rag.envInt[`KDBX_HNSW_M; 32];
.rag.hnsw.ml             :1 % log .rag.hnsw.M;
.rag.hnsw.efConstruction :.rag.envInt[`KDBX_HNSW_EF_CONSTRUCTION; 64];
.rag.hnsw.efSearch       :.rag.envInt[`KDBX_HNSW_EF_SEARCH; 64];
/ Distance metric for ALL .ai.hnsw calls.  Default `L2 (matches the kdbai
/ default path).  Set KDBX_METRIC=CS for cosine (e.g. normalized embeddings).
/ build and search MUST agree on the metric -- this single global guarantees it.
.rag.hnsw.metric         :$[0<count v:getenv `KDBX_METRIC; `$v; `L2];

/ Shared metric: both backends read .rag.metric so build and search can never
/ disagree (the cuVS reference flags metric mismatch as undefined behavior).
/ .rag.hnsw.metric stays the env source; .rag.metric is the canonical alias.
.rag.metric:.rag.hnsw.metric;

/ ====== CAGRA (cuVS GPU) params -- only meaningful when .rag.cuvs.enabled ======
/ Env-overridable, same pattern as the HNSW knobs. Confirmed against cuVS 25.10
/ on g7e (RTX PRO 6000 Blackwell): metric L2/CS/IP; search returns
/ (distances; 0-based positions); itopk_size must be >= k (clamped at search).
.rag.cagra.graphDegree             :.rag.envInt[`KDBX_CAGRA_GRAPH_DEGREE; 32];
.rag.cagra.intermediateGraphDegree :.rag.envInt[`KDBX_CAGRA_INTERMEDIATE_GRAPH_DEGREE; 32];
.rag.cagra.itopkSize               :.rag.envInt[`KDBX_CAGRA_ITOPK_SIZE; 128];
.rag.cagra.nnDescentNiter          :.rag.envInt[`KDBX_CAGRA_NN_DESCENT_NITER; 20];
.rag.cagra.maxIterations           :.rag.envInt[`KDBX_CAGRA_MAX_ITERATIONS; 0];
.rag.cagra.minIterations           :.rag.envInt[`KDBX_CAGRA_MIN_ITERATIONS; 0];
.rag.cagra.buildAlgo               :$[0<count v:getenv `KDBX_CAGRA_BUILD_ALGO; `$v; `nn_descent];
.rag.cagra.gpuid                   :.rag.envInt[`KDBX_CAGRA_GPUID; 0];
/ cuVS needs >= intermediate_graph_degree + 1 rows before a graph can build.
.rag.cagra.minRows                 :1 + .rag.cagra.intermediateGraphDegree;

/ ====== WS-SAFETY: cuVS persistence integrity + crashloop guards ======
/ A persisted .cagra blob is opaque GPU state -- a fatal read (e.g. a blob built
/ on a different GPU arch / cuVS version, or one left half-written by a crashed
/ build) can hard-fault q, which q cannot trap, so the pod would crashloop on
/ every boot replaying the same fatal read.  Three guards (rehydrate consults all
/ three before trusting a .cagra; any one => skip the read and rebuild from the
/ intact vector table, which is always written before the index):
/   1. kill-switch  KDBX_CAGRA_SKIP_PERSISTED_READ=1 -> never read, always rebuild.
/   2. env stamp    a <cname>_cagrastamp sidecar recording the build environment
/      (GPU name/compute-cap/driver + optional KDBX_CUVS_STAMP); a mismatch on
/      boot means the blob is from an incompatible arch/version -> rebuild.
/   3. build marker a <cname>_cagrabuilding sidecar written before a build/extend
/      and cleared after persist; if it survives to the next boot the prior build
/      crashed mid-flight -> the blob may be corrupt -> rebuild.
.rag.cagra.skipPersistedRead:getenv[`KDBX_CAGRA_SKIP_PERSISTED_READ]~enlist"1";

/ ====== .rag.ping[]  ->  `pong ======
/ Liveness probe -- used by healthcheck.q and integration smoke tests.
.rag.ping:{`pong};

/ ====== Helpers ======
/ Coerce a string-or-symbol arg into a symbol -- pykx in unlicensed/IPC mode
/ can't construct local q symbol values, so the Python adapter sends
/ collection names as plain strings.  Wrappers run cname through this so
/ q-side code is uniform.
.rag.toSym:{$[10h=type x; `$x; x]};

/ Build the symbol-form of a derived global name, e.g.
/   .rag.fp[`t1; "_meta"]   -> `t1_meta
/   .rag.fp[`t1; "_idx"]    -> `t1_idx
/   .rag.fp[`t1; "_schema"] -> `t1_schema
/ Replaces the repeated `$string[cname],"<suffix>" pattern that appeared in
/ six places.
.rag.fp:{[cname; suffix] `$string[cname],suffix};

/ Apply the grouped `g# attribute to a meta table's id column so the per-id
/ lookups in .rag.search / .rag.deleteDocumentsByMeta / .rag.getDocumentsWithMeta
/ are hash lookups instead of full linear scans (schema-1).  Idempotent and
/ cheap; re-applied after every meta mutation and on rehydrate because a
/ functional delete or a reload can drop the attribute.  `g# (not `u#) because
/ id legitimately repeats -- one meta row per (id, mkey) pair.
.rag.applyMetaAttr:{[metaName]
  if[metaName in tables `.; metaName set update `g#id from value metaName];
 };

/ Crash-safe persist (q-TODO 1.1c).  q's `set` truncates-then-writes in place,
/ so a crash mid-write leaves a torn file that `get` can no longer read.  Write
/ to a sibling .tmp and rename into place -- rename(2) is atomic on the same
/ filesystem, so a reader (rehydrate) only ever sees the old or the new
/ complete file.  ".tmp" is a reserved suffix: excluded from rehydrate's
/ collection scan and rejected by createCollection's name guard.
.rag.atomicSet:{[fp; v]
  tmp:`$(string fp),".tmp";
  tmp set v;
  system "mv ",(1_string tmp)," ",1_string fp;
 };

/ ====== Backend dispatch helpers (Phase 2: `hnsw | `cagra) ======
/ The per-collection backend is the catalogue indexType column.  Both backends
/ store their index object in the same type-agnostic `.rag.<cname>_idx` slot
/ (HNSW: a kx.ai graph; CAGRA: a cuVS foreign).  Search for BOTH returns
/ (distances; 0-based positions) into the collection table's row order, so the
/ downstream id/doc/meta join in .rag.search is identical regardless of backend.
.rag.idxType:{[cname] first exec indexType from .rag.collections where name=.rag.toSym cname};

/ The metric a collection was BUILT with (WS-METRIC).  Build, rebuild, search and
/ rehydrate all consult THIS, not the .rag.metric pod global, so a collection
/ keeps its metric even if the pod's KDBX_METRIC default later changes.  Falls
/ back to the current global for a legacy collection whose row predates the
/ column / whose `_metric` sidecar is absent (null symbol => use the global).
.rag.metricOf:{[cname]
  m:first exec metric from .rag.collections where name=.rag.toSym cname;
  $[null m; .rag.metric; m]};

/ CAGRA build + search param dicts.  initParams takes the per-collection metric
/ (search params don't -- CAGRA bakes the metric into the index at build time).
.rag.cagra.initParams:{[metric]
  `metric`intermediate_graph_degree`graph_degree`build_algo`nn_descent_niter`gpuid!
   (metric; .rag.cagra.intermediateGraphDegree; .rag.cagra.graphDegree;
    .rag.cagra.buildAlgo; .rag.cagra.nnDescentNiter; .rag.cagra.gpuid)};
/ itopk_size MUST be >= k (cuVS raises 'value otherwise) -- clamp here.
.rag.cagra.searchParams:{[k]
  `itopk_size`max_iterations`min_iterations!
   ((.rag.cagra.itopkSize) | k; .rag.cagra.maxIterations; .rag.cagra.minIterations)};

/ Resolve the backend for a NEW collection: `cagra only when cuVS is loaded
/ AND the caller asked for it (or the pod default is cagra); else `hnsw.
.rag.resolveIndexType:{[requested]
  req:$[(::)~requested; `; .rag.toSym requested];
  dflt:$[.rag.cuvs.enabled and getenv[`KDBX_INDEX_TYPE]~"cagra"; `cagra; `hnsw];
  want:$[req in `hnsw`cagra; req; dflt];
  $[(want=`cagra) and not .rag.cuvs.enabled;
    [-1 "[kdbx] cagra requested but cuVS unavailable -- downgrading to hnsw"; `hnsw];
    want]};

/ Resolve a per-collection metric REQUEST (review-2 #3: the adapter's metric
/ was previously dropped on the floor and every collection silently used the
/ pod global).  `L2`CS`IP accepted as-is; anything else ((::), "", unknown)
/ falls back to the pod global (.rag.metric, from KDBX_METRIC).  The chosen
/ metric is stamped per-collection (WS-METRIC), so it sticks across restarts.
.rag.resolveMetric:{[requested]
  r:$[(::)~requested; `; .rag.toSym requested];
  $[r in `L2`CS`IP; r; .rag.metric]};

/ ====== CAGRA index ops (reached only when indexType=`cagra) ======
/ The cuVS index is a MUTABLE foreign in the .rag.<cname>_idx slot.  CAGRA needs
/ >= minRows to build; below that the slot stays `() and search falls back to an
/ exact scan.  cuVS write/read persist the index (<base>.cagra + <base>.kdb) --
/ base path has no leading colon, so 1_ string the hsym.
.rag.cagra.basePath:{[cname] 1_ string .Q.dd[DATA_DIR; cname]};

/ --- WS-SAFETY sidecars (see the guards block above) ---
.rag.cagra.stampSidecar :{[cname] .rag.fp[cname; "_cagrastamp"]};
.rag.cagra.markerSidecar:{[cname] .rag.fp[cname; "_cagrabuilding"]};
/ Build-environment fingerprint. nvidia-smi is best-effort: on any failure the
/ stamp is "" which deliberately fails the equality check on rehydrate (=> the
/ safe rebuild path).  KDBX_CUVS_STAMP lets the operator pin a cuVS/CUDA version
/ tag too (the entrypoint knows the module version); arch+driver alone already
/ catch the common PVC-reattach-to-a-different-GPU case.
.rag.cagra.envStamp:{[]
  gpu:@[{first system "nvidia-smi --query-gpu=name,compute_cap,driver_version --format=csv,noheader -i ",string .rag.cagra.gpuid};
        ::; {[e] ""}];
  gpu,"|",getenv `KDBX_CUVS_STAMP};
.rag.cagra.stampMatches:{[cname]
  disk:@[get; .Q.dd[DATA_DIR; .rag.cagra.stampSidecar cname]; {""}];
  env:.rag.cagra.envStamp[];
  / q-TODO 1.4: an empty GPU segment means nvidia-smi failed on that side.  A
  / SYMMETRIC failure (nvidia-smi unavailable at build AND at rehydrate) would
  / otherwise compare equal and bypass the safe-rebuild path -- exactly the
  / arch-mismatch crashloop this stamp exists to prevent.  Empty GPU segment on
  / either side => mismatch.
  / (),x promotes a char ATOM to a 1-char vector -- `vs` signals 'type on an
  / atom right-arg, and a legacy/hand-written sidecar can hold an atom.
  $[any {0=count first "|" vs (),x} each (disk; env); 0b; disk~env]};
.rag.cagra.markBuildStart:{[cname] (.Q.dd[DATA_DIR; .rag.cagra.markerSidecar cname]) set 1b; };
.rag.cagra.markBuildDone :{[cname] @[hdel; .Q.dd[DATA_DIR; .rag.cagra.markerSidecar cname]; {[e]::}]; };
.rag.cagra.markerExists  :{[cname] (.rag.cagra.markerSidecar cname) in key DATA_DIR};

/ Rehydrate decision: "" => trust the persisted blob and .read it; a non-empty
/ string => skip the (possibly fatal) read and rebuild from the vector table.
/ Pure + standalone so it's unit-testable without a GPU (set the env / drop a
/ marker / write a mismatched stamp, then assert the reason).
.rag.cagra.skipReadReason:{[cname]
  $[.rag.cagra.skipPersistedRead;     "kill-switch KDBX_CAGRA_SKIP_PERSISTED_READ";
    .rag.cagra.markerExists cname;    "stale build marker (prior build crashed)";
    not .rag.cagra.stampMatches cname; "build-env stamp mismatch (arch/version changed)";
    ""]};

/ persist writes the index AND refreshes the env stamp next to it (so the stamp
/ always describes the blob currently on disk).  When there is NO index --
/ obj~() because the collection shrank below minRows (delete-rebuild) -- any
/ previously persisted blob is now misaligned with the table's row order, and
/ reading it back on a later rehydrate would return silently wrong documents
/ (q-TODO 1.2): delete the stale .cagra/.kdb and the stamp sidecar instead.
.rag.cagra.persist:{[cname; obj]
  $[()~obj;
    [{[p] @[hdel; hsym `$p; {[e]::}]} each .rag.cagra.basePath[cname],/:(".cagra"; ".kdb");
     @[hdel; .Q.dd[DATA_DIR; .rag.cagra.stampSidecar cname]; {[e]::}]];
    [.cuvs.cagra.write[obj; .rag.cagra.basePath cname];
     .rag.atomicSet[.Q.dd[DATA_DIR; .rag.cagra.stampSidecar cname]; .rag.cagra.envStamp[]]]]; };
/ Build a fresh index from ALL persisted vectors (used on first build / delete-
/ rebuild / rehydrate). Returns the index object (or `() when too few rows).
.rag.cagra.rebuild:{[cname]
  embsR:"e"$exec vec from value cname;
  / Mark the build BEFORE touching the GPU so a crash mid-build/persist leaves a
  / marker that forces a rebuild (not a corrupt-blob read) on the next boot.
  / Sub-minRows: no GPU op, so no marker (markBuildDone below is a no-op then).
  obj:$[(count embsR)<.rag.cagra.minRows; ();
    [.rag.cagra.markBuildStart cname;
     i:.cuvs.cagra.init .rag.cagra.initParams[.rag.metricOf cname]; .cuvs.cagra.insert[i; embsR]; i]];
  .rag[.rag.fp[cname; "_idx"]]:obj;
  .rag.cagra.persist[cname; obj];
  .rag.cagra.markBuildDone cname;
  obj};
/ Incremental insert: extend an existing index in place, else build from scratch.
.rag.cagra.insertVecs:{[cname; newVecsR]
  idxFP:.rag.fp[cname; "_idx"]; cur:.rag idxFP;
  $[()~cur;
    .rag.cagra.rebuild cname;                  / rebuild brackets its own marker
    [.rag.cagra.markBuildStart cname;
     .cuvs.cagra.insert[cur; newVecsR]; .rag.cagra.persist[cname; cur];
     .rag.cagra.markBuildDone cname]];
  };
/ Exact L2 top-k fallback for the (rare) sub-minRows window before a CAGRA graph
/ exists. Returns (distances; positions) -- same shape as the ANN backends.
/ allowPos = () for unfiltered, else the allowed row positions to restrict to.
.rag.cagra.exactScan:{[embsR; qv; k; allowPos]
  pos:$[0=count allowPos; til count embsR; allowPos];
  d:{sqrt sum x*x}each embsR[pos] -\: "e"$qv;
  ix:(k&count pos) sublist iasc d;
  (d ix; `long$pos ix)};

/ ====== WS-SAFETY: GPU readiness canary ======
/ A cuVS GPU context can fault (e.g. "illegal memory access") and stay wedged
/ while q's main thread is otherwise alive -- so .rag.ping would still say pong
/ on the LIVENESS probe (good: we don't want a PVC-churning liveness kill), but
/ the GPU is dead. The canary goes on the READINESS probe: it searches a tiny
/ throwaway CAGRA index built once at startup; if the GPU is wedged the search
/ throws and the pod is pulled from service without being killed.
/ CPU pods (cuVS not loaded) have nothing to check -> always ready.
/ buildCanary is BEST-EFFORT. Building a small *synthetic* CAGRA index can flakily
/ fail with 'rank / illegal-memory-access on some GPUs (observed repeatedly on A10G /
/ Ampere with cuVS 25.10) even when the GPU is perfectly healthy -- this is the
/ documented cuVS "very small / degenerate batches" edge, and it is NON-deterministic
/ (the same build succeeds on a fresh context and real >=minRows collection builds work
/ fine on the very same pod). We therefore (a) build LARGER than ~minRows to reduce the
/ degenerate probability, and (b) treat a build failure as INCONCLUSIVE, not as "GPU
/ wedged" -- a flaky self-test must never pull a healthy pod from service. Real
/ collection ops are the source of truth.
.rag.cuvs.canaryDim:8;
.rag.cuvs.buildCanary:{[]
  if[not .rag.cuvs.enabled; :()];
  n:256 | 8 * .rag.cagra.intermediateGraphDegree; d:.rag.cuvs.canaryDim;
  v:"e"$(n;d)#(n*d)?1.0;
  .rag.cuvs.canaryIdx:@[
    {[v] i:.cuvs.cagra.init .rag.cagra.initParams[`L2]; .cuvs.cagra.insert[i; v]; i}[v];
    ::;
    {[e] -1 "[kdbx] cuVS canary build INCONCLUSIVE (flaky synthetic build, GPU likely fine; real builds unaffected): ",e; ()}];
 };
.rag.cuvs.canary:{[]
  if[not .rag.cuvs.enabled; :1b];                 / CPU pod: nothing to canary
  / No canary index (build was inconclusive) => report READY, NOT wedged: a flaky
  / synthetic build is not evidence of a dead GPU, and real ops would surface a true
  / fault. Only a SEARCH that throws on a successfully-built canary signals a wedge.
  if[()~.rag.cuvs.canaryIdx; :1b];
  @[{.cuvs.cagra.search[.rag.cuvs.canaryIdx; "e"$.rag.cuvs.canaryDim#0.5; 1; .rag.cagra.searchParams 1]; 1b};
    ::;
    {[e] -1 "[kdbx] cuVS GPU canary search failed (GPU may be wedged): ",e; 0b}]};

/ ====== .rag.collectionExists[cname]  ->  bool ======
/ Predicate used by the Python adapter's check_collection_exists.
.rag.collectionExists:{[cname] (.rag.toSym cname) in exec name from .rag.collections};

/ ====== .rag.createCollection[cname; dim; metaSchema; reqIndexType; reqMetric]  ->  chosen indexType ======
/ Idempotent: a second create with the same dim is a no-op (returns the
/ existing indexType).  Conflicting dim raises a signal.
/ reqIndexType: `hnsw | `cagra | "" | (::) — a PREFERENCE; resolved against
/ cuVS availability via .rag.resolveIndexType (cagra downgrades to hnsw when
/ cuVS isn't loaded).  Returns the CHOSEN type so the Python adapter can
/ surface what the server actually picked.
/ Side effects (new collection): creates two global tables (`<cname>`, `<cname>_meta`),
/ leaves the `.rag.<cname>_idx` slot empty (() until first insert), persists the
/ tables + an `<cname>_idxtype` sidecar (the catalogue isn't persisted, so
/ rehydrate reads the sidecar to restore the backend choice).
.rag.createCollection:{[cname; dim; metaSchema; reqIndexType; reqMetric]
  cname:.rag.toSym cname;
  / Reserve sidecar suffixes/extensions so a user collection name can never
  / collide with our persisted siblings (_meta/_schema/_idxtype, .cagra/.kdb)
  / and get dropped or misread on rehydrate (q-6).  Reject up front.
  if[any (string cname) like/: ("*_meta"; "*_schema"; "*_idxtype"; "*_metric"; "*_cagrastamp"; "*_cagrabuilding"; "*.cagra"; "*.kdb"; "*.tmp");
    '`createCollection_reserved_suffix];
  it:.rag.resolveIndexType reqIndexType;
  if[cname in exec name from .rag.collections;
    if[dim<>first exec dim from .rag.collections where name=cname;
      '`createCollection_dim_mismatch];
    :.rag.idxType cname];

  / Empty typed vector + meta tables.  (column names mkey/mval not key/value --
  / the latter are q built-ins and 'assign inside ([] ...) literals.)
  cname set ([] id:`long$(); vec:(); doc:(); ts:`timestamp$());
  metaName:.rag.fp[cname; "_meta"];
  metaName set ([] id:`long$(); mkey:`symbol$(); mval:());

  / The index slot starts empty (`()`) for BOTH backends -- there are no
  / vectors yet, and .ai.hnsw.put / .cuvs.cagra.init both need rows.  The first
  / .rag.insert builds the right index per indexType.
  idxFP:.rag.fp[cname; "_idx"];
  / Stamp THIS collection's metric (caller request resolved against the
  / supported set, falling back to the pod global) and persist it alongside
  / the _idxtype sidecar, so a later rebuild/rehydrate uses this metric even
  / if the pod's KDBX_METRIC default changes (WS-METRIC).
  m:.rag.resolveMetric reqMetric;
  `.rag.collections upsert (cname; dim; metaSchema; idxFP; it; m);
  .rag.atomicSet[.Q.dd[DATA_DIR; cname]; value cname];
  .rag.atomicSet[.Q.dd[DATA_DIR; metaName]; value metaName];
  .rag.atomicSet[.Q.dd[DATA_DIR; .rag.fp[cname; "_idxtype"]]; it];
  .rag.atomicSet[.Q.dd[DATA_DIR; .rag.fp[cname; "_metric"]]; m];
  .rag[idxFP]:();
  it
 };

/ ====== .rag.listCollections[]  ->  dict<symbol; long> ======
/ Returns name -> row-count mapping for every registered collection.
.rag.listCollections:{
  names:exec name from .rag.collections;
  names!{count value x} each names
 };

/ ====== .rag.deleteCollection[cname]  ->  bool ======
/ Returns 1b on success, 0b if the collection does not exist.  Drops the
/ catalogue row, both tables, the HNSW graph slot, AND the on-disk files for
/ this collection.  Without the on-disk cleanup, .rag.rehydrate[] would
/ re-register the collection on every pod restart, silently undoing every
/ user-facing delete.
.rag.deleteCollection:{[cname]
  cname:.rag.toSym cname;
  if[not cname in exec name from .rag.collections; :0b];

  / Drop catalogue row.
  ![`.rag.collections; enlist(=;`name;enlist cname); 0b; `symbol$()];
  / Drop the two globals via functional delete (note: 4th arg is the *list
  / of names* to remove from the namespace, evaluated from the cname value).
  ![`.; (); 0b; enlist cname];
  ![`.; (); 0b; enlist .rag.fp[cname; "_meta"]];
  / Clear the .rag.<n>_idx slot (q has no functional delete inside a custom
  / namespace; assigning `()` is the idiomatic clear).
  .rag[.rag.fp[cname; "_idx"]]:();
  / Unlink persisted files: the table, its meta sibling, and the schema slot.
  / hdel raises if the path doesn't exist, so trap each call; the schema file
  / in particular is optional for legacy collections written before we added
  / metadata support.  We log non-noexist errors but don't fail the delete.
  paths:.Q.dd[DATA_DIR;] each (cname; .rag.fp[cname; "_meta"]; .rag.fp[cname; "_schema"]; .rag.fp[cname; "_idxtype"]; .rag.fp[cname; "_metric"]; .rag.fp[cname; "_cagrastamp"]; .rag.fp[cname; "_cagrabuilding"]);
  {[fp] @[hdel; fp; {[fp;e] -1 "[kdbx] hdel ",(string fp),": ",e}[fp]]} each paths;
  / cuVS index sidecars (cagra collections only; hdel traps absent files, so
  / this is a harmless no-op for hnsw collections).
  {[p] @[hdel; hsym `$p; {[e]::}]} each .rag.cagra.basePath[cname],/:(".cagra"; ".kdb");
  1b
 };

/ ====== .rag.deleteDocumentsByMeta[cname; srcBlobs] -> long ======
/ Delete every row whose meta `source` mval equals one of the given strings.
/ `srcBlobs` is a list of the JSON-encoded source blobs to remove (the Python
/ adapter resolves user-facing filenames -> blobs before calling us, since the
/ source dict carries source_name + source_id + source_type and we don't
/ JSON-parse on the q side).
/ Returns the number of rows deleted.  Persists both tables and rebuilds the
/ HNSW graph from the remaining vectors so search stays correct.
.rag.deleteDocumentsByMeta:{[cname; srcBlobs]
  cname:.rag.toSym cname;
  if[not cname in exec name from .rag.collections; :0];
  metaName:.rag.fp[cname; "_meta"];
  if[not metaName in tables `.; :0];

  / Find the row ids to delete.  Note: the meta column is `mval` (a string),
  / so srcBlobs must arrive as a list of strings -- q `in` matches by value.
  rids:exec id from value[metaName] where mkey=`source, mval in srcBlobs;
  if[0=count rids; :0];

  / Drop rows from the main table and the meta table.
  ![cname;    enlist(in;`id;rids); 0b; `symbol$()];
  ![metaName; enlist(in;`id;rids); 0b; `symbol$()];
  / Functional delete can drop the `g# attribute -- re-apply (schema-1).
  .rag.applyMetaAttr metaName;

  / Persist both (crash-safe).
  .rag.atomicSet[.Q.dd[DATA_DIR; cname];    value cname];
  .rag.atomicSet[.Q.dd[DATA_DIR; metaName]; value metaName];

  / Rebuild the index from the remaining vectors (no per-id delete on either
  / backend).  CAGRA: .rag.cagra.rebuild also re-persists the .cagra/.kdb files.
  / HNSW: rebuild from all surviving vectors (() for the now-empty case --
  / .ai.hnsw.put signals 'type on a typed-empty real).
  / NB (TODO 1.9): this rebuild is SYNCHRONOUS on q's single thread.  The
  / liveness probe budget is period 30s x failureThreshold 10 = ~5 min -- a
  / multi-million-row HNSW rebuild could exceed that and get the pod killed
  / mid-rebuild (CAGRA is covered by its build marker).  Keep collections
  / within that budget or raise the chart's liveness failureThreshold.
  idxFP:.rag.fp[cname; "_idx"];
  $[(.rag.idxType cname)=`cagra;
    .rag.cagra.rebuild cname;
    [embs:exec vec from value cname;
     .rag[idxFP]:$[0=count embs;
       ();
       .ai.hnsw.put[(); (); "e"$embs; .rag.metricOf cname; .rag.hnsw.M; .rag.hnsw.ml; .rag.hnsw.efConstruction]]]];

  count rids
 };

/ ====== .rag.insert[cname; ids; vecs; docs; metas]  ->  long ======
/ Appends `vecs` to the collection and extends the HNSW graph.  Returns the
/ number of rows inserted.
/   ids   long[]    -- vector ids (caller-generated; uniqueness enforced by caller)
/   vecs  real[][]  -- N×dim float32 vectors (cast with "e"$ if needed)
/   docs  string[]  -- source text chunks (one per id)
/   metas dict[]    -- N metadata dicts (key->value); empty `()!()` ok
/ Signals on unknown collection or dim mismatch.  Persists vector + meta
/ tables; HNSW graph is in-memory only (rebuilt on restart from vectors).
.rag.insert:{[cname; ids; vecs; docs; metas]
  cname:.rag.toSym cname;
  if[not cname in exec name from .rag.collections;
    '`insert_unknown_collection];
  expectedDim:first exec dim from .rag.collections where name=cname;
  actualDim:count first vecs;
  / dim-1: a collection that was created but never inserted into (or rehydrated
  / from an empty persisted table) carries dim 0 in the catalogue -- the original
  / dim can't be recovered from zero vectors.  Adopt the incoming vector's dim
  / and repair the catalogue rather than signalling a spurious mismatch that
  / would make the collection permanently un-insertable after a pod restart.
  / Post-insert the table is non-empty, so future rehydrates recover dim correctly.
  if[(0=expectedDim) and 0<actualDim;
    expectedDim:actualDim;
    update dim:actualDim from `.rag.collections where name=cname];
  if[expectedDim<>actualDim;
    '`insert_dim_mismatch];

  N:count ids;
  / Cast caller-supplied vectors to real (float32) so the table column type
  / matches what the HNSW graph is indexed against -- otherwise search hits
  / 'type when reading `vec` back as embs.  Caller may already cast on the
  / Python side; `"e"$` is idempotent on a typed-real list.
  vecsR:"e"$vecs;

  / kx.ai keeps vectors separate from the graph -- capture the prior set
  / before we append so we can pass it back to .ai.hnsw.put as `embs`.
  priorVecs:exec vec from value cname;

  / Append rows + persist (crash-safe: a torn table file is unreadable forever).
  cname upsert flip `id`vec`doc`ts!(ids; vecsR; docs; N#.z.p);
  .rag.atomicSet[.Q.dd[DATA_DIR; cname]; value cname];

  / Update the index (backend-aware) UNDER PROTECTION (q-TODO 1.3).  The rows
  / were appended+persisted above; if the index step then fails (GPU fault,
  / wsfull, ...) table and index silently diverge: the next HNSW put would see
  / embs the graph lacks (every later insert fails), and the appended rows have
  / no meta yet (invisible to getDocuments, undeletable by source).  So trap
  / the index step; on failure ROLL BACK the rows just appended (drop the last
  / N -- upsert appends, so this is exact even if caller ids collide with
  / existing rows), re-persist, and re-signal the original error.
  / HNSW extends incrementally via .ai.hnsw.put (prior vectors as `embs`).
  / CAGRA extends its mutable foreign in place (or builds once enough rows
  / exist) and persists the .cagra/.kdb files; if the GPU op crashed the pod
  / outright its build marker forces a clean rebuild on the next boot.
  / NB: q lambdas don't close over outer locals -- pass everything explicitly.
  idxFP:.rag.fp[cname; "_idx"];
  ixErr:.[{[cname; vecsR; idxFP; priorVecs]
      $[(.rag.idxType cname)=`cagra;
        .rag.cagra.insertVecs[cname; vecsR];
        .rag[idxFP]:.ai.hnsw.put[priorVecs; .rag idxFP; vecsR;
                                  .rag.metricOf cname; .rag.hnsw.M; .rag.hnsw.ml; .rag.hnsw.efConstruction]];
      ""};
    (cname; vecsR; idxFP; priorVecs);
    {[e] e}];
  if[count ixErr;
    cname set neg[N] _ value cname;
    .rag.atomicSet[.Q.dd[DATA_DIR; cname]; value cname];
    'ixErr];

  / Persist metadata in tall form, skipping when every dict is empty.
  if[any 0<count each metas;
    metaName:.rag.fp[cname; "_meta"];
    metaRows:raze {[id;m]
      flip `id`mkey`mval!(count[m]#id; key m; value m)
     }'[ids; metas];
    metaName upsert metaRows;
    .rag.applyMetaAttr metaName;
    .rag.atomicSet[.Q.dd[DATA_DIR; metaName]; value metaName]];

  N
 };

/ ====== .rag.search[cname; queryVec; k; filter]  ->  dict ======
/ Returns four equal-length lists keyed `ids`distances`docs`metas.  Distances
/ are L2 (lower = closer).
/ `filter` is a functional-select where-clause (list of triples like
/ `enlist(in;`id;allowedIds)`).  Pass `()` for unfiltered search.
/ With a filter, candidate rows are resolved against the main table and
/ passed to `.ai.hnsw.filterSearch` as a graph-position allow-list.
.rag.search:{[cname; queryVec; k; filter]
  cname:.rag.toSym cname;
  if[not cname in exec name from .rag.collections;
    '`search_unknown_collection];
  t    :value cname;
  embs :t`vec;
  graph:.rag .rag.fp[cname; "_idx"];
  / Empty / never-inserted collection: the HNSW graph is still the `() sentinel
  / and embs is empty, so .ai.hnsw.search would signal 'rank.  Return the normal
  / empty result shape (mirrors the empty-allowIxs short-circuit below).
  if[0=count embs;
    :`ids`distances`docs`metas!(`long$(); `real$(); (); ())];
  qv   :"e"$queryVec;
  it   :.rag.idxType cname;
  / HNSW search MUST use the same metric the graph was built with (WS-METRIC).
  m    :.rag.metricOf cname;

  / Both backends return (distances; 0-based positions).  CAGRA: use the cuVS
  / index when built, else the exact-scan fallback (sub-minRows window).  HNSW:
  / kx.ai search.  Filter present -> resolve allowed row positions first.
  res:$[0=count filter;
    $[it=`cagra;
      $[()~graph; .rag.cagra.exactScan[embs; qv; k; ()];
        .cuvs.cagra.search[graph; qv; k; .rag.cagra.searchParams k]];
      .ai.hnsw.search[embs; graph; qv; k; m; .rag.hnsw.efSearch]];
    [
      filteredIds:?[t; filter; 0b; (enlist`id)!enlist`id]`id;
      allowIxs:where t[`id] in filteredIds;
      $[0=count allowIxs;
        ("e"$();`long$());
        it=`cagra;
          $[()~graph; .rag.cagra.exactScan[embs; qv; k; allowIxs];
            .cuvs.cagra.filter[graph; qv; k&count allowIxs; .rag.cagra.searchParams[k&count allowIxs]; allowIxs]];
        .ai.hnsw.filterSearch[embs; graph; qv; k&count allowIxs; m; .rag.hnsw.efSearch; allowIxs]]]];

  rdists:res 0;
  rixs  :res 1;

  / Map graph row positions back to caller-supplied ids + join docs + metas.
  rids   :t[`id] rixs;
  / Positional doc lookup (TODO 1.9): an id->doc dict would resolve duplicate
  / ids to the FIRST occurrence's doc; indexing the doc column by the result
  / positions is both simpler and always row-correct.
  rdocs  :t[`doc] rixs;
  metaName:.rag.fp[cname; "_meta"];
  / q-3: resolve metadata for ALL result ids in a single grouped pass instead
  / of one full meta-table scan per result.  `where id in rids` rides the `g#
  / attribute on the meta table's id column (see .rag.applyMetaAttr), so this
  / is a hash lookup, not an O(rows) scan.  byId is keyed on id with the per-id
  / mkey/mval lists grouped; rebuild each result's mkey!mval dict, falling back
  / to an empty dict for ids that carry no metadata.
  / NB: alias the grouped columns mkeys/mvals (not the builtins key/value), and
  / never reference the virtual `i` -- both are q parser traps hit before here.
  byId   :select mkeys:mkey, mvals:mval by id from value[metaName] where id in rids;
  present:exec id from key byId;
  rmetas :{[byId;present;rid]
    $[rid in present; [r:byId rid; (r`mkeys)!r`mvals]; ()!()]
   }[byId;present;] each rids;

  `ids`distances`docs`metas!(rids; rdists; rdocs; rmetas)
 };

/ ====== .rag.getDocuments[cname]  ->  table([] source:<value>) ======
/ Returns the distinct `source` values from the collection's metadata table.
/ "source" is the conventional key the upstream RAG uses to identify originating
/ documents.  Returns an empty table when the meta table is absent or empty.
.rag.getDocuments:{[cname]
  cname:.rag.toSym cname;
  metaName:.rag.fp[cname; "_meta"];
  if[not metaName in tables `.; :([] source:())];
  flip (enlist`source)!enlist exec distinct mval from value[metaName] where mkey=`source
 };

/ ====== .rag.getDocumentsWithMeta[cname]  ->  table([] id; source; contentMeta) ======
/ Like .rag.getDocuments but also returns each chunk's content_metadata blob,
/ so the Python adapter can pivot per-schema-field metadata without an extra
/ round trip per document.  One row per chunk id; the Python side dedupes by
/ source and keeps the first chunk's metadata (matching the kdbai adapter).
/ Returns an empty 2-col table when the meta table is absent.
.rag.getDocumentsWithMeta:{[cname]
  cname:.rag.toSym cname;
  metaName:.rag.fp[cname; "_meta"];
  if[not metaName in tables `.; :([] source:(); contentMeta:())];
  m:value metaName;
  s:select id, source:mval from m where mkey=`source;
  c:`id xkey select id, contentMeta:mval from m where mkey=`content_metadata;
  s lj c
 };

/ ====== Metadata schema registration (field -> q-type symbol) ======
/ The kdbx adapter uses this for optional client-side type checks.  The schema
/ is stored as a slot in `.rag` (under `<cname>_schema`) and persisted to disk
/ alongside the collection tables.
.rag.addMetadataSchema:{[cname; schema]
  cname:.rag.toSym cname;
  fp:.rag.fp[cname; "_schema"];
  .rag[fp]:schema;
  (.Q.dd[DATA_DIR; fp]) set schema;
 };

.rag.getMetadataSchema:{[cname]
  cname:.rag.toSym cname;
  fp:.rag.fp[cname; "_schema"];
  $[fp in key `.rag; .rag fp; ()!()]
 };

/ ====== .rag.rehydrate[]  ->  long ======
/ Walk DATA_DIR and rebuild in-memory state for any persisted collection.
/ For each `<cname>` table found on disk (excluding `<cname>_meta` and
/ `<cname>_schema` siblings):
/   1. Load the vector + meta tables back into the root namespace.
/   2. Re-register the collection in the catalogue (recovering `dim` from
/      the first row's vector and any persisted `_schema`).
/   3. Rebuild the HNSW graph from the persisted vector column -- graphs are
/      NOT persisted (just the embeddings), so a pod recycle would otherwise
/      lose all retrieval capability.
/ Returns the number of collections rehydrated.  Safe to call multiple times
/ (an already-loaded collection is a no-op).
.rag.rehydrate:{[]
  / Skip cleanly when DATA_DIR doesn't exist (first-boot before any writes).
  if[()~@[key; DATA_DIR; {()}]; :0];

  / Per-collection rehydration.  Returns the rehydrated cname (or `:: when
  / the collection was already loaded), so `each` collects a list we can
  / count for the log message -- no side-effect counter.
  rehydrateOne:{[cname]
    if[cname in exec name from .rag.collections; :(::)];
    / Load the vector table back into the root namespace.
    cname set get .Q.dd[DATA_DIR; cname];

    / Load the meta table (or initialise empty if not on disk).
    metaName:.rag.fp[cname; "_meta"];
    metaPath:.Q.dd[DATA_DIR; metaName];
    metaName set $[()~@[get; metaPath; {()}];
      ([] id:`long$(); mkey:`symbol$(); mval:());
      get metaPath];
    / Ensure the `g# lookup attribute is present after reload (schema-1).
    .rag.applyMetaAttr metaName;

    / Recover dim from the first row's vector (0 when the table is empty --
    / the caller can re-create with the correct dim later).
    rows:value cname;
    dim:$[count rows; count first rows`vec; 0];

    / Restore the schema slot if persisted, else leave .rag.<n>_schema unset.
    schemaFP:.rag.fp[cname; "_schema"];
    schema:@[get; .Q.dd[DATA_DIR; schemaFP]; {()}];
    if[not ()~schema; .rag[schemaFP]:schema];

    / Restore the persisted backend choice (no sidecar => legacy hnsw).  A cagra
    / collection on a non-GPU pod is DOWNGRADED to hnsw so it stays queryable
    / (vectors are identical; only the index differs).  The _idxtype sidecar is
    / left intact, so a GPU pod re-promotes it to cagra on a later rehydrate.
    idxFP:.rag.fp[cname; "_idx"];
    want:@[get; .Q.dd[DATA_DIR; .rag.fp[cname; "_idxtype"]]; {`hnsw}];
    effIt:$[(want=`cagra) and not .rag.cuvs.enabled; `hnsw; want];
    if[(want=`cagra) and not effIt=`cagra;
      -1 "[kdbx] rehydrate: ",(string cname)," is cagra but cuVS unavailable -- serving as hnsw"];
    / Restore the per-collection metric (WS-METRIC).  No sidecar => legacy
    / collection written before WS-METRIC: fall back to the pod global, matching
    / pre-WS-METRIC behavior (the best we can do without a stamped value).
    m:@[get; .Q.dd[DATA_DIR; .rag.fp[cname; "_metric"]]; {.rag.metric}];
    `.rag.collections upsert (cname; dim; (); idxFP; effIt; m);
    / Build the index.  CAGRA: prefer the persisted .cagra (skip the rebuild),
    / else rebuild from vectors.  HNSW: rebuild the graph from all vectors
    / (() sentinel when empty; "e"$() typed-empty would raise 'type in kx.ai).
    .rag[idxFP]:$[0=count rows; ();
      effIt=`cagra;
        / WS-SAFETY: consult the three guards before trusting the persisted blob.
        / A non-empty reason => skip the (potentially fatal) .read and rebuild
        / from the intact vector table.  An empty reason => attempt the read.
        [skipReason:.rag.cagra.skipReadReason cname;
         $[0<count skipReason;
           [-1 "[kdbx] rehydrate: ",(string cname),": skipping .cagra read (",skipReason,") -- rebuilding";
            .rag.cagra.rebuild cname];
           / @[f;arg;handler]: f is UNAPPLIED (1 implicit param x:=cname) so @ runs
           / it under protection.  Eagerly applying f[cname] here would evaluate the
           / read OUTSIDE the trap, then hand its (foreign) result to @ as the thing
           / to apply to `::` -- which raises a spurious 'rank and forces a needless
           / rebuild even though the read succeeded.
           @[{.cuvs.cagra.read[.rag.cagra.basePath x; .rag.cagra.gpuid]};
             cname;
             {[c;e] -1 "[kdbx] rehydrate: .cagra read failed (",e,") -- rebuilding"; .rag.cagra.rebuild c}[cname;]]]];
      .ai.hnsw.put[(); (); "e"$rows`vec; .rag.metricOf cname; .rag.hnsw.M; .rag.hnsw.ml; .rag.hnsw.efConstruction]];
    cname
   };

  / `key DATA_DIR` returns a symbol vector -- collection files AND any noise
  / the PVC introduced (ext4's lost+found dir, hidden files, etc.).  Two
  / filters narrow that down to actual collections:
  /   1. The filename must look like a valid collection identifier (leading
  /      letter/underscore, then [A-Za-z0-9_.] -- matches the Python adapter's
  /      _CNAME_RE allowlist).  This drops `lost+found`, `.snapshot`, etc.
  /   2. The filename must NOT be a sidecar of an already-counted collection:
  /      _meta / _schema / _idxtype / _metric / _cagrastamp / _cagrabuilding
  /      tables, or the cuVS .cagra / .kdb index files.  cnameLike allows `.`, so
  /      the extension-based ones MUST be excluded explicitly here or they become
  /      phantom collections (q-6 + Phase-2 sidecars).
  cnameLike:{[s]
    if[0=count s; :0b];
    leads:(first s) in .Q.a,.Q.A,"_";
    rest:(1_s) inter .Q.a,.Q.A,.Q.n,"_.";
    leads and (count rest)=count 1_s
   };
  files:key DATA_DIR;
  sidecar:{[f] any (string f) like/: ("*_meta"; "*_schema"; "*_idxtype"; "*_metric"; "*_cagrastamp"; "*_cagrabuilding"; "*.cagra"; "*.kdb"; "*.tmp")};
  base:files where (cnameLike each string files) and not sidecar each files;

  / Run rehydration per collection UNDER PROTECTION (q-TODO 1.1a): one torn /
  / unreadable / stray file must SKIP that one collection (logged loudly), not
  / abort the whole rehydrate -- an abort here kills the rest of the init load
  / and leaves q listening with .rag.* partially defined (the zombie-pod mode;
  / see also the .rag.initComplete sentinel + readiness.q).
  / NB: rehydrateOne is a LOCAL and q lambdas don't close over outer locals --
  / pass it in explicitly.  `each` collects each call's return -- cname on
  / success, `:: when already loaded or skipped -- so counting non-:: results
  / gives the rehydrated count.
  results:{[f; c]
    @[f; c; {[c; e]
      -1 "[kdbx] rehydrate: SKIPPED ",(string c)," (",e,") -- collection not loaded; inspect ",string .Q.dd[DATA_DIR; c];
      (::)}[c;]]
   }[rehydrateOne;] each base;
  n:count results where not results~\:(::);
  -1 "[kdbx-init] rehydrated ",string[n]," collection(s) from ",string DATA_DIR;
  n
 };

/ Server-managed version constant — checked by the adapter on connect.
.rag.version:"2.4.0";

/ Run rehydration once at startup.  Idempotent on re-invocation.
.rag.rehydrate[];

/ Build the GPU readiness canary (no-op on a CPU pod). After rehydrate so it
/ doesn't contend with the (potentially large) rehydrate builds.
.rag.cuvs.buildCanary[];

/ Init-complete sentinel (q-TODO 1.1b) -- the LAST assignment in this file
/ (only the ready log follows).  readiness.q requires this to be defined and
/ true: if the load aborts ANYWHERE above, the sentinel is absent and the pod
/ reports NOT-ready instead of serving traffic with partial .rag.* state.
.rag.initComplete:1b;

-1 "[kdbx-init] ready on port ",string system"p";
