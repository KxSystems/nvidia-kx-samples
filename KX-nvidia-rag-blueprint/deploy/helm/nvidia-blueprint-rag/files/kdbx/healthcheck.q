/ deploy/helm/nvidia-blueprint-rag/files/kdbx/healthcheck.q
/ Liveness probe — exit 0 if KDB-X responds, non-zero otherwise.
/ Mounted into the pod by kdbx-configmap; called by the probe via `q healthcheck.q`.
/ NOTE: never use a lone "/" (or "/ " + only whitespace) line here — in q that
/ opens a block comment running to a lone "\" and would silently disable this probe.
/ Liveness uses a trivial `1+1` eval (NOT .rag.ping or the GPU canary): it should
/ assert only that q is up + responsive, staying independent of bootstrap/GPU
/ state. A heavier liveness could kill-and-restart the pod and churn its RWO PVC
/ during the at-startup cuVS install / first CAGRA build. GPU/bootstrap health is
/ the readiness probe's job (readiness.q). kdbx-init.q is loaded at q startup, so
/ .rag.* exists by the time the server accepts connections.
/ Port comes from KDBX_LISTEN_PORT (TODO 1.9; the entrypoint honors the same
/ env -- a hardcoded 5000 here would kill-loop any pod using the knob), and
/ hopen carries a 2s timeout so a wedged listener can't hang the probe past
/ the kubelet's own timeoutSeconds.

p:"J"$getenv `KDBX_LISTEN_PORT;
p:$[(not null p) and p>0; p; 5000];

@[{[p]
  h:hopen (`$"::",string p; 2000);
  r:h"1+1";
  hclose h;
  $[r=2; exit 0; exit 1]
 };
 p;
 {-2 "healthcheck failed: ",x; exit 1}];
