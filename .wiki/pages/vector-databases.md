---
title: Vector Databases
type: concept
confidence: medium
sources:
  - https://www.pinecone.io/learn/vector-database/
  - https://milvus.io/docs
related:
  - retrieval-augmented-generation
  - semantic-search
  - embedding-models
tags: [databases, vectors, ai, search]
freshness_tier: fast
created: 2025-05-01
updated: 2026-02-01
---
# Vector Databases

Vector databases store and index high-dimensional vectors for efficient similarity search, powering [[retrieval-augmented-generation|RAG]] and [[semantic-search]] systems.

## Key Features

- **Approximate Nearest Neighbor (ANN)** search for fast retrieval
- **HNSW, IVF, PQ** indexing algorithms
- **Metadata filtering** for hybrid search (vector + attribute filters)
- **Real-time ingestion** for streaming updates

## Popular Options

| Database | Type | Key Feature |
|----------|------|-------------|
| Pinecone | Managed | Serverless, auto-scaling |
| Weaviate | Open-source | GraphQL API, modules |
| Milvus | Open-source | GPU-accelerated, distributed |
| Qdrant | Open-source | Rust-based, fast filtering |
| ChromaDB | Open-source | Python-native, lightweight |
| pgvector | Extension | PostgreSQL integration |

## Use Cases

- [[retrieval-augmented-generation|RAG]] document retrieval
- Image/audio similarity search
- Recommendation systems
- Anomaly detection

See also: [[embedding-models]], [[large-language-models]]
