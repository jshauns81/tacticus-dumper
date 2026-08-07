"""Score factual advisor actions against versioned strategic knowledge."""

from __future__ import annotations

from collections import Counter
from typing import Any


class ActionScoringError(ValueError):
    """Raised when scoring knowledge cannot produce recommendations."""


def _matching_policies(
    scoring_models: dict[str, dict[str, Any]],
    mode_id: str,
    archetype_id: str | None = None,
) -> list[dict[str, Any]]:
    matching = sorted(
        [
            model
            for model in scoring_models.values()
            if model.get("mode_id") == mode_id
        ],
        key=lambda model: model["id"],
    )
    if not matching:
        raise ActionScoringError(
            f"Expected at least one scoring model for mode {mode_id}."
        )
    if archetype_id is not None:
        matching = [
            policy
            for policy in matching
            if policy["team_archetype_id"] == archetype_id
        ]
        if not matching:
            raise ActionScoringError(
                f"Unknown {mode_id} team archetype: {archetype_id}."
            )
    return matching


def _shared_project_limits(policies: list[dict[str, Any]]) -> tuple[int, int]:
    baseline = policies[0]
    comparable_fields = ("weights", "max_projects", "max_projects_per_character")
    for policy in policies[1:]:
        if any(policy[field] != baseline[field] for field in comparable_fields):
            raise ActionScoringError(
                "Guild Raid scoring policies must use comparable weights and project limits."
            )
    return baseline["max_projects"], baseline["max_projects_per_character"]


def _select_projects(
    scored: list[dict[str, Any]],
    max_projects: int,
    max_projects_per_character: int,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    ordered = sorted(
        scored,
        key=lambda item: (-item["score"], item["action"]["id"]),
    )
    selected: list[dict[str, Any]] = []
    character_counts: Counter[str] = Counter()
    selection_reason: dict[str, str] = {}
    for item in ordered:
        character_id = item["action"]["character"]["id"]
        if len(selected) >= max_projects:
            selection_reason[item["action"]["id"]] = "project_limit"
            continue
        if character_counts[character_id] >= max_projects_per_character:
            selection_reason[item["action"]["id"]] = "character_project_limit"
            continue
        character_counts[character_id] += 1
        selected.append(item)
    return selected, selection_reason


def _archetype_options(
    scored_matches: list[dict[str, Any]],
    policy_contexts: list[tuple[dict[str, Any], dict[str, Any]]],
    max_projects: int,
    max_projects_per_character: int,
) -> list[dict[str, Any]]:
    options = []
    for _, archetype in policy_contexts:
        candidates = [
            item
            for item in scored_matches
            if item["archetype"]["id"] == archetype["id"]
        ]
        preview, _ = _select_projects(
            candidates, max_projects, max_projects_per_character
        )
        options.append(
            {
                "id": archetype["id"],
                "name": archetype["name"],
                "project_count": len(preview),
                "project_score_total": sum(item["score"] for item in preview),
                "best_project_score": max(
                    (item["score"] for item in preview), default=0
                ),
            }
        )

    if options:
        recommended = max(
            options,
            key=lambda option: (
                option["project_score_total"],
                option["project_count"],
                option["best_project_score"],
                option["id"],
            ),
        )["id"]
        for option in options:
            option["recommended"] = option["id"] == recommended
    return options


def _archetype_summary(archetype: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": archetype["id"],
        "name": archetype["name"],
        "required_roles": archetype["required_roles"],
        "optional_roles": archetype.get("optional_roles") or [],
        "exclusions": archetype.get("exclusions") or [],
    }


def _owned_archetype_roles(
    owned_ids: set[str],
    archetype: dict[str, Any],
    characters: dict[str, dict[str, Any]],
) -> set[str]:
    return {
        role
        for role, candidate_ids in archetype.get("candidates_by_role", {}).items()
        if any(
            character_id in owned_ids
            and role in characters.get(character_id, {}).get("roles", [])
            for character_id in candidate_ids
        )
    }


def _component(
    component_id: str,
    points: int,
    reason: str,
    knowledge_ids: list[str],
) -> dict[str, Any]:
    return {
        "id": component_id,
        "points": points,
        "reason": reason,
        "knowledge_ids": knowledge_ids,
    }


def _evidence(
    record_ids: list[tuple[str, str]],
    knowledge: dict[str, dict[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    evidence = []
    for collection, record_id in record_ids:
        record = knowledge[collection][record_id]
        evidence.append(
            {
                "knowledge_id": record_id,
                "name": record["name"],
                "sources": record["sources"],
            }
        )
    return evidence


def _opportunity_costs(action: dict[str, Any]) -> list[str]:
    costs = []
    for cost in action.get("costs") or []:
        resource = cost["resource"]
        required = cost["required"]
        if resource == "ability_badge":
            costs.append(
                f"Uses {required} {cost['rarity']} {cost['alliance']} ability "
                "badge(s) that could support another character."
            )
        elif resource == "coins" and cost.get("available") is None:
            costs.append(
                f"Requires {required} coins; the Player API does not report the "
                "available coin balance."
            )
        elif resource in {"character_shard", "mythic_character_shard"}:
            costs.append(
                f"Uses {required} character-specific shard(s), reducing progress "
                "toward later promotions or ascensions."
            )
        elif resource == "orb":
            costs.append(
                f"Uses {required} {cost['rarity']} {cost['alliance']} orb(s) shared "
                "with other characters in that alliance."
            )
        else:
            costs.append(f"Uses {required} unit(s) of {resource}.")
    if action["type"] == "rank" and not costs:
        costs.append(
            "No additional resource cost is represented; all six rank upgrades "
            "are already applied."
        )
    return costs


def _stopping_point(action: dict[str, Any]) -> str:
    if action["type"] == "ability_level":
        target = action["ability"]["target_level"]
        return f"Raise only this ability to level {target}, refresh the dump, and rescore."
    if action["type"] == "rank":
        return (
            f"Rank up to {action['rank']['target_label']}, refresh the dump, and rescore."
        )
    if action["type"] == "unlock":
        return "Unlock the character, refresh the dump, and rescore before investing further."
    target = action["progression"]["target_label"]
    return f"Advance only to {target}, refresh the dump, and rescore."


def _action_title(
    action: dict[str, Any], ability: dict[str, Any] | None = None
) -> str:
    if action["type"] == "ability_level":
        target = action["ability"]["target_level"]
        return f"Raise {ability['name']} to level {target}"
    if action["type"] == "rank":
        return f"Rank up to {action['rank']['target_label']}"
    if action["type"] == "unlock":
        return f"Unlock {action['character']['name']}"
    verb = "Ascend" if action["type"] == "ascension" else "Promote"
    return f"{verb} to {action['progression']['target_label']}"


def score_guild_raid_actions(
    normalized: dict[str, Any],
    candidate_result: dict[str, Any],
    knowledge: dict[str, dict[str, dict[str, Any]]],
    *,
    mode_id: str = "guildRaid",
    archetype_id: str | None = None,
) -> dict[str, Any]:
    """Return at most three explainable Guild Raid projects."""
    policies = _matching_policies(
        knowledge["scoring_models"], mode_id, archetype_id
    )
    try:
        mode = knowledge["modes"][mode_id]
        policy_contexts = [
            (
                policy,
                knowledge["team_archetypes"][policy["team_archetype_id"]],
            )
            for policy in policies
        ]
    except KeyError as exc:
        raise ActionScoringError(f"Scoring knowledge reference is missing: {exc}") from exc

    owned_ids = {unit["id"] for unit in normalized.get("units") or []}
    max_projects, max_projects_per_character = _shared_project_limits(policies)

    excluded = Counter()
    scored: list[dict[str, Any]] = []
    scored_matches: list[dict[str, Any]] = []
    for action in candidate_result.get("actions") or []:
        character_id = action.get("character", {}).get("id")
        character = knowledge["characters"].get(character_id)
        if character is None:
            excluded["unknown_character"] += 1
            continue

        character_roles = set(character.get("roles") or [])
        matched_an_archetype = False
        action_matches: list[dict[str, Any]] = []
        for policy, archetype in policy_contexts:
            required_roles = set(archetype["required_roles"])
            optional_roles = set(archetype.get("optional_roles") or [])
            archetype_roles = {
                role
                for role, character_ids in archetype.get(
                    "candidates_by_role", {}
                ).items()
                if character_id in character_ids
            }
            matched_required = sorted(
                character_roles & required_roles & archetype_roles
            )
            matched_optional = sorted(
                character_roles & optional_roles & archetype_roles
            )
            if not matched_required and not matched_optional:
                continue
            matched_an_archetype = True

            weights = policy["weights"]
            components: list[dict[str, Any]] = []
            if matched_required:
                components.append(
                    _component(
                        "required_role",
                        weights["required_role"],
                        f"Fills required role(s): {', '.join(matched_required)}.",
                        [character_id, archetype["id"]],
                    )
                )
            if matched_optional:
                components.append(
                    _component(
                        "optional_role",
                        weights["optional_role"],
                        f"Fills optional role(s): {', '.join(matched_optional)}.",
                        [character_id, archetype["id"]],
                    )
                )

            evidence_records: list[tuple[str, str]] = [
                ("characters", character_id),
                ("team_archetypes", archetype["id"]),
            ]
            action_type = action["type"]
            ability = None
            if action_type == "ability_level":
                ability_id = action["ability"]["id"]
                ability = knowledge["abilities"].get(ability_id)
                aligned_roles = sorted(
                    set((ability or {}).get("supports_roles") or [])
                    & character_roles
                    & (required_roles | optional_roles)
                    & archetype_roles
                )
                if not aligned_roles:
                    continue
                components.append(
                    _component(
                        "role_aligned_ability",
                        weights["role_aligned_ability"],
                        f"Directly advances {ability['name']} for role(s): "
                        f"{', '.join(aligned_roles)}.",
                        [ability_id, archetype["id"]],
                    )
                )
                evidence_records.append(("abilities", ability_id))
            elif action_type in {"promotion", "ascension", "rank"}:
                components.append(
                    _component(
                        "general_progression",
                        weights["general_progression"],
                        "Improves a documented archetype character's general progression.",
                        [character_id, archetype["id"]],
                    )
                )
            elif action_type == "unlock":
                owned_roles = _owned_archetype_roles(
                    owned_ids, archetype, knowledge["characters"]
                )
                if set(matched_required) - owned_roles:
                    components.append(
                        _component(
                            "unlock_missing_required_role",
                            weights["unlock_missing_required_role"],
                            "Unlocks a required role not currently covered by known owned characters.",
                            [character_id, archetype["id"]],
                        )
                    )
                else:
                    components.append(
                        _component(
                            "general_progression",
                            weights["general_progression"],
                            "Adds another documented character for the selected archetype.",
                            [character_id, archetype["id"]],
                        )
                    )
            else:
                continue

            if action.get("availability") == "ready":
                components.append(
                    _component(
                        "ready",
                        weights["ready"],
                        "All resources reported by the Player API are sufficient.",
                        [policy["id"]],
                    )
                )
            else:
                components.append(
                    _component(
                        "conditional_resources",
                        weights["conditional_resources"],
                        "Reported resources are sufficient, but an unreported resource must be checked.",
                        [policy["id"]],
                    )
                )

            owned_roles = _owned_archetype_roles(
                owned_ids, archetype, knowledge["characters"]
            )
            projected_roles = (
                owned_roles | set(matched_required) | set(matched_optional)
            )
            if required_roles <= projected_roles:
                components.append(
                    _component(
                        "complete_required_role_core",
                        weights["complete_required_role_core"],
                        "Keeps or completes coverage of every required archetype role.",
                        [archetype["id"]],
                    )
                )

            score = sum(component["points"] for component in components)
            action_matches.append(
                {
                    "action": action,
                    "title": _action_title(action, ability),
                    "score": score,
                    "archetype": {
                        "id": archetype["id"],
                        "name": archetype["name"],
                    },
                    "policy_id": policy["id"],
                    "components": components,
                    "why": " ".join(
                        component["reason"] for component in components
                    ),
                    "assumptions": [
                        "Scores compare ordinal priorities; they do not predict boss damage.",
                        *(
                            [
                                "Coin sufficiency must be confirmed in game because the Player API does not report coins."
                            ]
                            if action.get("availability")
                            == "possible_if_unreported_coins_sufficient"
                            else []
                        ),
                    ],
                    "stopping_point": _stopping_point(action),
                    "opportunity_costs": _opportunity_costs(action),
                    "evidence": _evidence(evidence_records, knowledge),
                }
            )

        if action_matches:
            scored_matches.extend(action_matches)
            action_matches.sort(
                key=lambda item: (-item["score"], item["policy_id"])
            )
            scored.append(action_matches[0])
        elif not matched_an_archetype:
            excluded["no_archetype_role"] += 1
        elif action["type"] == "ability_level":
            excluded["undocumented_ability_role"] += 1
        else:
            excluded["unsupported_action_type"] += 1

    scored.sort(key=lambda item: (-item["score"], item["action"]["id"]))
    selected, selection_reason = _select_projects(
        scored, max_projects, max_projects_per_character
    )

    for rank, item in enumerate(selected, start=1):
        item["rank"] = rank

    selected_ids = {item["action"]["id"] for item in selected}
    alternatives = [
        {
            "action_id": item["action"]["id"],
            "title": item["title"],
            "character": item["action"]["character"],
            "archetype": item["archetype"],
            "policy_id": item["policy_id"],
            "score": item["score"],
            "reason": selection_reason.get(item["action"]["id"], "lower_score"),
        }
        for item in scored
        if item["action"]["id"] not in selected_ids
    ][:10]

    candidate_counts_by_character = Counter(
        action.get("character", {}).get("id")
        for action in candidate_result.get("actions") or []
    )
    covered_character_ids = {
        character_id
        for _, archetype in policy_contexts
        for character_ids in archetype.get("candidates_by_role", {}).values()
        for character_id in character_ids
    }
    known_owned_characters = [
        {
            "id": character_id,
            "name": knowledge["characters"][character_id]["name"],
            "candidate_actions": candidate_counts_by_character[character_id],
        }
        for character_id in sorted(owned_ids & covered_character_ids)
    ]
    status = "projects_ready" if selected else "no_supported_project_ready"
    message = (
        "Prioritized Guild Raid projects are ready."
        if selected
        else (
            "No resource-ready or conditionally-ready action is available for the "
            "currently known Guild Raid characters. Refresh after roster or inventory "
            "changes."
        )
    )
    archetypes = [_archetype_summary(archetype) for _, archetype in policy_contexts]
    policy_details = [
        {
            "id": policy["id"],
            "name": policy["name"],
            "knowledge_version": policy["knowledge_version"],
            "last_reviewed": policy["last_reviewed"],
            "team_archetype_id": policy["team_archetype_id"],
            "weights": policy["weights"],
            "sources": policy["sources"],
        }
        for policy in policies
    ]
    policy_summary = {
        "id": (
            policies[0]["id"]
            if len(policies) == 1
            else "multiArchetypeGuildRaid"
        ),
        "name": (
            policies[0]["name"]
            if len(policies) == 1
            else "Validated Guild Raid archetype policies"
        ),
        "knowledge_version": max(
            policy["knowledge_version"] for policy in policies
        ),
        "last_reviewed": max(policy["last_reviewed"] for policy in policies),
        "policy_ids": [policy["id"] for policy in policies],
        "max_projects": max_projects,
        "max_projects_per_character": max_projects_per_character,
    }

    return {
        "status": status,
        "message": message,
        "source": candidate_result["source"],
        "player": candidate_result["player"],
        "mode": {"id": mode_id, "name": mode["name"]},
        "archetype": archetypes[0],
        "archetypes": archetypes,
        "archetype_options": _archetype_options(
            scored_matches,
            policy_contexts,
            max_projects,
            max_projects_per_character,
        ),
        "projects": selected,
        "alternatives": alternatives,
        "counts": {
            "candidate_actions": len(candidate_result.get("actions") or []),
            "scored_actions": len(scored),
            "returned_projects": len(selected),
            "excluded_actions": sum(excluded.values()),
            "excluded_by_reason": dict(sorted(excluded.items())),
        },
        "coverage": {
            "knowledge_characters": len(knowledge["characters"]),
            "known_owned_characters": known_owned_characters,
            "unknown_candidate_actions": excluded["unknown_character"],
        },
        "policy": policy_summary,
        "policies": policy_details,
        "scope": (
            "Guild Raid recommendations cover only characters and ability-role links "
            "present in the validated knowledge repository."
        ),
    }
