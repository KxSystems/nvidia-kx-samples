#!/bin/bash

# Load .env file from home directory if it exists
if [[ -f ~/.env ]]; then
  echo "Loading environment from ~/.env"
  export $(grep -v '^#' ~/.env | grep -v '^$' | xargs)
fi

# Run w/ dev docker compose so we get the UIs (Flower for Celery monitoring)
docker compose -f ./deploy/docker-compose.yaml -f ./deploy/docker-compose.dev.yaml down && \
  docker compose -f ./deploy/docker-compose.yaml -f ./deploy/docker-compose.dev.yaml up --build
