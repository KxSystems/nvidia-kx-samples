#!/bin/bash

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Clear KDB-X volume
echo "Clearing KDB-X volume..."
"$SCRIPT_DIR/clear_kdbx_volume.sh"

# Clear Redis volume
echo "Clearing Redis volume..."
"$SCRIPT_DIR/clear_redis_volume.sh"

# Clear MLflow volume
echo "Clearing MLflow volume..."
"$SCRIPT_DIR/clear_mlflow_volume.sh"

echo "All volumes have been cleared and services restarted."
