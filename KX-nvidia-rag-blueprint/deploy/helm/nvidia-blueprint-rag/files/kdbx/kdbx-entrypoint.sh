#!/bin/sh
# SPDX-FileCopyrightText: Copyright (c) 2026 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# kdbx-entrypoint.sh — test-deploy bootstrap for a GPU+cuVS-capable KDB-X.
#
# PRODUCTION NOTE: this script exists ONLY to stand up KDB-X for *testing this
# blueprint*. In production KDB-X is customer-managed (installed properly on
# accessible infra with cuVS set up by the customer) and the blueprint just
# connects to its endpoint — see memory `project-kdbx-production-model`. Do NOT
# treat this as a production install path.
#
# It formalises the steps validated by hand on a g5.2xlarge (A10G, cuVS 25.10,
# commit 478422b). Every step is idempotent and presence-gated, so the script
# works both on the KDB-X-baked image (Dockerfile.kdbx) — where the install
# steps are no-ops — and on a plain base image where it does the full install.
#
# Caching: NONE. install_deps.sh pulls ~GBs of CUDA on every cold start
# (chosen for simplicity in a test deploy). A rarely-restarted test pod is the
# assumed usage; if restarts become frequent, bake cuVS into the image instead.
#
# Env (set by the chart):
#   QHOME            KDB-X home (module dir is $QHOME/mod/kx/<name>, matching
#                    kdbx-init.q's loadMod which resolves getenv[`QHOME]).
#   HOME             miniforge install root ($HOME/miniforge3).
#   KDBX_USE_CUVS    "1" to install + enable cuVS (GPU CAGRA); anything else
#                    skips cuVS entirely and runs CPU HNSW only.
#   KDB_LICENSE_B64  base64 KDB-X license — required only if q is not present
#                    (i.e. when this script performs the KDB-X install itself).
#   KDB_BEARER_TOKEN KX portal OAuth token — required only when this script
#                    downloads KDB-X and/or the cuVS module at runtime.
#   KDBX_LISTEN_PORT listen port (default 5000). NOT named KDBX_PORT: a k8s
#                    Service called "kdbx" auto-injects KDBX_PORT=tcp://<ip>:5000
#                    (legacy Docker-link env), which would clobber a plain port.
#
# This script launches q WITH kdbx-init.q loaded at startup (see the exec at the
# bottom): kdbx-init.q defines all .rag.* functions and runs .rag.rehydrate[] +
# the cuVS readiness canary before the first connection is accepted. cuVS is
# installed + LD_LIBRARY_PATH exported here first so the init's `use kx.cuvs`
# works server-side. (The adapter no longer pushes the bootstrap over IPC.)
# set -eu makes a cuVS download/install failure CRASH-LOOP the pod, while the
# q layer deliberately DEGRADES cagra->hnsw when cuVS is absent (TODO 1.9).
# This asymmetry is intentional: you explicitly asked for GPU (kdbx.useCuvs),
# so a broken GPU setup should fail loudly here, not silently serve CPU HNSW.
set -eu

log() { echo "[kdbx-entrypoint] $*"; }

QHOME="${QHOME:-/opt/kx/.kx}"
HOME="${HOME:-/opt/kx}"
KDBX_LISTEN_PORT="${KDBX_LISTEN_PORT:-5000}"
PORTAL="https://portal.dl.kx.com/assets/raw/kdb-x"

# ---- 1. ensure KDB-X (no-op when the image already ships q) ----------------
ensure_kdbx() {
    if [ -x "${QHOME}/bin/q" ]; then
        log "KDB-X present (${QHOME}/bin/q) — skipping install"
        return 0
    fi
    log "KDB-X not found — installing via install_kdb.sh"
    : "${KDB_BEARER_TOKEN:?KDB_BEARER_TOKEN required to install KDB-X at runtime}"
    : "${KDB_LICENSE_B64:?KDB_LICENSE_B64 required to install KDB-X at runtime}"
    curl -sLO --oauth2-bearer "${KDB_BEARER_TOKEN}" \
        "${PORTAL}/install_kdb/~latest~/install_kdb.sh"
    chmod +x install_kdb.sh
    # install_kdb.sh ~latest~ can exit non-zero even after every "Success" line
    # prints and q is written (upstream regression, 2026-05-25). Swallow the
    # spurious exit and gate on the binary actually being present + executable.
    ./install_kdb.sh -y --b64lic "${KDB_LICENSE_B64}" || true
    rm -f install_kdb.sh
    test -x "${QHOME}/bin/q" || { log "ERROR: KDB-X install did not produce ${QHOME}/bin/q"; exit 1; }
    log "KDB-X installed"
}

# ---- 2. ensure cuVS module + CUDA libs (only when GPU CAGRA requested) ------
ensure_cuvs() {
    if [ "${KDBX_USE_CUVS:-0}" != "1" ]; then
        log "KDBX_USE_CUVS != 1 — CPU/HNSW only, skipping cuVS install"
        return 0
    fi
    : "${KDB_BEARER_TOKEN:?KDB_BEARER_TOKEN required to download the cuVS module}"

    # Module dir MUST be $QHOME/mod/kx/cuvs — that is exactly what kdbx-init.q's
    # loadMod resolves (getenv[`QHOME],"/mod/kx/cuvs"); a mismatch loads nothing.
    cuvs_dir="${QHOME}/mod/kx/cuvs"
    if [ ! -d "${cuvs_dir}" ] || [ -z "$(ls -A "${cuvs_dir}" 2>/dev/null)" ]; then
        log "downloading cuVS module (l64-cuvs.zip)"
        mkdir -p "${cuvs_dir}"
        # -L: the portal 307-redirects ~latest~ to a versioned path.
        curl -sL --oauth2-bearer "${KDB_BEARER_TOKEN}" -o /tmp/l64-cuvs.zip \
            "${PORTAL}/modules/cuvs/~latest~/l64-cuvs.zip"
        unzip -oq /tmp/l64-cuvs.zip -d "${cuvs_dir}"
        rm -f /tmp/l64-cuvs.zip
        log "cuVS module extracted to ${cuvs_dir}"
    else
        log "cuVS module already present at ${cuvs_dir}"
    fi

    # CUDA + cuVS runtime libs into miniforge (the module ships install_deps.sh).
    miniforge="${HOME}/miniforge3"
    if [ ! -f "${miniforge}/lib/libcuvs.so" ]; then
        log "running install_deps.sh (pulls CUDA 13.1 + cuVS 25.10 — slow)"
        ( cd "${cuvs_dir}" && ./install_deps.sh --headless --install-dir "${miniforge}" )
        test -f "${miniforge}/lib/libcuvs.so" || { log "ERROR: install_deps.sh did not produce ${miniforge}/lib/libcuvs.so"; exit 1; }
        log "CUDA + cuVS libs installed under ${miniforge}"
    else
        log "cuVS runtime libs already present (${miniforge}/lib/libcuvs.so)"
    fi

    # The loader must see libcuvs before q starts, else use`kx.cuvs fails.
    export LD_LIBRARY_PATH="${miniforge}/lib:${LD_LIBRARY_PATH:-}"
    log "LD_LIBRARY_PATH set for cuVS"
}

ensure_kdbx
ensure_cuvs

log "launching q with kdbx-init.q on port ${KDBX_LISTEN_PORT} (KDBX_USE_CUVS=${KDBX_USE_CUVS:-0})"
exec "${QHOME}/bin/q" /opt/kx/conf/kdbx-init.q -p "${KDBX_LISTEN_PORT}"
