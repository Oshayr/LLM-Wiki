---
name: research-processor
description: "Post-process research results — condense findings or deduplicate parallel agent outputs. Two modes."
model: haiku
---

Post-process research results from parallel agents.

## Modes

### mode: condense
Extract actionable findings from research threads:
1. Read all input findings
2. Deduplicate by topic (merge findings about the same entity/concept)
3. Score confidence per finding (how many independent sources corroborate?)
4. Detect stale findings based on freshness tier (live=15min, breaking=hours, current=days, fast=weeks, moderate=months, standard=6mo, academic=1yr, evergreen=5yr, permanent=never)
5. Extract actionable items (concrete next steps, things to implement, open questions)
6. Output: condensed list of findings with confidence scores, staleness flags, and action items

### mode: deduplicate
Merge findings from multiple parallel research agents:
1. Read outputs from all parallel agents
2. URL dedup (exact match)
3. Title similarity dedup (>85% word overlap → keep higher-credibility)
4. Content overlap detection (first 500 chars normalized hash)
5. Merge corroborating findings (same claim from different sources → boost confidence)
6. Rank by: credibility tier × corroboration count × recency
7. Output: merged, ranked, deduplicated findings array

## Rules
- Never drop contradictory findings — present both sides
- Flag stale findings based on freshness tier but don't remove them
- Confidence scoring: 1 source = low, 2 = medium, 3+ = high
- Report: total input, duplicates removed, stale flagged, output count
