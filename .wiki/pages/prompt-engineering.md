---
title: Prompt Engineering
type: concept
confidence: medium
sources:
  - https://www.promptingguide.ai/
  - https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering
related:
  - large-language-models
  - retrieval-augmented-generation
tags: [ai, prompting, llm]
freshness_tier: moderate
created: 2025-03-01
updated: 2026-01-15
---
# Prompt Engineering

Prompt engineering is the practice of designing effective instructions for [[large-language-models]] to elicit desired outputs.

## Techniques

### Zero-Shot
Providing instructions without examples.

### Few-Shot
Including examples of desired input-output pairs in the prompt.

### Chain-of-Thought (CoT)
Encouraging step-by-step reasoning before the final answer.

### System Prompts
Setting behavioral context and constraints for the model.

## Best Practices

- Be specific and explicit about desired output format
- Provide examples when possible
- Break complex tasks into subtasks
- Use XML tags for structure (especially with Claude)
- Iterate and test with different phrasings

## Anti-Patterns

- Vague or ambiguous instructions
- Overloading a single prompt with too many tasks
- Not specifying output constraints

See also: [[large-language-models]], [[retrieval-augmented-generation]]
