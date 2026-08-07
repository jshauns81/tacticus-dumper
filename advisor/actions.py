"""Generate deterministic, unranked advisor candidate actions."""

from __future__ import annotations

from typing import Any


class ActionModelError(ValueError):
    """Raised when progression knowledge cannot produce candidate actions."""


def _ability_cost_table(
    progression_models: dict[str, dict[str, Any]],
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    matching = [
        model
        for model in progression_models.values()
        if model.get("action_type") == "ability_level"
    ]
    if len(matching) != 1:
        raise ActionModelError(
            "Expected exactly one ability_level progression model."
        )

    model = matching[0]
    costs: dict[int, dict[str, Any]] = {}
    for band in model["level_bands"]:
        first = band["first_target_level"]
        coins = band["coin_costs"]
        badges = band["badge_costs"]
        if len(coins) != len(badges):
            raise ActionModelError(
                f"Progression model {model['id']} has unequal cost arrays."
            )
        for offset, (coin_cost, badge_cost) in enumerate(zip(coins, badges)):
            target_level = first + offset
            if target_level in costs:
                raise ActionModelError(
                    f"Progression model {model['id']} repeats target level {target_level}."
                )
            costs[target_level] = {
                "coins": coin_cost,
                "badge_rarity": band["rarity"],
                "badges": badge_cost,
            }
    return costs, model


def _unit_progression_table(
    progression_models: dict[str, dict[str, Any]],
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    matching = [
        model
        for model in progression_models.values()
        if model.get("action_type") == "unit_progression"
    ]
    if len(matching) != 1:
        raise ActionModelError(
            "Expected exactly one unit_progression progression model."
        )

    model = matching[0]
    steps: dict[int, dict[str, Any]] = {}
    for step in model["steps"]:
        current_index = step["current_progression_index"]
        target_index = step["target_progression_index"]
        if current_index in steps:
            raise ActionModelError(
                f"Progression model {model['id']} repeats index {current_index}."
            )
        if target_index != current_index + 1:
            raise ActionModelError(
                f"Progression model {model['id']} skips from index "
                f"{current_index} to {target_index}."
            )
        steps[current_index] = step
    return steps, model


def _unlock_cost_table(
    progression_models: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    matching = [
        model
        for model in progression_models.values()
        if model.get("action_type") == "unlock"
    ]
    if len(matching) != 1:
        raise ActionModelError("Expected exactly one unlock progression model.")

    model = matching[0]
    costs: dict[str, dict[str, Any]] = {}
    for cost in model["unlock_costs"]:
        rarity = cost["base_rarity"]
        if rarity in costs:
            raise ActionModelError(
                f"Progression model {model['id']} repeats base rarity {rarity}."
            )
        costs[rarity] = cost
    return costs, model


def _rank_progression_model(
    progression_models: dict[str, dict[str, Any]],
) -> tuple[list[str], int, dict[str, Any]]:
    matching = [
        model
        for model in progression_models.values()
        if model.get("action_type") == "rank"
    ]
    if len(matching) != 1:
        raise ActionModelError("Expected exactly one rank progression model.")

    model = matching[0]
    labels = model["rank_labels"]
    required_upgrade_slots = model["required_upgrade_slots"]
    if len(set(labels)) != len(labels):
        raise ActionModelError(
            f"Progression model {model['id']} repeats a rank label."
        )
    return labels, required_upgrade_slots, model


def _model_metadata(model: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": model["id"],
        "knowledge_version": model["knowledge_version"],
        "last_reviewed": model["last_reviewed"],
        "sources": model["sources"],
    }


def generate_candidate_actions(
    normalized: dict[str, Any],
    progression_models: dict[str, dict[str, Any]],
    character_knowledge: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return currently supported, factual actions without strategic ranking."""
    costs_by_level, ability_cost_model = _ability_cost_table(progression_models)
    progression_steps, unit_progression_model = _unit_progression_table(
        progression_models
    )
    unlock_costs, unlock_cost_model = _unlock_cost_table(progression_models)
    rank_labels, required_upgrade_slots, rank_progression_model = (
        _rank_progression_model(progression_models)
    )
    character_knowledge = character_knowledge or {}
    inventory = normalized.get("inventory") or {}
    badge_inventory = inventory.get("ability_badges") or {}
    orb_inventory = inventory.get("orbs") or {}

    actions: list[dict[str, Any]] = []
    excluded = {
        "ability_at_character_level": 0,
        "insufficient_ability_badges": 0,
        "insufficient_character_shards": 0,
        "insufficient_mythic_shards": 0,
        "insufficient_orbs": 0,
        "insufficient_unlock_shards": 0,
        "incomplete_rank_upgrades": 0,
        "progression_maxed": 0,
        "rank_maxed": 0,
        "unsupported_unlock_character": 0,
        "unsupported_unit_ability_layout": 0,
        "unsupported_progression_index": 0,
        "unsupported_rank": 0,
        "unsupported_target_level": 0,
    }

    units = sorted(
        normalized.get("units") or [],
        key=lambda unit: (unit.get("id", ""), unit.get("name", "")),
    )
    for unit in units:
        alliance = unit.get("grand_alliance", "Unknown")
        alliance_badges = badge_inventory.get(alliance, {})
        abilities = sorted(
            unit.get("abilities") or [], key=lambda ability: ability.get("id", "")
        )
        if len(abilities) != 2:
            excluded["unsupported_unit_ability_layout"] += len(abilities)
            abilities = []
        for ability in abilities:
            current_level = ability["level"]
            target_level = current_level + 1
            if target_level > unit["xp_level"]:
                excluded["ability_at_character_level"] += 1
                continue

            cost = costs_by_level.get(target_level)
            if cost is None:
                excluded["unsupported_target_level"] += 1
                continue

            badges_available = alliance_badges.get(cost["badge_rarity"], 0)
            if badges_available < cost["badges"]:
                excluded["insufficient_ability_badges"] += 1
                continue

            actions.append(
                {
                    "id": (
                        f"ability_level:{unit['id']}:{ability['id']}:{target_level}"
                    ),
                    "type": "ability_level",
                    "character": {"id": unit["id"], "name": unit["name"]},
                    "ability": {
                        "id": ability["id"],
                        "current_level": current_level,
                        "target_level": target_level,
                    },
                    "prerequisites": [
                        {
                            "resource": "character_level",
                            "required": target_level,
                            "available": unit["xp_level"],
                            "sufficient": True,
                        }
                    ],
                    "costs": [
                        {
                            "resource": "ability_badge",
                            "alliance": alliance,
                            "rarity": cost["badge_rarity"],
                            "required": cost["badges"],
                            "available": badges_available,
                            "sufficient": True,
                        },
                        {
                            "resource": "coins",
                            "required": cost["coins"],
                            "available": None,
                            "sufficient": None,
                        },
                    ],
                    "availability": "possible_if_unreported_coins_sufficient",
                }
            )

        current_rank = unit.get("rank")
        if not isinstance(current_rank, int) or not 0 <= current_rank < len(rank_labels):
            excluded["unsupported_rank"] += 1
        elif current_rank == len(rank_labels) - 1:
            excluded["rank_maxed"] += 1
        else:
            filled_upgrade_slots = {
                slot
                for slot in unit.get("equipped_upgrade_slots") or []
                if isinstance(slot, int) and 0 <= slot < required_upgrade_slots
            }
            if len(filled_upgrade_slots) != required_upgrade_slots:
                excluded["incomplete_rank_upgrades"] += 1
            else:
                target_rank = current_rank + 1
                actions.append(
                    {
                        "id": f"rank:{unit['id']}:{target_rank}",
                        "type": "rank",
                        "character": {"id": unit["id"], "name": unit["name"]},
                        "rank": {
                            "current": current_rank,
                            "current_label": rank_labels[current_rank],
                            "target": target_rank,
                            "target_label": rank_labels[target_rank],
                        },
                        "prerequisites": [
                            {
                                "resource": "applied_rank_upgrades",
                                "required": required_upgrade_slots,
                                "available": len(filled_upgrade_slots),
                                "sufficient": True,
                            }
                        ],
                        "costs": [],
                        "availability": "ready",
                    }
                )

        current_index = unit["progression_index"]
        step = progression_steps.get(current_index)
        if step is None:
            if current_index == unit_progression_model["max_progression_index"]:
                excluded["progression_maxed"] += 1
            else:
                excluded["unsupported_progression_index"] += 1
            continue

        shard_resource = step["shard_resource"]
        shards_available = unit[shard_resource]
        if shards_available < step["shard_amount"]:
            reason = (
                "insufficient_mythic_shards"
                if shard_resource == "mythic_shards"
                else "insufficient_character_shards"
            )
            excluded[reason] += 1
            continue

        orb = step.get("orb")
        orbs_available = None
        if orb is not None:
            orbs_available = orb_inventory.get(alliance, {}).get(orb["rarity"], 0)
            if orbs_available < orb["amount"]:
                excluded["insufficient_orbs"] += 1
                continue

        costs = [
            {
                "resource": (
                    "mythic_character_shard"
                    if shard_resource == "mythic_shards"
                    else "character_shard"
                ),
                "character_id": unit["id"],
                "required": step["shard_amount"],
                "available": shards_available,
                "sufficient": True,
            }
        ]
        if orb is not None:
            costs.append(
                {
                    "resource": "orb",
                    "alliance": alliance,
                    "rarity": orb["rarity"],
                    "required": orb["amount"],
                    "available": orbs_available,
                    "sufficient": True,
                }
            )

        actions.append(
            {
                "id": f"{step['action_type']}:{unit['id']}:{step['target_progression_index']}",
                "type": step["action_type"],
                "character": {"id": unit["id"], "name": unit["name"]},
                "progression": {
                    "current_index": current_index,
                    "target_index": step["target_progression_index"],
                    "target_label": step["target_label"],
                },
                "prerequisites": [],
                "costs": costs,
                "availability": "ready",
            }
        )

    owned_character_ids = {unit["id"] for unit in units}
    shard_inventory = inventory.get("shards") or {}
    unowned_shard_ids = set(shard_inventory) - owned_character_ids
    excluded["unsupported_unlock_character"] = len(
        unowned_shard_ids - character_knowledge.keys()
    )

    for character_id, character in sorted(character_knowledge.items()):
        if character_id in owned_character_ids:
            continue
        cost = unlock_costs.get(character["base_rarity"])
        if cost is None:
            raise ActionModelError(
                f"No unlock cost for base rarity {character['base_rarity']}."
            )
        shards_available = shard_inventory.get(character_id, 0)
        if shards_available < cost["shards"]:
            excluded["insufficient_unlock_shards"] += 1
            continue
        actions.append(
            {
                "id": f"unlock:{character_id}:{cost['target_progression_index']}",
                "type": "unlock",
                "character": {"id": character_id, "name": character["name"]},
                "progression": {
                    "current_index": None,
                    "target_index": cost["target_progression_index"],
                    "target_label": f"{character['base_rarity']} Unlock",
                },
                "prerequisites": [],
                "costs": [
                    {
                        "resource": "character_shard",
                        "character_id": character_id,
                        "required": cost["shards"],
                        "available": shards_available,
                        "sufficient": True,
                    }
                ],
                "availability": "ready",
            }
        )

    actions.sort(key=lambda action: action["id"])

    return {
        "source": normalized.get("source", {"filename": None, "imported_at": None}),
        "player": {
            "name": normalized.get("name", "Unknown"),
            "power_level": normalized.get("power_level", 0),
            "unit_count": normalized.get("unit_count", len(units)),
        },
        "actions": actions,
        "counts": {
            "returned": len(actions),
            "excluded": sum(excluded.values()),
            "excluded_by_reason": excluded,
        },
        "coverage": {
            "supported_action_types": [
                "ability_level",
                "ascension",
                "promotion",
                "rank",
                "unlock",
            ],
            "pending_action_types": [
                "equipment",
            ],
            "unreported_resources": ["coins"],
            "evaluation": "Each action is evaluated independently, not as a combined spend plan.",
            "unlock_knowledge": {
                "known_characters": len(character_knowledge),
                "unmapped_unowned_shard_records": excluded[
                    "unsupported_unlock_character"
                ],
            },
        },
        "cost_models": {
            "ability_level": _model_metadata(ability_cost_model),
            "unit_progression": _model_metadata(unit_progression_model),
            "unlock": _model_metadata(unlock_cost_model),
            "rank": _model_metadata(rank_progression_model),
        },
        "scope": "Unranked factual candidate actions; strategic scoring is not enabled.",
    }
