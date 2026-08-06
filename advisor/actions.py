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


def generate_candidate_actions(
    normalized: dict[str, Any],
    progression_models: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Return currently supported, factual actions without strategic ranking."""
    costs_by_level, cost_model = _ability_cost_table(progression_models)
    inventory = normalized.get("inventory") or {}
    badge_inventory = inventory.get("ability_badges") or {}

    actions: list[dict[str, Any]] = []
    excluded = {
        "ability_at_character_level": 0,
        "insufficient_ability_badges": 0,
        "unsupported_unit_ability_layout": 0,
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
            continue
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
            "supported_action_types": ["ability_level"],
            "pending_action_types": [
                "rank",
                "ascension",
                "equipment",
                "unlock",
            ],
            "unreported_resources": ["coins"],
            "evaluation": "Each action is evaluated independently, not as a combined spend plan.",
        },
        "cost_model": {
            "id": cost_model["id"],
            "knowledge_version": cost_model["knowledge_version"],
            "last_reviewed": cost_model["last_reviewed"],
            "sources": cost_model["sources"],
        },
        "scope": "Unranked factual candidate actions; strategic scoring is not enabled.",
    }
