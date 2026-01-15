#!/bin/bash
# Build and deploy the custom AIRA frontend to Kubernetes

set -e

NAMESPACE="${NAMESPACE:-aiq}"
IMAGE_NAME="${IMAGE_NAME:-aira-custom-frontend}"
IMAGE_TAG="${IMAGE_TAG:-latest}"

echo "Building Docker image..."
docker build -t ${IMAGE_NAME}:${IMAGE_TAG} .

# If using a remote registry, push the image
if [ -n "$REGISTRY" ]; then
    echo "Pushing to registry: ${REGISTRY}..."
    docker tag ${IMAGE_NAME}:${IMAGE_TAG} ${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}
    docker push ${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}

    # Update deployment to use registry image
    sed -i.bak "s|image: ${IMAGE_NAME}:${IMAGE_TAG}|image: ${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}|g" k8s/deployment.yaml
fi

echo "Deploying to Kubernetes namespace: ${NAMESPACE}..."
kubectl apply -f k8s/deployment.yaml -n ${NAMESPACE}

echo "Waiting for deployment to be ready..."
kubectl rollout status deployment/aira-custom-frontend -n ${NAMESPACE} --timeout=120s

echo ""
echo "Deployment complete!"
echo ""
echo "To access the frontend, run:"
echo "  kubectl port-forward -n ${NAMESPACE} svc/aira-custom-frontend 3000:3000"
echo ""
echo "Then open: http://localhost:3000"
