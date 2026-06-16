/ deploy/helm/nvidia-blueprint-rag/files/kdbx/readiness.q
/ Readiness probe (WS-SAFETY) — exit 0 if the pod should receive traffic.
/ Mounted into the pod by kdbx-configmap; invoked by the probe via `q readiness.q`.
/ NOTE: never use a lone "/" (or "/ " + only whitespace) line here — in q that
/ opens a block comment that runs to a lone "\" and would silently disable this
/ whole probe. Use a blank line or "/ text" as a separator.
/ kdbx-init.q is loaded at q startup and sets .rag.initComplete:1b as its LAST
/ assignment.  q is single-threaded: it only answers IPC after the init load
/ has finished (or aborted partway), so once our query below gets an answer,
/ an absent sentinel can only mean the load ABORTED — the pod would otherwise
/ serve traffic with partial .rag.* definitions forever (q-TODO 1.1b: the old
/ probe trapped that state to "ready", creating exactly that zombie mode).
/ Once init is complete, readiness runs the GPU canary so a wedged GPU context
/ pulls the pod from service WITHOUT a liveness kill (liveness stays the cheap
/ eval in healthcheck.q, so a faulted pod isn't killed-and-restarted, churning
/ its RWO PVC).

/ Decision (evaluated server-side):
/   q not answering yet         -> NOT ready (outer trap: connect refused = still booting)
/   init aborted (no sentinel)  -> NOT ready (error trapped server-side to 0b)
/   init complete, CPU pod      -> ready
/   init complete, GPU healthy  -> ready  (canary search succeeds)
/   init complete, GPU wedged   -> NOT ready (canary returns 0b; a canary that
/                                  was never built reports ready — inconclusive
/                                  builds must not pull a healthy pod)

p:"J"$getenv `KDBX_LISTEN_PORT;
p:$[(not null p) and p>0; p; 5000];

@[{[p]
  h:hopen (`$"::",string p; 2000);
  r:h"@[{$[not .rag.initComplete; 0b; .rag.cuvs.enabled; .rag.cuvs.canary[]; 1b]}; ::; {[e] 0b}]";
  hclose h;
  $[r; exit 0; exit 1]
 };
 p;
 {-2 "readiness probe failed: ",x; exit 1}];
