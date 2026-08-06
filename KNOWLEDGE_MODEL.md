# Knowledge Model

## Data categories

The engine keeps three categories separate:

1. Account facts imported from player dumps
2. Game facts describing Tacticus entities and mechanics
3. Strategic evaluations describing usefulness under stated assumptions

Strategic evaluations must never be presented as official game facts.

## Core entities

### Character

A character record includes a stable ID, name, faction, alliance, abilities, traits, damage profiles, movement, summons, campaign requirements, and knowledge version.

Optional evaluation fields include mode values, useful breakpoints, team roles, synergies, encounter constraints, evidence, and confidence.

### Ability

An ability record includes its stable ID, display name, active or passive type, targets, mechanics, created effects, consumed effects, scaling dimensions, and breakpoint notes.

### Effect

Effects model mechanics such as buffs, debuffs, marks, summons, overwatch, healing, suppression, and damage amplification. Effects record producers, beneficiaries, stacking rules, duration, and scope.

### Game mode

A mode records team-size rules, reuse or lockout rules, restrictions, scoring objectives, and resources consumed.

### Encounter

Guild Raid bosses, event tracks, and constrained battles share an encounter model. An encounter records its mode, restrictions, phases, mechanics, counters, scoring considerations, and effective game version.

### Team archetype

An archetype describes required roles and relationships rather than only five character names. It records required and optional roles, enabling mechanics, exclusions, and candidate characters per role.

### Resource

A resource records category, rarity, applicable factions or alliances, and acquisition constraints.

### Investment action

An investment action is a decision candidate, such as raising rank, leveling an ability, ascending rarity, upgrading equipment, or farming an unlock. It records current state, target state, estimated costs, prerequisites, and affected capabilities.

## Relationship vocabulary

Controlled relationship verbs include:

- belongs to
- requires
- produces
- consumes
- benefits from
- amplifies
- enables
- counters
- restricted by
- eligible for
- substitutes for
- competes with

A relationship may carry mode scope, encounter scope, strength, confidence, effective version, source references, and notes.

## Evaluations

Mode evaluations use a normalized zero-to-ten scale only within the named mode and conditions. Every evaluation includes confidence, evidence, effective date, and source type.

A breakpoint identifies a useful stopping point, the reason it matters, affected modes, conditions, evidence, and confidence.

## Recommendation contract

A recommendation contains:

- generated identifier
- action and subject
- current and target state
- explicit stopping point
- priority and confidence
- total score and component breakdown
- affected modes and teams
- evidence
- assumptions
- opportunity costs
- the next candidate after completion

## Versioning

Every knowledge document includes a schema version, knowledge version, effective date, last-reviewed date, and sources.

Versioned JSON Schemas live under `knowledge/schema/`. Supported document collections are `characters`, `abilities`, `effects`, `modes`, `encounters`, and `team_archetypes`; the repository validator rejects JSON placed outside those collection directories.

Source types include official game data, official patch notes, observed player data, controlled tests, community consensus, and expert judgment. Confidence is reduced when an entry depends primarily on community consensus or judgment.
