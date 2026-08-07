from copy import deepcopy
from pathlib import Path

import pytest

from advisor.knowledge import validate_knowledge_repository
from advisor.scoring import ActionScoringError, score_guild_raid_actions


def knowledge():
    return validate_knowledge_repository(Path("knowledge"))


def candidate_result(actions):
    return {
        "source": {"filename": "player_test.json", "imported_at": None},
        "player": {"name": "Scoring Tester", "power_level": 1, "unit_count": 2},
        "actions": actions,
    }


def ability_action(character_id, character_name, ability_id, *, target_level=20):
    return {
        "id": f"ability_level:{character_id}:{ability_id}:{target_level}",
        "type": "ability_level",
        "character": {"id": character_id, "name": character_name},
        "ability": {
            "id": ability_id,
            "current_level": target_level - 1,
            "target_level": target_level,
        },
        "prerequisites": [],
        "costs": [
            {
                "resource": "ability_badge",
                "alliance": "Xenos",
                "rarity": "Rare",
                "required": 3,
                "available": 5,
                "sufficient": True,
            },
            {
                "resource": "coins",
                "required": 1000,
                "available": None,
                "sufficient": None,
            },
        ],
        "availability": "possible_if_unreported_coins_sufficient",
    }


def test_scores_documented_role_actions_and_limits_one_project_per_character():
    normalized = {
        "units": [
            {"id": "eldarFarseer"},
            {"id": "tauCrisis"},
        ]
    }
    actions = [
        ability_action("eldarFarseer", "Eldryon", "Doom"),
        ability_action("eldarFarseer", "Eldryon", "Executioner"),
        ability_action("tauCrisis", "Re'vas", "CyclicIonBlaster"),
        {
            "id": "promotion:eldarFarseer:8",
            "type": "promotion",
            "character": {"id": "eldarFarseer", "name": "Eldryon"},
            "progression": {"target_label": "6 Stars"},
            "prerequisites": [],
            "costs": [],
            "availability": "ready",
        },
        ability_action("unknown", "Unknown", "unknownAbility"),
    ]

    result = score_guild_raid_actions(
        normalized, candidate_result(actions), knowledge()
    )

    assert [project["action"]["id"] for project in result["projects"]] == [
        "ability_level:eldarFarseer:Doom:20",
        "ability_level:tauCrisis:CyclicIonBlaster:20",
    ]
    assert result["status"] == "projects_ready"
    assert [project["score"] for project in result["projects"]] == [85, 85]
    assert [component["id"] for component in result["projects"][0]["components"]] == [
        "required_role",
        "role_aligned_ability",
        "conditional_resources",
        "complete_required_role_core",
    ]
    assert result["alternatives"] == [
        {
            "action_id": "promotion:eldarFarseer:8",
            "character": {"id": "eldarFarseer", "name": "Eldryon"},
            "score": 75,
            "reason": "character_project_limit",
        }
    ]
    assert result["counts"] == {
        "candidate_actions": 5,
        "scored_actions": 3,
        "returned_projects": 2,
        "excluded_actions": 2,
        "excluded_by_reason": {
            "undocumented_ability_role": 1,
            "unknown_character": 1,
        },
    }
    assert "does not report the available coin balance" in (
        result["projects"][0]["opportunity_costs"][1]
    )


def test_unlock_scores_when_it_completes_a_missing_required_role():
    normalized = {"units": [{"id": "eldarFarseer"}]}
    unlock = {
        "id": "unlock:tauCrisis:3",
        "type": "unlock",
        "character": {"id": "tauCrisis", "name": "Re'vas"},
        "progression": {"target_label": "Uncommon Unlock"},
        "prerequisites": [],
        "costs": [
            {
                "resource": "character_shard",
                "required": 80,
                "available": 80,
                "sufficient": True,
            }
        ],
        "availability": "ready",
    }

    result = score_guild_raid_actions(
        normalized, candidate_result([unlock]), knowledge()
    )

    project = result["projects"][0]
    assert project["score"] == 80
    assert [component["id"] for component in project["components"]] == [
        "required_role",
        "unlock_missing_required_role",
        "ready",
        "complete_required_role_core",
    ]


def test_returns_explicit_status_when_known_characters_have_no_ready_action():
    normalized = {
        "units": [
            {"id": "eldarFarseer"},
            {"id": "tauCrisis"},
        ]
    }

    result = score_guild_raid_actions(
        normalized, candidate_result([]), knowledge()
    )

    assert result["status"] == "no_supported_project_ready"
    assert result["projects"] == []
    assert result["message"] == (
        "No resource-ready or conditionally-ready action is available for the "
        "currently known Guild Raid characters. Refresh after roster or inventory changes."
    )
    assert result["coverage"]["known_owned_characters"] == [
        {"id": "eldarFarseer", "name": "Eldryon", "candidate_actions": 0},
        {"id": "tauCrisis", "name": "Re'vas", "candidate_actions": 0},
    ]


def test_rejects_ambiguous_scoring_policy():
    records = knowledge()
    records = deepcopy(records)
    records["scoring_models"]["duplicate"] = dict(
        records["scoring_models"]["guildRaidCoreV1"], id="duplicate"
    )

    with pytest.raises(ActionScoringError, match="exactly one"):
        score_guild_raid_actions(
            {"units": []}, candidate_result([]), records
        )
