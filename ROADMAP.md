# Roadmap

## Milestone 0: Deployment baseline

Status: complete enough for feature development.

- Dockerized Flask application
- persistent named volume
- health check
- GHCR workflow
- Dockhand deployment documentation

## Milestone 1: Account normalization

Status: complete.

- load latest player dump
- normalize character progression and abilities
- preserve source filename and import timestamp
- validate against a full real-world player dump
- expose a factual summary API
- add error responses for missing or malformed dumps

Exit condition: a saved player dump can be converted into a stable internal account model and returned through an authenticated API endpoint.

## Milestone 2: Knowledge foundation

Status: complete.

- add machine-readable schemas
- add version and source metadata
- define schemas for characters, abilities, effects, modes, encounters, and team archetypes
- seed a small Guild Raid-focused character set
- validate every knowledge file and typed relationship in CI

Exit condition: the application can load and validate versioned knowledge without strategic code depending on character names.

## Milestone 3: Candidate actions

Status: in progress. Ability-level candidates are supported; coin sufficiency remains
explicitly unknown because the Player API export does not report coin inventory.

- generate possible rank, ability, ascension, equipment, and unlock actions
- calculate prerequisites and resource costs
- filter impossible actions
- expose candidate actions through an API

Exit condition: the engine can describe what the account could do next without yet ranking those choices.

## Milestone 4: Guild Raid scoring

- define Guild Raid priorities and team roles
- score candidate actions with visible components
- compare alternatives
- return no more than three active projects
- include evidence, assumptions, stopping points, and opportunity costs

Exit condition: the engine can answer what to build next for Guild Raid and why the alternatives rank lower.

## Milestone 5: Advisor UI

- add an Advisor card and summary view
- show build queue and score breakdowns
- add a Why view
- show data freshness and game version
- support selecting an older player dump

## Milestone 6: Account history

- compare snapshots
- explain recommendation changes
- show progression over time
- detect unlocks, promotions, and resource changes

## Later modes

After Guild Raid works well, expand in this order:

1. Campaign and Elite Campaign minimums
2. Legendary Events and wave survival
3. Guild War offense and defense depth
4. Arena
5. Onslaught
6. Machines of War

## Merge policy

- Work remains on feature branches.
- Pull requests stay draft until explicitly approved.
- No automatic merge.
- Changes to recommendation ordering require tests.
