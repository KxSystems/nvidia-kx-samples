/ tests/q/test_rag_wrappers.q
/ Run via: q tests/q/test_rag_wrappers.q -q
/ Exits 0 on pass, non-zero on failure.

\l /opt/kx/conf/kdbx-init.q

assert:{[name; cond] $[cond; -1 "PASS ",name; [-1 "FAIL ",name; exit 1]]}

/ Test 1: .rag.ping returns `pong
assert["ping"; `pong = .rag.ping[]]

/ Test 2: createCollection registers it
.rag.createCollection[`t1; 128; (); `hnsw; (::)];
assert["create"; `t1 in exec name from .rag.collections];
assert["dim"; 128 = first exec dim from .rag.collections where name=`t1];

/ Test 3: idempotency — second create is a no-op
.rag.createCollection[`t1; 128; (); `hnsw; (::)];
assert["idem"; 1 = count exec name from .rag.collections where name=`t1];

/ Test 4: list returns the right shape
ls:.rag.listCollections[];
assert["list type"; 99h = type ls];  / dict
assert["list has t1"; `t1 in key ls];

/ Test 5: delete removes
.rag.deleteCollection[`t1];
assert["delete"; not `t1 in exec name from .rag.collections];

/ ====== .rag.insert ======

/ Test 6: insert appends rows + grows the HNSW graph; returns row count.
.rag.createCollection[`t2; 16; (); `hnsw; (::)];
N:100; D:16;
ids:til N;
vecs:"e"$(N;D)#N?1e;
docs:N#enlist "test doc";
metas:N#enlist ()!();
inserted:.rag.insert[`t2; ids; vecs; docs; metas];
assert["insert count";    N = count value `t2];
assert["insert returned"; N = inserted];

/ Test 7: insert rejects wrong dim (signal is the symbol `insert_dim_mismatch).
@[{.rag.insert[`t2; til 5; "e"$(5;99)#0.0; 5#enlist "x"; 5#enlist ()!()]};
  ();
  {assert["dim err"; x ~ "insert_dim_mismatch"]}];

/ Test 8: insert rejects unknown collection.
@[{.rag.insert[`tNope; til 1; "e"$1 1#0.0; enlist "x"; enlist ()!()]};
  ();
  {assert["unknown coll err"; x ~ "insert_unknown_collection"]}];

.rag.deleteCollection[`t2];

/ ====== .rag.search (no filter) ======

/ Test 9: search returns top-k with monotonic L2 distances; self-match wins.
.rag.createCollection[`t3; 8; (); `hnsw; (::)];
N:50; D:8;
ids:til N;
vecs:"e"$(N;D)#N?1e;
docs:string ids;
.rag.insert[`t3; ids; vecs; docs; N#enlist ()!()];
res:.rag.search[`t3; first vecs; 5; ()];
assert["search count";         5 = count res`ids];
assert["search dist monotone"; all 0<=1_deltas res`distances];
/ The query is a row of t3 — distance 0 to itself.
assert["self match";           0 = first res`distances];
assert["docs joined";          5 = count res`docs];

.rag.deleteCollection[`t3];

/ ====== .rag.search with filter ======

/ Test 10: filtered search restricts results to allow-list.
.rag.createCollection[`t4; 8; (); `hnsw; (::)];
N:20; D:8;
ids:til N;
vecs:"e"$(N;D)#N?1e;
docs:string ids;
.rag.insert[`t4; ids; vecs; docs; N#enlist ()!()];
/ Functional-select where-clause: only even ids.
allowedIds:2*til N div 2;
filterExpr:enlist (in;`id;allowedIds);
res:.rag.search[`t4; first vecs; 5; filterExpr];
assert["filter count";      5 = count res`ids];
assert["filter restricted"; all res[`ids] in allowedIds];

/ Test 11: filter with no matches returns empty.
emptyFilter:enlist (=;`id;-1);
resEmpty:.rag.search[`t4; first vecs; 5; emptyFilter];
assert["empty filter";      0 = count resEmpty`ids];

.rag.deleteCollection[`t4];

/ ====== .rag.getDocuments + metadata schema ======

/ Test 12: getDocuments returns distinct `source` from the meta table.
.rag.createCollection[`t5; 4; (); `hnsw; (::)];
.rag.insert[`t5; 0 1 2; "e"$3 4#1e; 3#enlist "src1"; 3#enlist `source`page!("doc.pdf";1)];
.rag.insert[`t5; 3 4;   "e"$2 4#1e; 2#enlist "src2"; 2#enlist `source`page!("doc.pdf";2)];
docsTbl:.rag.getDocuments[`t5];
assert["getDocs"; 1 = count distinct docsTbl`source];

/ Test 13: addMetadataSchema + getMetadataSchema round-trip.
/   Schema is a field→q-type-symbol dict.
schema:`source`page!(`symbol;`long);
.rag.addMetadataSchema[`t5; schema];
got:.rag.getMetadataSchema[`t5];
assert["schema rt"; schema ~ got];

/ Test 14: getMetadataSchema on an unregistered collection returns empty dict.
empt:.rag.getMetadataSchema[`tNeverSet];
assert["empty schema"; 0 = count empt];

.rag.deleteCollection[`t5];

/ ====== WP1 ship-readiness fixes (docs/kdbx-ship-readiness-todo.md) ======

/ Test 15: init-complete sentinel is set (readiness.q gates on it; if the init
/ load had aborted anywhere, this would be undefined and the pod NOT-ready).
assert["init sentinel"; 1b~.rag.initComplete];

/ Test 16: stampMatches treats a SYMMETRIC nvidia-smi failure as MISMATCH
/ (q-TODO 1.4).  On this CPU container envStamp's GPU segment is "" -- write a
/ sidecar holding the same degenerate "|" stamp (what a both-sides-failed
/ build would produce) and assert it does NOT match.
.rag.createCollection[`t6; 4; (); `hnsw; (::)];
(.Q.dd[DATA_DIR; .rag.cagra.stampSidecar `t6]) set "|";
assert["stamp sym-fail mismatch"; not .rag.cagra.stampMatches `t6];

/ Test 17: skipReadReason guard branches (GPU-free by design).
.rag.cagra.markBuildStart `t6;
assert["skip reason marker"; (.rag.cagra.skipReadReason `t6) like "stale build marker*"];
.rag.cagra.markBuildDone `t6;
assert["skip reason stamp"; (.rag.cagra.skipReadReason `t6) like "build-env stamp mismatch*"];
sv0:.rag.cagra.skipPersistedRead;
.rag.cagra.skipPersistedRead:1b;
assert["skip reason killswitch"; (.rag.cagra.skipReadReason `t6) like "kill-switch*"];
.rag.cagra.skipPersistedRead:sv0;

/ Test 18: an empty rebuild (rows < minRows) DELETES any stale persisted blob
/ + stamp (q-TODO 1.2) -- otherwise a later rehydrate reads a graph misaligned
/ with the shrunken table and returns wrong documents.
bp:.rag.cagra.basePath `t6;
(hsym `$bp,".cagra") set 0x00;
(hsym `$bp,".kdb") set 0x00;
.rag.cagra.rebuild `t6;
assert["stale cagra deleted"; not any (`$string[`t6],/:(".cagra"; ".kdb"; "_cagrastamp")) in key DATA_DIR];
.rag.deleteCollection[`t6];

/ Test 19: insert ROLLS BACK appended rows when the index step fails
/ (q-TODO 1.3) -- in-memory and on-disk row counts must be unchanged and the
/ original error re-signalled.
.rag.createCollection[`t7; 4; (); `hnsw; (::)];
.rag.insert[`t7; 0 1 2; "e"$3 4#1e; 3#enlist "d"; 3#enlist ()!()];
origPut:.ai.hnsw.put;
.ai.hnsw.put:{[a;b;c;d;f;g;h] '`forced_index_failure};
err:@[{.rag.insert[`t7; 3 4; "e"$2 4#2e; 2#enlist "x"; 2#enlist ()!()]; ""}; ::; {[e] e}];
.ai.hnsw.put:origPut;
assert["rollback resignals";  err like "forced_index_failure*"];
assert["rollback rows mem";   3 = count value `t7];
assert["rollback rows disk";  3 = count get .Q.dd[DATA_DIR; `t7]];
/ ...and a normal insert still works afterwards (index/table not desynced).
.rag.insert[`t7; 3 4; "e"$2 4#2e; 2#enlist "x"; 2#enlist ()!()];
assert["rollback recovers";   5 = count value `t7];
.rag.deleteCollection[`t7];

/ Test 20: rehydrate SKIPS an unreadable stray file instead of aborting
/ (q-TODO 1.1a) -- a torn file must cost one collection, not the whole init.
(.Q.dd[DATA_DIR; `zzjunk]) 1: 0x0102030405;
ok:@[{.rag.rehydrate[]; 1b}; ::; {[e] 0b}];
assert["rehydrate skips junk"; ok];
assert["junk not registered";  not `zzjunk in exec name from .rag.collections];
@[hdel; .Q.dd[DATA_DIR; `zzjunk]; {[e]::}];

/ Test 21: a leftover .tmp file (crash between atomicSet's write and rename)
/ is NOT treated as a collection on rehydrate.
(`$(string .Q.dd[DATA_DIR; `t9]),".tmp") set ([] id:`long$(); vec:(); doc:(); ts:`timestamp$());
.rag.rehydrate[];
assert["tmp excluded"; not (`$"t9.tmp") in exec name from .rag.collections];
@[hdel; `$(string .Q.dd[DATA_DIR; `t9]),".tmp"; {[e]::}];

/ Test 22: resolveIndexType downgrades cagra -> hnsw when cuVS is unavailable
/ (this test image is CPU-only, so .rag.cuvs.enabled is 0b).
assert["cagra downgrade";  `hnsw = .rag.resolveIndexType `cagra];
assert["hnsw passthrough"; `hnsw = .rag.resolveIndexType `hnsw];
assert["default resolve";  `hnsw = .rag.resolveIndexType (::)];

/ Test 23: cagra.exactScan returns exact L2 top-k (pure math, GPU-free).
embs:"e"$(0 0; 1 0; 0 3; 5 0);
r:.rag.cagra.exactScan[embs; 0 0f; 2; ()];
assert["exactScan order"; (r 1) ~ 0 1];
assert["exactScan dist";  (first r) ~ 0 1f];  / sqrt returns float, not real
rf:.rag.cagra.exactScan[embs; 0 0f; 2; 2 3];
assert["exactScan filter"; (rf 1) ~ 2 3];

/ Test 24: per-collection metric request is honored + stamped (review-2 #3 --
/ the adapter's metric was previously dropped and every collection silently
/ used the pod global).
assert["resolveMetric CS";      `CS = .rag.resolveMetric `CS];
assert["resolveMetric string";  `IP = .rag.resolveMetric "IP"];
assert["resolveMetric default"; .rag.metric = .rag.resolveMetric (::)];
assert["resolveMetric bogus";   .rag.metric = .rag.resolveMetric `bogus];
.rag.createCollection[`t10; 4; (); `hnsw; `CS];
assert["metric stamped";  `CS = .rag.metricOf `t10];
assert["metric persisted"; `CS = get .Q.dd[DATA_DIR; .rag.fp[`t10; "_metric"]]];
.rag.deleteCollection[`t10];

-1 "ALL TESTS PASSED";
exit 0
