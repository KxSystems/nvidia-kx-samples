#!/bin/bash

# Load .env file from home directory if it exists
if [[ -f ~/.env ]]; then
  echo "Loading environment from ~/.env"
  export $(grep -v '^#' ~/.env | grep -v '^$' | xargs)
fi

docker compose -f ./deploy/docker-compose.yaml down && docker compose -f ./deploy/docker-compose.yaml up -d --build
