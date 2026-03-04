#!/bin/bash

# Clear KDB-X data in Kubernetes

set -e

# Configuration
NAMESPACE="${NAMESPACE:-nv-nvidia-blueprint-data-flywheel}"

echo "Clearing KDB-X data in namespace: $NAMESPACE"

# Check if namespace exists
if ! kubectl get namespace "$NAMESPACE" &>/dev/null; then
    echo "Namespace '$NAMESPACE' does not exist"
    exit 1
fi

# Retrieve the KDB-X pod name
KDBX_POD=$(kubectl get pods -l app=df-kdbx-deployment -n "$NAMESPACE" -o jsonpath='{.items[0].metadata.name}')

if [ -z "$KDBX_POD" ]; then
    echo "KDB-X pod not found. It might not be deployed yet."
    exit 1
fi

# Delete all rows from all flywheel tables via q IPC
# This sends a q expression that clears each table
echo "Clearing all flywheel tables..."
kubectl exec "$KDBX_POD" -n "$NAMESPACE" -- q -p 8082 -e '{
  tables: `flywheel_runs`nims`evaluations`customizations`llm_judge_runs`flywheel_logs`flywheel_embeddings;
  {[t] if[t in tables[]; delete from t]} each tables;
  }'

echo "KDB-X data cleared successfully!"
