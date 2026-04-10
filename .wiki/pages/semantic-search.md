---
title: Semantic Search
type: concept
confidence: medium
sources:
  - https://www.sbert.net/
  - https://arxiv.org/abs/1908.10084
related:
  - vector-databases
  - retrieval-augmented-generation
  - embedding-models
tags: [search, ai, nlp, embeddings]
freshness_tier: moderate
created: 2025-04-01
updated: 2025-11-01
---
# Semantic Search

Semantic search uses [[embedding-models|embeddings]] to find results based on meaning rather than keyword matching.

## How It Works

1. Documents are converted to vector embeddings
2. Query is converted to a vector embedding
3. Nearest neighbor search finds most similar documents
4. Results are ranked by cosine similarity or dot product

## Advantages Over Keyword Search

- Understands synonyms and paraphrases
- Handles multilingual queries
- Captures conceptual relationships
- Works with short or ambiguous queries

## Hybrid Search

Combines semantic and keyword search for best results:
- Dense retrieval (embeddings) for meaning
- Sparse retrieval (BM25) for exact matches
- Reciprocal Rank Fusion (RRF) to merge rankings

See also: [[vector-databases]], [[retrieval-augmented-generation]], [[embedding-models]]
