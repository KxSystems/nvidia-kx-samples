#!/bin/bash
# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Build script for KDB-X Docker image
# This script builds a prebuilt KDB-X image that can be used instead of runtime installation.
#
# SECURITY: This script uses Docker BuildKit secrets to pass credentials securely.
# Credentials are NOT stored in image layers and cannot be extracted via `docker history`.
# The resulting image can be safely pushed to any registry (public or private).
#
# Prerequisites:
# - Docker installed with BuildKit support (Docker 18.09+)
# - KX Portal bearer token (from https://portal.kx.com)
# - KDB-X license (base64 encoded)
#
# Usage:
#   ./build-kdbx-image.sh [OPTIONS]
#
# Options:
#   --bearer-token TOKEN    KX Portal OAuth bearer token
#   --license-b64 LICENSE   Base64-encoded KDB-X license
#   --repository REPO       Docker repository for the image (default: kdb-x)
#   --tag TAG               Image tag (default: 1.3.0)
#   --push                  Push image after building
#   --platform PLATFORM     Target platform (default: linux/amd64)
#
# Environment variables (alternative to command-line options):
#   KDB_BEARER_TOKEN        KX Portal OAuth bearer token
#   KDB_B64_LICENSE         Base64-encoded KDB-X license
#   KDB_IMAGE_REPOSITORY    Docker repository
#   KDB_IMAGE_TAG           Image tag

set -e

# Default values
REPOSITORY="${KDB_IMAGE_REPOSITORY:-kdb-x}"
TAG="${KDB_IMAGE_TAG:-1.3.0}"
BEARER_TOKEN="${KDB_BEARER_TOKEN:-}"
LICENSE_B64="${KDB_B64_LICENSE:-}"
PUSH=false
PLATFORM="linux/amd64"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --bearer-token)
            BEARER_TOKEN="$2"
            shift 2
            ;;
        --license-b64)
            LICENSE_B64="$2"
            shift 2
            ;;
        --repository)
            REPOSITORY="$2"
            shift 2
            ;;
        --tag)
            TAG="$2"
            shift 2
            ;;
        --push)
            PUSH=true
            shift
            ;;
        --platform)
            PLATFORM="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Build a prebuilt KDB-X Docker image."
            echo ""
            echo "Options:"
            echo "  --bearer-token TOKEN    KX Portal OAuth bearer token"
            echo "  --license-b64 LICENSE   Base64-encoded KDB-X license"
            echo "  --repository REPO       Docker repository (default: kdb-x)"
            echo "  --tag TAG               Image tag (default: 1.3.0)"
            echo "  --push                  Push image after building"
            echo "  --platform PLATFORM     Target platform (default: linux/amd64)"
            echo "  -h, --help              Show this help message"
            echo ""
            echo "Environment variables:"
            echo "  KDB_BEARER_TOKEN        KX Portal OAuth bearer token"
            echo "  KDB_B64_LICENSE         Base64-encoded KDB-X license"
            echo "  KDB_IMAGE_REPOSITORY    Docker repository"
            echo "  KDB_IMAGE_TAG           Image tag"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Validate required parameters
if [[ -z "$BEARER_TOKEN" ]]; then
    echo "Error: Bearer token is required."
    echo "Provide via --bearer-token or KDB_BEARER_TOKEN environment variable."
    echo "Get your token from https://portal.kx.com"
    exit 1
fi

if [[ -z "$LICENSE_B64" ]]; then
    echo "Error: License is required."
    echo "Provide via --license-b64 or KDB_B64_LICENSE environment variable."
    echo "To get the base64 license: cat kc.lic | base64"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKERFILE_PATH="${SCRIPT_DIR}/../Dockerfile.kdbx"

if [[ ! -f "$DOCKERFILE_PATH" ]]; then
    echo "Error: Dockerfile.kdbx not found at $DOCKERFILE_PATH"
    exit 1
fi

echo "============================================"
echo "Building KDB-X Docker Image"
echo "============================================"
echo "Repository: $REPOSITORY"
echo "Tag: $TAG"
echo "Platform: $PLATFORM"
echo "Dockerfile: $DOCKERFILE_PATH"
echo "Using: Docker BuildKit secrets (credentials not stored in image)"
echo "============================================"

# Export credentials for BuildKit secret mounting
export KDB_BEARER_TOKEN="$BEARER_TOKEN"
export KDB_B64_LICENSE="$LICENSE_B64"

# Build the image using BuildKit secrets
# Secrets are mounted temporarily during build and NOT stored in image layers
DOCKER_BUILDKIT=1 docker build \
    --platform "$PLATFORM" \
    --secret id=bearer_token,env=KDB_BEARER_TOKEN \
    --secret id=license_b64,env=KDB_B64_LICENSE \
    -t "${REPOSITORY}:${TAG}" \
    -f "$DOCKERFILE_PATH" \
    "${SCRIPT_DIR}/.."

echo ""
echo "✓ Image built successfully: ${REPOSITORY}:${TAG}"

# Push if requested
if [[ "$PUSH" == "true" ]]; then
    echo ""
    echo "Pushing image to registry..."
    docker push "${REPOSITORY}:${TAG}"
    echo "✓ Image pushed successfully"
fi

echo ""
echo "============================================"
echo "Next steps:"
echo "============================================"
echo ""
echo "Note: This image was built using Docker BuildKit secrets."
echo "      Credentials are NOT stored in image layers and cannot be"
echo "      extracted via 'docker history'. Safe to push to any registry."
echo ""
echo "1. Push to your registry:"
echo ""
echo "   docker push ${REPOSITORY}:${TAG}"
echo ""
echo "2. To use this prebuilt image in your Helm deployment, update values.yaml:"
echo ""
echo "   kdbx:"
echo "     enabled: true"
echo "     installMode: \"prebuilt\""
echo "     image:"
echo "       repository: \"${REPOSITORY}\""
echo "       tag: \"${TAG}\""
echo ""
echo "3. Deploy with Helm:"
echo ""
echo "   helm upgrade --install kdb-mcp ./kdb-x-mcp-server -f your-values.yaml"
echo ""
