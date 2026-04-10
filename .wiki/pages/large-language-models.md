---
title: Large Language Models
type: concept
confidence: high
sources:
  - https://arxiv.org/abs/2303.08774
  - https://arxiv.org/abs/2302.13971
  - https://arxiv.org/abs/2307.09288
related:
  - retrieval-augmented-generation
  - prompt-engineering
  - transformer-architecture
tags: [ai, llm, nlp, deep-learning]
freshness_tier: fast
created: 2025-01-15
updated: 2026-04-01
---
# Large Language Models

Large language models (LLMs) are neural networks trained on massive text corpora to understand and generate human language.

## Key Models

- **GPT-4** (OpenAI) — multimodal, strong reasoning
- **Claude** (Anthropic) — safety-focused, long context
- **Llama** (Meta) — open-weight, community-driven
- **Gemini** (Google) — multimodal, integrated with Google services
- **Mistral** — efficient open-source models

## Capabilities

- Text generation and completion
- Code generation and debugging
- Reasoning and analysis
- Tool use and function calling
- Multi-turn conversation

## Training Approach

1. **Pre-training** on large text corpora (next-token prediction)
2. **Supervised fine-tuning** (SFT) on curated examples
3. **RLHF/DPO** alignment for helpfulness and safety

## Context Windows

Modern LLMs support increasingly large context windows:
- GPT-4: 128K tokens
- Claude: 200K tokens  
- Gemini: 1M+ tokens

See also: [[retrieval-augmented-generation]], [[prompt-engineering]], [[transformer-architecture]]
