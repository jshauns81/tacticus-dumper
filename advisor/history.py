"""Compare normalized Tacticus player snapshots without strategic inference."""

from __future__ import annotations

from typing import Any


def _project_summary(project: dict[str, Any]) -> dict[str, Any]:
    return {
        "action_id": project["action"]["id"],
        "title": project.get("title"),
        "type": project["action"]["type"],
        "character": project["action"]["character"],
        "score": project["score"],
        "action": project["action"],
    }


def compare_recommendation_queues(
    before: dict[str, Any], after: dict[str, Any]
) -> dict[str, Any]:
    """Compare two scored project queues without inferring unsupported causes."""
    before_projects = {
        project["action"]["id"]: project for project in before.get("projects") or []
    }
    after_projects = {
        project["action"]["id"]: project for project in after.get("projects") or []
    }
    before_alternatives = {
        alternative["action_id"]: alternative
        for alternative in before.get("alternatives") or []
    }
    after_alternatives = {
        alternative["action_id"]: alternative
        for alternative in after.get("alternatives") or []
    }

    added = []
    for action_id in sorted(after_projects.keys() - before_projects.keys()):
        project = _project_summary(after_projects[action_id])
        project["reason"] = (
            "promoted_from_alternative"
            if action_id in before_alternatives
            else "newly_eligible_or_supported"
        )
        added.append(project)

    removed = []
    for action_id in sorted(before_projects.keys() - after_projects.keys()):
        project = _project_summary(before_projects[action_id])
        alternative = after_alternatives.get(action_id)
        project["reason"] = (
            f"reprioritized:{alternative['reason']}"
            if alternative
            else "no_longer_eligible_or_supported"
        )
        removed.append(project)

    retained = []
    for action_id in sorted(before_projects.keys() & after_projects.keys()):
        old = before_projects[action_id]
        new = after_projects[action_id]
        retained.append(
            {
                "action_id": action_id,
                "title": new.get("title"),
                "type": new["action"]["type"],
                "character": new["action"]["character"],
                "before_score": old["score"],
                "after_score": new["score"],
                "score_delta": new["score"] - old["score"],
                "action": new["action"],
            }
        )

    score_changed = any(project["score_delta"] for project in retained)
    changed = bool(added or removed or score_changed)
    return {
        "status": "changed" if changed else "unchanged",
        "message": (
            "The prioritized Advisor queue changed between these snapshots."
            if changed
            else "The prioritized Advisor queue did not change between these snapshots."
        ),
        "before_status": before.get("status"),
        "after_status": after.get("status"),
        "added": added,
        "removed": removed,
        "retained": retained,
        "assumption": (
            "A removed project may have been completed, become ineligible, or fallen "
            "below another project. The queue comparison reports which condition is "
            "observable but does not infer unreported spending intent."
        ),
    }


def _progression_steps(
    progression_models: dict[str, dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    matching = [
        model
        for model in progression_models.values()
        if model.get("action_type") == "unit_progression"
    ]
    if len(matching) != 1:
        return {}
    return {
        step["current_progression_index"]: step for step in matching[0]["steps"]
    }


def _inventory_changes(
    before: dict[str, Any], after: dict[str, Any]
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for inventory_key, resource in (
        ("ability_badges", "ability_badge"),
        ("orbs", "orb"),
    ):
        before_groups = before.get(inventory_key) or {}
        after_groups = after.get(inventory_key) or {}
        for alliance in sorted(before_groups.keys() | after_groups.keys()):
            before_amounts = before_groups.get(alliance, {})
            after_amounts = after_groups.get(alliance, {})
            for rarity in sorted(before_amounts.keys() | after_amounts.keys()):
                old = before_amounts.get(rarity, 0)
                new = after_amounts.get(rarity, 0)
                if old != new:
                    changes.append(
                        {
                            "resource": resource,
                            "alliance": alliance,
                            "rarity": rarity,
                            "before": old,
                            "after": new,
                            "delta": new - old,
                        }
                    )

    for inventory_key, resource in (
        ("shards", "unowned_character_shard"),
        ("mythic_shards", "unowned_mythic_character_shard"),
    ):
        before_amounts = before.get(inventory_key) or {}
        after_amounts = after.get(inventory_key) or {}
        for character_id in sorted(before_amounts.keys() | after_amounts.keys()):
            old = before_amounts.get(character_id, 0)
            new = after_amounts.get(character_id, 0)
            if old != new:
                changes.append(
                    {
                        "resource": resource,
                        "character_id": character_id,
                        "before": old,
                        "after": new,
                        "delta": new - old,
                    }
                )
    return changes


def compare_player_snapshots(
    before: dict[str, Any],
    after: dict[str, Any],
    progression_models: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Return factual changes between two chronologically ordered snapshots."""
    before_units = {unit["id"]: unit for unit in before.get("units") or []}
    after_units = {unit["id"]: unit for unit in after.get("units") or []}
    progression_steps = _progression_steps(progression_models)
    events: list[dict[str, Any]] = []

    for character_id in sorted(after_units.keys() - before_units.keys()):
        unit = after_units[character_id]
        events.append(
            {
                "type": "unlock",
                "character": {"id": character_id, "name": unit["name"]},
                "after": {
                    "rank": unit["rank"],
                    "progression_index": unit["progression_index"],
                    "xp_level": unit["xp_level"],
                },
            }
        )

    for character_id in sorted(before_units.keys() - after_units.keys()):
        unit = before_units[character_id]
        events.append(
            {
                "type": "character_missing",
                "character": {"id": character_id, "name": unit["name"]},
            }
        )

    for character_id in sorted(before_units.keys() & after_units.keys()):
        old = before_units[character_id]
        new = after_units[character_id]
        character = {"id": character_id, "name": new["name"]}

        if old["rank"] != new["rank"]:
            events.append(
                {
                    "type": "rank_up" if new["rank"] > old["rank"] else "rank_changed",
                    "character": character,
                    "before": old["rank"],
                    "after": new["rank"],
                    "delta": new["rank"] - old["rank"],
                }
            )

        old_progression = old["progression_index"]
        new_progression = new["progression_index"]
        if old_progression != new_progression:
            if new_progression > old_progression and all(
                index in progression_steps
                for index in range(old_progression, new_progression)
            ):
                for index in range(old_progression, new_progression):
                    step = progression_steps[index]
                    events.append(
                        {
                            "type": step["action_type"],
                            "character": character,
                            "before": index,
                            "after": step["target_progression_index"],
                            "target_label": step["target_label"],
                        }
                    )
            else:
                events.append(
                    {
                        "type": "progression_changed",
                        "character": character,
                        "before": old_progression,
                        "after": new_progression,
                        "delta": new_progression - old_progression,
                    }
                )

        if old["xp_level"] != new["xp_level"]:
            events.append(
                {
                    "type": "character_level",
                    "character": character,
                    "before": old["xp_level"],
                    "after": new["xp_level"],
                    "delta": new["xp_level"] - old["xp_level"],
                }
            )

        old_abilities = {
            ability["id"]: ability["level"] for ability in old.get("abilities") or []
        }
        new_abilities = {
            ability["id"]: ability["level"] for ability in new.get("abilities") or []
        }
        for ability_id in sorted(old_abilities.keys() | new_abilities.keys()):
            old_level = old_abilities.get(ability_id)
            new_level = new_abilities.get(ability_id)
            if old_level != new_level:
                events.append(
                    {
                        "type": "ability_level",
                        "character": character,
                        "ability_id": ability_id,
                        "before": old_level,
                        "after": new_level,
                        "delta": (
                            new_level - old_level
                            if old_level is not None and new_level is not None
                            else None
                        ),
                    }
                )

        for field, resource in (
            ("shards", "character_shard"),
            ("mythic_shards", "mythic_character_shard"),
        ):
            if old[field] != new[field]:
                events.append(
                    {
                        "type": "resource_change",
                        "character": character,
                        "resource": resource,
                        "before": old[field],
                        "after": new[field],
                        "delta": new[field] - old[field],
                    }
                )

    resource_changes = _inventory_changes(
        before.get("inventory") or {}, after.get("inventory") or {}
    )
    power_before = before.get("power_level", 0)
    power_after = after.get("power_level", 0)
    unlocked_count = len(after_units.keys() - before_units.keys())
    missing_count = len(before_units.keys() - after_units.keys())

    return {
        "before": {
            "source": before["source"],
            "player": {
                "name": before.get("name", "Unknown"),
                "power_level": power_before,
                "unit_count": len(before_units),
            },
        },
        "after": {
            "source": after["source"],
            "player": {
                "name": after.get("name", "Unknown"),
                "power_level": power_after,
                "unit_count": len(after_units),
            },
        },
        "summary": {
            "power_delta": power_after - power_before,
            "unit_count_delta": len(after_units) - len(before_units),
            "unlocked_characters": unlocked_count,
            "missing_characters": missing_count,
            "events": len(events),
            "resource_changes": len(resource_changes),
        },
        "events": events,
        "resource_changes": resource_changes,
        "scope": (
            "Factual snapshot differences only. Resource deltas show net changes "
            "between dumps and do not infer individual gains or spending causes."
        ),
    }
