#!/bin/bash

# Stop any running KDB-X containers
echo "Stopping KDB-X containers..."
docker compose -f ./deploy/docker-compose.yaml stop kdbx

# Remove the KDB-X volume
echo "Removing KDB-X volume..."
docker compose -f ./deploy/docker-compose.yaml down -v kdbx

# Start KDB-X again
echo "Starting KDB-X..."
docker compose -f ./deploy/docker-compose.yaml up -d kdbx

echo "KDB-X volume cleared and container restarted."
