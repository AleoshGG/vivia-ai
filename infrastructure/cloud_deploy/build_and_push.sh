#!/bin/bash
# Placeholder script for building and pushing Docker images to a registry

echo "Building Docker images..."
# docker build -t vivia/anomaly-api:latest -f infrastructure/docker/anomaly_api.Dockerfile .
# docker build -t vivia/clustering-batch:latest -f infrastructure/docker/clustering_batch.Dockerfile .
# docker build -t vivia/llm-local:latest -f infrastructure/docker/llm_local.Dockerfile .

echo "Images built. Pushing to registry..."
# docker push vivia/anomaly-api:latest
# docker push vivia/clustering-batch:latest
# docker push vivia/llm-local:latest

echo "Done."
