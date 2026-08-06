from pathlib import Path

from advisor.actions import ActionModelError, generate_candidate_actions
from advisor.knowledge import load_knowledge_collection


def progression_models():
    return {
        "testCosts": {
            "id": "testCosts",
            "knowledge_version": "test",
            "last_reviewed": "2026-08-05",
            "action_type": "ability_level",
            "level_bands": [
                {
                    "rarity": "Common",
                    "first_target_level": 2,
                    "coin_costs": [25, 50, 100, 150, 200, 300, 400],
                    "badge_costs": [1, 1, 1, 2, 2, 2, 3],
                },
                {
                    "rarity": "Uncommon",
                    "first_target_level": 9,
                    "coin_costs": [500, 600, 700, 800],
                    "badge_costs": [1, 1, 1, 2],
                },
            ],
            "sources": [{"type": "controlled_test", "reference": "fixture"}],
        },
        "testProgression": {
            "id": "testProgression",
            "knowledge_version": "test",
            "last_reviewed": "2026-08-05",
            "action_type": "unit_progression",
            "max_progression_index": 19,
            "steps": [
                {
                    "current_progression_index": 2,
                    "target_progression_index": 3,
                    "target_label": "Uncommon 2 Stars",
                    "action_type": "ascension",
                    "shard_resource": "shards",
                    "shard_amount": 15,
                    "orb": {"rarity": "Uncommon", "amount": 10},
                },
                {
                    "current_progression_index": 3,
                    "target_progression_index": 4,
                    "target_label": "3 Stars",
                    "action_type": "promotion",
                    "shard_resource": "shards",
                    "shard_amount": 15,
                },
            ],
            "sources": [{"type": "controlled_test", "reference": "fixture"}],
        },
        "testUnlock": {
            "id": "testUnlock",
            "knowledge_version": "test",
            "last_reviewed": "2026-08-06",
            "action_type": "unlock",
            "unlock_costs": [
                {"base_rarity": "Uncommon", "target_progression_index": 3, "shards": 80},
                {"base_rarity": "Rare", "target_progression_index": 6, "shards": 130},
            ],
            "sources": [{"type": "controlled_test", "reference": "fixture"}],
        },
    }


def character_knowledge():
    return {
        "locked": {"id": "locked", "name": "Locked", "base_rarity": "Rare"},
        "short": {"id": "short", "name": "Short", "base_rarity": "Uncommon"},
    }


def normalized_player():
    return {
        "name": "Action Tester",
        "power_level": 10,
        "unit_count": 3,
        "source": {"filename": "player_test.json", "imported_at": None},
        "inventory": {
            "ability_badges": {
                "Xenos": {"Common": 3, "Uncommon": 1},
                "Imperial": {"Uncommon": 0},
            },
            "orbs": {"Xenos": {"Uncommon": 10}},
            "shards": {"locked": 130, "short": 79, "unknown": 999},
        },
        "units": [
            {
                "id": "zeta",
                "name": "Zeta",
                "grand_alliance": "Xenos",
                "progression_index": 3,
                "xp_level": 8,
                "shards": 14,
                "mythic_shards": 0,
                "abilities": [
                    {"id": "zetaActive", "level": 7},
                    {"id": "zetaPassive", "level": 7},
                ],
            },
            {
                "id": "alpha",
                "name": "Alpha",
                "grand_alliance": "Xenos",
                "progression_index": 2,
                "xp_level": 10,
                "shards": 15,
                "mythic_shards": 0,
                "abilities": [
                    {"id": "alphaActive", "level": 8},
                    {"id": "alphaPassive", "level": 8},
                ],
            },
            {
                "id": "blocked",
                "name": "Blocked",
                "grand_alliance": "Imperial",
                "progression_index": 19,
                "xp_level": 10,
                "shards": 999,
                "mythic_shards": 0,
                "abilities": [
                    {"id": "atCap", "level": 10},
                    {"id": "needsBadge", "level": 8},
                ],
            },
        ],
    }


def test_generates_deterministic_actions_and_filters_known_blockers():
    result = generate_candidate_actions(
        normalized_player(), progression_models(), character_knowledge()
    )

    assert [action["id"] for action in result["actions"]] == [
        "ability_level:alpha:alphaActive:9",
        "ability_level:alpha:alphaPassive:9",
        "ability_level:zeta:zetaActive:8",
        "ability_level:zeta:zetaPassive:8",
        "ascension:alpha:3",
        "unlock:locked:6",
    ]
    assert result["counts"] == {
        "returned": 6,
        "excluded": 6,
        "excluded_by_reason": {
            "ability_at_character_level": 1,
            "insufficient_ability_badges": 1,
            "insufficient_character_shards": 1,
            "insufficient_mythic_shards": 0,
            "insufficient_orbs": 0,
            "insufficient_unlock_shards": 1,
            "progression_maxed": 1,
            "unsupported_unlock_character": 1,
            "unsupported_unit_ability_layout": 0,
            "unsupported_progression_index": 0,
            "unsupported_target_level": 0,
        },
    }


def test_reports_known_costs_and_marks_unreported_coins_unknown():
    result = generate_candidate_actions(
        normalized_player(), progression_models(), character_knowledge()
    )
    action = result["actions"][0]

    assert action["prerequisites"] == [
        {
            "resource": "character_level",
            "required": 9,
            "available": 10,
            "sufficient": True,
        }
    ]
    assert action["costs"] == [
        {
            "resource": "ability_badge",
            "alliance": "Xenos",
            "rarity": "Uncommon",
            "required": 1,
            "available": 1,
            "sufficient": True,
        },
        {
            "resource": "coins",
            "required": 500,
            "available": None,
            "sufficient": None,
        },
    ]
    assert action["availability"] == "possible_if_unreported_coins_sufficient"


def test_generates_resource_ready_ascension_action():
    result = generate_candidate_actions(
        normalized_player(), progression_models(), character_knowledge()
    )
    action = next(action for action in result["actions"] if action["type"] == "ascension")

    assert action == {
        "id": "ascension:alpha:3",
        "type": "ascension",
        "character": {"id": "alpha", "name": "Alpha"},
        "progression": {
            "current_index": 2,
            "target_index": 3,
            "target_label": "Uncommon 2 Stars",
        },
        "prerequisites": [],
        "costs": [
            {
                "resource": "character_shard",
                "character_id": "alpha",
                "required": 15,
                "available": 15,
                "sufficient": True,
            },
            {
                "resource": "orb",
                "alliance": "Xenos",
                "rarity": "Uncommon",
                "required": 10,
                "available": 10,
                "sufficient": True,
            },
        ],
        "availability": "ready",
    }


def test_generates_unlock_only_for_known_character_with_enough_shards():
    result = generate_candidate_actions(
        normalized_player(), progression_models(), character_knowledge()
    )
    unlocks = [action for action in result["actions"] if action["type"] == "unlock"]

    assert unlocks == [
        {
            "id": "unlock:locked:6",
            "type": "unlock",
            "character": {"id": "locked", "name": "Locked"},
            "progression": {
                "current_index": None,
                "target_index": 6,
                "target_label": "Rare Unlock",
            },
            "prerequisites": [],
            "costs": [
                {
                    "resource": "character_shard",
                    "character_id": "locked",
                    "required": 130,
                    "available": 130,
                    "sufficient": True,
                }
            ],
            "availability": "ready",
        }
    ]
    assert result["coverage"]["unlock_knowledge"] == {
        "known_characters": 2,
        "unmapped_unowned_shard_records": 1,
    }


def test_rejects_ambiguous_or_malformed_cost_models():
    models = progression_models()
    models["duplicate"] = dict(models["testCosts"], id="duplicate")

    try:
        generate_candidate_actions(
            normalized_player(), models, character_knowledge()
        )
    except ActionModelError as exc:
        assert "exactly one" in str(exc)
    else:
        raise AssertionError("Expected an ambiguous model to be rejected")

    malformed = progression_models()
    malformed["testCosts"]["level_bands"][0]["badge_costs"] = [1]
    try:
        generate_candidate_actions(
            normalized_player(), malformed, character_knowledge()
        )
    except ActionModelError as exc:
        assert "unequal cost arrays" in str(exc)
    else:
        raise AssertionError("Expected unequal cost arrays to be rejected")


def test_repository_progression_model_preserves_rarity_boundaries():
    models = load_knowledge_collection(Path("knowledge"), "progression_models")
    normalized = {
        "inventory": {
            "ability_badges": {},
            "orbs": {
                "Xenos": {"Legendary": 10, "Mythic": 10},
            },
        },
        "units": [
            {
                "id": "epicCap",
                "name": "Epic Cap",
                "grand_alliance": "Xenos",
                "progression_index": 11,
                "xp_level": 35,
                "shards": 100,
                "mythic_shards": 0,
                "abilities": [],
            },
            {
                "id": "legendaryStart",
                "name": "Legendary Start",
                "grand_alliance": "Xenos",
                "progression_index": 12,
                "xp_level": 36,
                "shards": 150,
                "mythic_shards": 0,
                "abilities": [],
            },
            {
                "id": "legendaryCap",
                "name": "Legendary Cap",
                "grand_alliance": "Xenos",
                "progression_index": 15,
                "xp_level": 50,
                "shards": 0,
                "mythic_shards": 20,
                "abilities": [],
            },
        ],
    }

    result = generate_candidate_actions(normalized, models, {})
    progression_actions = [
        action for action in result["actions"] if action["type"] != "ability_level"
    ]

    assert [(action["id"], action["progression"]["target_label"]) for action in progression_actions] == [
        ("ascension:epicCap:12", "Legendary 8 Stars"),
        ("ascension:legendaryCap:16", "Mythic 11 Stars"),
        ("promotion:legendaryStart:13", "9 Stars"),
    ]
    mythic_costs = progression_actions[1]["costs"]
    assert mythic_costs[0]["resource"] == "mythic_character_shard"
    assert mythic_costs[1]["rarity"] == "Mythic"
