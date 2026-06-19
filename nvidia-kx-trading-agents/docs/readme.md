# AI Trader Agents Blueprint Documentation

Welcome to the **AI Trader Agents** documentation (a KX variant of the NVIDIA AI-Q
Research Assistant blueprint). AI Trader Agents is an on-premise, multi-agent system for
financial research: an orchestrator plans research queries, routes each to the best-fit
source agent (KDB-X market data, documents, web, news, fundamentals, filings, macro),
judges and reroutes on relevance, then writes a citation-backed report. The following
sections are covered:

## Concepts & Architecture
- [What's Different from AI-Q](/docs/whats-different-from-aiq.md) - How this variant extends the upstream blueprint
- [REST API Reference](/docs/rest-api.md) - All endpoints, including `/source_agents`, `/settings/kdb-docs`, `/settings/kdb-tables`, and `/sec/ingest`
- [KDB-X Document Agent (`kdb_docs`)](/docs/kdb-docs-agent.md) - Vector search over documents/filings in KDB-X

## Getting Started
- [Get Started](/docs/get-started/)
    - [Using the NVIDIA API](/notebooks/get_started_nvidia_api.ipynb)
    - [Using Docker Compose](/docs/get-started/get-started-docker-compose.md)
    - [Using a Helm chart](/docs/get-started/get-started-helm.md)
    - [Using hosted NVIDIA NIM microservices](/docs/get-started/get-started-hosted-nims.md)

## KDB-X Integration
- [KDB-X Deployment Guide](/docs/kxta-deployment-guide.md) - Complete guide for deploying with KDB-X financial data integration
- [Configuration Reference](/docs/configuration-reference.md) - All configurable environment variables and Helm values

## Development & Operations
- [Local Development Guide](/docs/local-development.md)
- [Phoenix Tracing Configuration for Docker Deployment](/docs/phoenix-tracing.md)
- [Evaluation](/docs/evaluate.md)
- [Security Testing Guide](/docs/security-testing.md)
- [Frequently Asked Questions](/docs/FAQ.md)
- [Troubleshooting](/docs/troubleshooting.md)
