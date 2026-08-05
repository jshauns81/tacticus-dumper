# Architecture

## System boundaries

The application is divided into four layers.

```text
Tacticus API and saved dumps
          |
          v
Account ingestion and normalization
          |
          +-------------------+
          |                   |
          v                   v
Versioned game knowledge   Account history
          |                   |
          +---------+---------+
                    v
             Strategy engine
                    |
                    v
       Structured recommendations API
                    |
                    v
        Web UI and optional LLM explanation
```

## 1. Account ingestion

Responsibilities:

- load the newest or selected player dump
- validate the supported JSON shape
- normalize unstable API field names into internal models
- retain unknown fields when practical for later schema discovery
- never attach strategic opinions to imported facts

Current implementation lives in `advisor/parser.py`.

## 2. Game knowledge

Version-controlled data describes characters, abilities, mechanics, game modes, teams, encounters, resource costs, relationships, and strategic evaluations.

Knowledge entries must include:

- stable identifier
- schema version
- game version or effective date
- source type
- confidence
- factual attributes
- separately identified evaluations

Factual fields and strategic evaluations must not be silently mixed.

## 3. Strategy engine

The engine consumes normalized account state, game knowledge, user priorities, and resource constraints.

It produces candidate actions, scores each action by explicit components, compares alternatives, and selects a bounded build queue.

The engine must be pure where practical: identical inputs should produce identical outputs.

## 4. Recommendation contract

Each recommendation contains:

- action
- subject
- current state
- target state
- stopping point
- affected teams and modes
- score breakdown
- evidence
- assumptions
- opportunity cost
- confidence
- next action after completion

## 5. Presentation

The Flask application exposes structured JSON endpoints and renders them for mobile use. UI code must not contain scoring rules.

An optional LLM layer may translate a structured recommendation into natural language. It must receive the evidence and score breakdown and may not alter the selected action.

## Storage

- Raw account dumps remain under `/data/dumps`.
- Configuration remains under `/data/config.json`.
- Knowledge ships with the application image and is version controlled.
- Generated recommendations may later be stored under `/data/advisor`, but are currently computed on demand.

## Security

- Never commit API keys, passwords, live player dumps, or guild-private data.
- Tests use sanitized fixtures.
- Advisor endpoints inherit the application's existing authentication boundary.

## Change discipline

- `master` remains deployable.
- Feature work occurs on branches.
- Recommendation behavior changes require tests showing the intended score or ordering change.
- Schema changes require a schema-version increment and migration notes.
