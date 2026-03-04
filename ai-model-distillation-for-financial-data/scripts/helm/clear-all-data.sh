#!/bin/bash

# Clear All Data in Kubernetes
# This script clears data for all services in the Data Flywheel deployment

set -e

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Configuration
NAMESPACE="${NAMESPACE:-nv-nvidia-blueprint-data-flywheel}"

echo "🔄 Starting to clear all data in namespace: $NAMESPACE"

# Check if namespace exists
if ! kubectl get namespace "$NAMESPACE" &>/dev/null; then
    echo "❌ Namespace '$NAMESPACE' does not exist"
    exit 1
fi

# Clear KDB-X data
echo ""
echo "Clearing KDB-X data..."
export NAMESPACE="$NAMESPACE"
"$SCRIPT_DIR/clear-kdbx-data.sh"

# Clear Redis data
echo ""
echo "Clearing Redis data..."
export NAMESPACE="$NAMESPACE"
"$SCRIPT_DIR/clear-redis-data.sh"

# Clear MLflow data (if enabled)
echo ""
echo "📊 Clearing MLflow data..."
export NAMESPACE="$NAMESPACE"
"$SCRIPT_DIR/clear-mlflow-data.sh"

echo ""
echo "👉 All data have been cleared successfully!"
echo ""
