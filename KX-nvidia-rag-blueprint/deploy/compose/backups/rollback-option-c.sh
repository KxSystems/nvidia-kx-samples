#!/bin/bash
# Rollback script for Option C optimizations
# Created: 2026-01-08
#
# This script reverts the LLM optimization changes (Option C - Balanced)
# back to the original configuration.
#
# Changes being reverted:
#   1. nims.yaml - Remove NIM performance tuning env vars
#   2. prompt.yaml - Change /think back to /no_think in rag_template
#   3. .env.kdbai-8gpu - Remove RAG optimization settings
#
# Usage: ./rollback-option-c.sh
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_DIR="$(dirname "$SCRIPT_DIR")"
SRC_DIR="$(dirname "$(dirname "$COMPOSE_DIR")")/src/nvidia_rag/rag_server"

echo "=========================================="
echo "Rollback Option C Optimizations"
echo "=========================================="

# Check if backups exist
if [[ ! -f "$SCRIPT_DIR/nims.yaml.backup" ]]; then
    echo "ERROR: Backup file nims.yaml.backup not found!"
    exit 1
fi

if [[ ! -f "$SCRIPT_DIR/prompt.yaml.backup" ]]; then
    echo "ERROR: Backup file prompt.yaml.backup not found!"
    exit 1
fi

if [[ ! -f "$SCRIPT_DIR/.env.kdbai-8gpu.backup" ]]; then
    echo "ERROR: Backup file .env.kdbai-8gpu.backup not found!"
    exit 1
fi

echo "Restoring nims.yaml..."
cp "$SCRIPT_DIR/nims.yaml.backup" "$COMPOSE_DIR/nims.yaml"

echo "Restoring prompt.yaml..."
cp "$SCRIPT_DIR/prompt.yaml.backup" "$SRC_DIR/prompt.yaml"

echo "Restoring .env.kdbai-8gpu..."
cp "$SCRIPT_DIR/.env.kdbai-8gpu.backup" "$COMPOSE_DIR/.env.kdbai-8gpu"

echo ""
echo "=========================================="
echo "Rollback complete!"
echo "=========================================="
echo ""
echo "To apply the rollback, restart your deployment:"
echo "  1. source .env.kdbai-8gpu.local"
echo "  2. ./deploy-kdbai-8gpu.sh down"
echo "  3. ./deploy-kdbai-8gpu.sh up"
echo ""
