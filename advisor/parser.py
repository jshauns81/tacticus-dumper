"""Parse Tacticus player dumps into a stable, testable advisor model."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_latest_player_dump(dumps_dir: Path) -> tuple[Path, dict[str, Any]]:
    """Return the newest player dump and its decoded JSON payload."""
    candidates = sorted(
        dumps_dir.glob("player_*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError("No player_*.json dumps were found.")

    latest = candidates[0]
    try:
        payload = json.loads(latest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Latest player dump is invalid JSON: {latest.name}") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"Player dump must contain a JSON object: {latest.name}")
    return latest, payload


def _abilities(unit: dict[str, Any]) -> list[dict[str, Any]]:
    abilities: list[dict[str, Any]] = []
    for ability in unit.get("abilities") or []:
        if not isinstance(ability, dict):
            continue
        ability_id = ability.get("id")
        level = ability.get("level")
        if isinstance(ability_id, str) and ability_id and isinstance(level, int):
            abilities.append({"id": ability_id, "level": level})
    return abilities


def _alliance_rarity_inventory(raw: Any) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    if not isinstance(raw, dict):
        return result
    for alliance, entries in raw.items():
        if not isinstance(alliance, str) or not isinstance(entries, list):
            continue
        amounts: dict[str, int] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            rarity = entry.get("rarity")
            amount = entry.get("amount")
            if isinstance(rarity, str) and isinstance(amount, int):
                amounts[rarity] = amount
        result[alliance] = amounts
    return result


def _id_amount_inventory(raw: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    if not isinstance(raw, list):
        return result
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        entry_id = entry.get("id")
        amount = entry.get("amount")
        if isinstance(entry_id, str) and entry_id and isinstance(amount, int):
            result[entry_id] = amount
    return result


def normalize_player(
    payload: dict[str, Any], *, source_path: Path | None = None
) -> dict[str, Any]:
    """Normalize the portions of the API payload needed by Advisor V1."""
    player = payload.get("player")
    if not isinstance(player, dict):
        raise ValueError("Player dump does not contain a player object.")

    details = player.get("details") if isinstance(player.get("details"), dict) else {}
    raw_units = player.get("units") if isinstance(player.get("units"), list) else []
    units: list[dict[str, Any]] = []

    for raw in raw_units:
        if not isinstance(raw, dict):
            continue
        abilities = _abilities(raw)
        levels = [ability["level"] for ability in abilities]
        items = raw.get("items") if isinstance(raw.get("items"), list) else []
        upgrades = raw.get("upgrades") if isinstance(raw.get("upgrades"), list) else []
        units.append(
            {
                "id": str(raw.get("id") or ""),
                "name": str(raw.get("name") or raw.get("id") or "Unknown"),
                "faction": str(raw.get("faction") or "Unknown"),
                "grand_alliance": str(raw.get("grandAlliance") or "Unknown"),
                "progression_index": int(raw.get("progressionIndex") or 0),
                "rank": int(raw.get("rank") or 0),
                "xp_level": int(raw.get("xpLevel") or 0),
                "shards": int(raw.get("shards") or 0),
                "mythic_shards": int(raw.get("mythicShards") or 0),
                "abilities": abilities,
                "ability_levels": levels,
                "ability_average": round(sum(levels) / len(levels), 1) if levels else 0.0,
                "equipped_items": len([item for item in items if isinstance(item, dict)]),
                "equipped_upgrade_slots": sorted(
                    {slot for slot in upgrades if isinstance(slot, int)}
                ),
            }
        )

    raw_inventory = (
        player.get("inventory") if isinstance(player.get("inventory"), dict) else {}
    )

    source = {
        "filename": source_path.name if source_path else None,
        "imported_at": (
            datetime.fromtimestamp(source_path.stat().st_mtime, tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
            if source_path
            else None
        ),
    }

    return {
        "name": str(details.get("name") or "Unknown"),
        "power_level": int(details.get("powerLevel") or 0),
        "unit_count": len(units),
        "units": units,
        "inventory": {
            "ability_badges": _alliance_rarity_inventory(
                raw_inventory.get("abilityBadges")
            ),
            "orbs": _alliance_rarity_inventory(raw_inventory.get("orbs")),
            "shards": _id_amount_inventory(raw_inventory.get("shards")),
            "mythic_shards": _id_amount_inventory(
                raw_inventory.get("mythicShards")
            ),
        },
        "source": source,
    }


def summarize_roster(normalized: dict[str, Any], limit: int = 10) -> dict[str, Any]:
    """Create factual Advisor V1 output without game-meta assumptions."""
    units = list(normalized.get("units") or [])

    by_investment = sorted(
        units,
        key=lambda unit: (
            unit["rank"],
            unit["xp_level"],
            unit["ability_average"],
            unit["progression_index"],
        ),
        reverse=True,
    )
    promotion_ready = sorted(
        [unit for unit in units if unit["shards"] >= 100],
        key=lambda unit: (unit["shards"], unit["rank"]),
        reverse=True,
    )
    underdeveloped = sorted(
        [unit for unit in units if unit["rank"] <= 3 and unit["xp_level"] >= 10],
        key=lambda unit: (unit["xp_level"], unit["shards"]),
        reverse=True,
    )

    faction_counts: dict[str, int] = {}
    for unit in units:
        faction = unit["faction"]
        faction_counts[faction] = faction_counts.get(faction, 0) + 1

    return {
        "source": normalized.get(
            "source", {"filename": None, "imported_at": None}
        ),
        "player": {
            "name": normalized.get("name", "Unknown"),
            "power_level": normalized.get("power_level", 0),
            "unit_count": normalized.get("unit_count", len(units)),
        },
        "top_invested": by_investment[:limit],
        "promotion_candidates": promotion_ready[:limit],
        "developed_but_low_rank": underdeveloped[:limit],
        "faction_counts": dict(sorted(faction_counts.items(), key=lambda item: (-item[1], item[0]))),
        "scope": "Factual roster summary only. Strategic recommendations are not yet enabled.",
    }
