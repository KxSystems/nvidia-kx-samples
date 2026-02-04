#!/bin/bash
# ==========================
# KDB.AI RAG Deployment Script
# ==========================
#
# EXAMPLE CONFIGURATION: 8x RTX PRO 6000 Blackwell (96GB each)
#
# NOTE: This script is an example showing how to configure GPU assignments
# for a specific hardware setup. You should customize the GPU IDs and
# assignments in .env.kdbai-8gpu.local based on YOUR actual hardware:
#   - Number of GPUs available
#   - GPU memory per device
#   - Which services to run on which GPUs
#
# See .env.kdbai-8gpu for the GPU assignment template.
# ==========================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}KDB.AI RAG Deployment${NC}"
echo -e "${GREEN}========================================${NC}"

# Check for local env file
if [ ! -f ".env.kdbai-8gpu.local" ]; then
    echo -e "${YELLOW}Creating .env.kdbai-8gpu.local from template...${NC}"
    cp .env.kdbai-8gpu .env.kdbai-8gpu.local
    echo -e "${RED}Please edit .env.kdbai-8gpu.local with your credentials:${NC}"
    echo "  - NGC_API_KEY"
    echo "  - KDBAI_REGISTRY_EMAIL"
    echo "  - KDBAI_REGISTRY_TOKEN"
    echo "  - KDB_LICENSE_B64"
    exit 1
fi

# Source the environment
source .env.kdbai-8gpu.local

# Validate required variables
if [ -z "$NGC_API_KEY" ] || [ "$NGC_API_KEY" = "your-ngc-api-key" ]; then
    echo -e "${RED}ERROR: NGC_API_KEY not set in .env.kdbai-8gpu.local${NC}"
    exit 1
fi

if [ -z "$KDBAI_REGISTRY_TOKEN" ] || [ "$KDBAI_REGISTRY_TOKEN" = "your-bearer-token" ]; then
    echo -e "${RED}ERROR: KDBAI_REGISTRY_TOKEN not set in .env.kdbai-8gpu.local${NC}"
    exit 1
fi

if [ -z "$KDB_LICENSE_B64" ] || [ "$KDB_LICENSE_B64" = "your-kdb-license-b64-string" ]; then
    echo -e "${RED}ERROR: KDB_LICENSE_B64 not set in .env.kdbai-8gpu.local${NC}"
    exit 1
fi

# Create required directories
echo -e "${GREEN}Creating directories...${NC}"
mkdir -p volumes/kdbai
mkdir -p "${MODEL_DIRECTORY:-$HOME/.cache/nim}"

# Fix KDB.AI volume permissions (runs as user 65534/nobody)
echo -e "${GREEN}Setting KDB.AI volume permissions...${NC}"
sudo chown -R 65534:65534 volumes/kdbai 2>/dev/null || chown -R 65534:65534 volumes/kdbai 2>/dev/null || true
chmod -R 777 volumes/kdbai 2>/dev/null || true

# Login to NGC
echo -e "${GREEN}Logging into NGC...${NC}"
echo "$NGC_API_KEY" | docker login nvcr.io -u '$oauthtoken' --password-stdin

# Login to KX Docker Registry (for KDB.AI)
echo -e "${GREEN}Logging into KX Docker Registry...${NC}"
echo "$KDBAI_REGISTRY_TOKEN" | docker login portal.dl.kx.com -u "$KDBAI_REGISTRY_EMAIL" --password-stdin

# Parse command
COMMAND=${1:-up}

case $COMMAND in
    up)
        echo -e "${GREEN}Starting KDB.AI RAG stack...${NC}"
        echo -e "${YELLOW}GPU Assignment:${NC}"
        echo "  GPU 0,1: LLM (49B - tensor parallelism)"
        echo "  GPU 2: Embedding + Reranker"
        echo "  GPU 3: Page Elements"
        echo "  GPU 4: Graphic Elements"
        echo "  GPU 5: Table Structure + PaddleOCR"
        echo "  GPU 6: KDB.AI"
        echo "  GPU 7: VLM (optional)"

        docker compose \
            -f vectordb.yaml \
            -f nims.yaml \
            -f docker-compose-rag-server.yaml \
            -f docker-compose-ingestor-server.yaml \
            --profile kdbai \
            --profile rag \
            --profile ingest \
            --profile minio \
            up -d

        echo -e "${GREEN}========================================${NC}"
        echo -e "${GREEN}Deployment started!${NC}"
        echo -e "${GREEN}========================================${NC}"
        echo ""
        echo "Services will take 5-15 minutes to initialize (downloading models)."
        echo ""
        echo "Check status:  ./deploy-kdbai-8gpu.sh ps"
        echo "View logs:     ./deploy-kdbai-8gpu.sh logs"
        echo ""
        echo "Endpoints (after startup):"
        echo "  - Frontend:    http://localhost:8090"
        echo "  - RAG Server:  http://localhost:8081"
        echo "  - KDB.AI:      http://localhost:8084"
        ;;

    down)
        echo -e "${YELLOW}Stopping KDB.AI RAG stack...${NC}"
        docker compose \
            -f vectordb.yaml \
            -f nims.yaml \
            -f docker-compose-rag-server.yaml \
            -f docker-compose-ingestor-server.yaml \
            --profile kdbai \
            --profile rag \
            --profile ingest \
            --profile minio \
            down
        echo -e "${GREEN}Stack stopped.${NC}"
        ;;

    logs)
        docker compose \
            -f vectordb.yaml \
            -f nims.yaml \
            -f docker-compose-rag-server.yaml \
            -f docker-compose-ingestor-server.yaml \
            --profile kdbai \
            --profile rag \
            --profile ingest \
            --profile minio \
            logs -f
        ;;

    ps)
        docker compose \
            -f vectordb.yaml \
            -f nims.yaml \
            -f docker-compose-rag-server.yaml \
            -f docker-compose-ingestor-server.yaml \
            --profile kdbai \
            --profile rag \
            --profile ingest \
            --profile minio \
            ps
        ;;

    gpu)
        echo -e "${GREEN}GPU Status:${NC}"
        nvidia-smi
        ;;

    *)
        echo "Usage: $0 {up|down|logs|ps|gpu}"
        echo ""
        echo "Commands:"
        echo "  up    - Start the KDB.AI RAG stack"
        echo "  down  - Stop the stack"
        echo "  logs  - View logs"
        echo "  ps    - Show container status"
        echo "  gpu   - Show GPU status"
        exit 1
        ;;
esac
