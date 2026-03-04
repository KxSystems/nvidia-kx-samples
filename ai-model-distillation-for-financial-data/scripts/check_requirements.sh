#!/bin/bash
set -e

# Generate temporary requirements file
temp_req=$(mktemp)
uv sync --no-dev
uv pip freeze > "$temp_req"

# Compare with existing requirements.txt
if ! cmp -s "$temp_req" requirements.txt; then
    echo "Error: requirements.txt is out of sync with pyproject.toml"
    echo "Please run 'uv sync --no-dev && uv pip freeze > requirements.txt' to update"
    diff "$temp_req" requirements.txt || true
    rm "$temp_req"
    exit 1
fi

rm "$temp_req"
echo "requirements.txt is up to date"
