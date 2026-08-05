"""Parse Tacticus player dumps into a stable, testable advisor model."""

from __future__ import annotations

import json
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


def _ability_levels(unit: dict[str, Any]) -> list[int]:
    levels: list[int] = []
    for ability in unit.get("abilities") or []:
        if not isinstance(ability, dict):
            continue
        level = ability.get("level")
        if isinstance(level, int):
            levels.append(level)
    return levels


def normalize_player(payload: dict[str, Any]) -> dict[str, Any]:
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
        levels = _ability_levels(raw)
        items = raw.get("items") if isinstance(raw.get("items"), list) else []
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
                "ability_levels": levels,
                "ability_average": round(sum(levels) / len(levels), 1) if levels else 0.0,
                "equipped_items": len([item for item in items if isinstance(item, dict)]),
            }
        )

    return {
        "name": str(details.get("name") or "Unknown"),
        "power_level": int(details.get("powerLevel") or 0),
        "unit_count": len(units),
        "units": units,
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
