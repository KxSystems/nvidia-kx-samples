#!/usr/bin/env bash
# Run q-side wrapper tests inside the built KDB-X image.
# Usage: ./tests/q/run_q_tests.sh <kdbx-image>
set -euo pipefail
IMAGE="${1:-${KDBX_IMAGE:-localhost/kdbx-rag:1.0.0}}"

# NB: a top-level q SIGNAL (e.g. a 'type mid-script) aborts the script load,
# after which q hits stdin-EOF and exits 0 -- a silent FALSE GREEN.  So exit
# code alone is not trustworthy: require the suite's final success marker in
# the output as well.
out=$(docker run --rm \
  -v "$(pwd)/deploy/helm/nvidia-blueprint-rag/files/kdbx/kdbx-init.q:/opt/kx/conf/kdbx-init.q:ro" \
  -v "$(pwd)/tests/q/test_rag_wrappers.q:/opt/kx/tests/test_rag_wrappers.q:ro" \
  --entrypoint /opt/kx/.kx/bin/q \
  "$IMAGE" \
  /opt/kx/tests/test_rag_wrappers.q -q 2>&1) || { echo "$out"; echo "q tests FAILED (exit code)"; exit 1; }
echo "$out"
if ! grep -q "ALL TESTS PASSED" <<<"$out"; then
  echo "q tests FAILED (no 'ALL TESTS PASSED' marker -- script aborted mid-run)"
  exit 1
fi
