---
name: research-loop
description: "Autonomous iterative research loop — hypothesis, search, ingest, evaluate, keep/discard via checkpoint. Max 3 iterations."
model: sonnet
---

Run an autonomous research loop: generate hypotheses, search, ingest to wiki, evaluate quality, keep or discard via checkpoint. Max 3 iterations by default. Stops on metric plateau or question saturation.

## Setup

Resolve `.wiki/` from plugin install scope.
Read the research program (provided by caller): topic, seed questions, search strategy.

## Iteration Loop

### 1. Checkpoint Baseline
Create a checkpoint of current `.wiki/` state as a rollback point.

### 2. Generate Hypotheses
From the program's seed questions and any remaining open questions from `.wiki/overview.md`:
- Pick the 2-3 most promising questions for this iteration
- Generate search queries targeting these specific questions

### 3. Search
Launch `search-orchestrator` with the queries. Receive ranked, deduplicated results.

### 4. Ingest
For each top result: launch `wiki-writer` (mode: ingest) to compile into wiki pages.

### 5. Evaluate
After ingestion, assess:
- **Questions answered**: how many of the iteration's questions got substantive answers?
- **New questions discovered**: did the results open new interesting directions?
- **Confidence changes**: did any pages get upgraded/downgraded?
- **Contradiction count**: any new contradictions flagged?

### 6. Keep or Discard
- If quality metrics improved (questions answered > 0, net confidence up): **keep** (commit changes)
- If no meaningful progress or quality degraded: **discard** (rollback to baseline)
- If metric plateau (same scores as last iteration): **stop** — further iterations won't help

### 7. Continue or Stop
- If iteration < max (3): continue to next iteration with updated questions
- If question saturation (all seed questions answered): stop early
- If metric plateau: stop early

## Output

After the loop completes:
- Write a deep-dive summary page to `.wiki/pages/<topic>-deep-dive.md`
- Include: questions answered, wiki coverage assessment, confidence levels, open questions remaining
- Update `.wiki/log.md` with iteration summary

## Rules
- Maximum 3 iterations by default (caller can override)
- Always create checkpoint baseline before each iteration
- Discard iterations that don't improve quality
- Stop early if questions are saturated or metrics plateau
- Report: iterations run, questions answered, pages added/updated, final confidence
