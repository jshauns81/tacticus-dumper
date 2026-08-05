# Tacticus Strategy Engine

## Mission

Turn Tacticus account data into clear, reproducible decisions about who to build, which teams to form, where to spend scarce resources, and what opportunity cost each choice creates.

## Core questions

The engine must answer:

- What should I build now?
- Why is that better than the alternatives?
- What team or game mode does it improve?
- What resources should I spend or preserve?
- Where should I stop investing?
- What changed since the previous account snapshot?

## Product principles

1. **Deterministic recommendations.** Rules and data produce recommendations. An LLM may explain them, but does not invent them.
2. **Explain every result.** A recommendation must include evidence, assumptions, tradeoffs, and a stopping point.
3. **Account-specific advice.** Generic tier lists are inputs at most, never the output.
4. **No hidden score.** Every score component must be inspectable.
5. **Versioned knowledge.** Patch-sensitive facts and evaluations carry a source and effective date.
6. **Small active queue.** Default output recommends no more than three concurrent projects.
7. **Protect scarce resources.** Badges, orbs, XP books, energy, shards, and equipment are first-class constraints.
8. **Preserve raw facts.** Imported account data remains separate from game knowledge and derived recommendations.

## Non-goals for the first release

- Mission walkthroughs
- Automated gameplay
- Unverifiable damage simulation
- LLM-only recommendations
- A universal S-through-F tier list

## First useful release

Given the latest saved player dump, return:

- a factual account summary
- three recommended projects
- a target and stopping point for each project
- the teams or modes affected
- protected resources and paused investments
- evidence and assumptions for every recommendation
