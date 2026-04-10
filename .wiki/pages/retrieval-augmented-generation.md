---
title: Retrieval-Augmented Generation
type: concept
confidence: high
sources:
  - https://arxiv.org/abs/2005.11401
  - https://arxiv.org/abs/2312.10997
  - https://docs.langchain.com/docs/use-cases/question-answering
related:
  - vector-databases
  - large-language-models
  - semantic-search
tags: [ai, rag, nlp, retrieval]
freshness_tier: fast
created: 2025-06-01
updated: 2026-03-15
---
# Retrieval-Augmented Generation

Retrieval-Augmented Generation (RAG) combines information retrieval with text generation to produce accurate, grounded responses.

## Architecture

RAG systems have three core components:

1. **Document Store** — a [[vector-databases|vector database]] or traditional index holding the knowledge base
2. **Retriever** — dense (embedding-based) or sparse (BM25/TF-IDF) search to find relevant documents
3. **Generator** — typically a [[large-language-models|large language model]] that synthesizes retrieved context into answers

## How It Works

1. User submits a query
2. Retriever searches the document store for relevant passages
3. Top-k passages are concatenated with the query as context
4. The LLM generates a response grounded in the retrieved evidence

## Benefits

- Reduces hallucination by grounding in evidence
- Enables knowledge updates without retraining
- Provides source attribution and citations
- Works with domain-specific knowledge bases

## Popular Implementations

- **LangChain** — modular RAG pipeline with extensive integrations
- **LlamaIndex** — data framework for LLM applications
- **Haystack** — end-to-end NLP framework by deepset

## Limitations

- Retrieval quality bottlenecks generation quality
- Context window limits constrain how much can be retrieved
- Latency overhead from the retrieval step

See also: [[semantic-search]], [[embedding-models]], [[prompt-engineering]]
