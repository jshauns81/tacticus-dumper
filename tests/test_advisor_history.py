from advisor.history import compare_player_snapshots, compare_recommendation_queues


def progression_models():
    return {
        "testProgression": {
            "action_type": "unit_progression",
            "steps": [
                {
                    "current_progression_index": 2,
                    "target_progression_index": 3,
                    "target_label": "Uncommon 2 Stars",
                    "action_type": "ascension",
                }
            ],
        }
    }


def unit(
    character_id,
    name,
    *,
    progression_index,
    rank,
    xp_level,
    ability_level,
    shards,
):
    return {
        "id": character_id,
        "name": name,
        "progression_index": progression_index,
        "rank": rank,
        "xp_level": xp_level,
        "abilities": [{"id": "Doom", "level": ability_level}],
        "shards": shards,
        "mythic_shards": 0,
    }


def test_compares_progression_unlocks_and_net_resource_changes():
    before = {
        "name": "History Tester",
        "power_level": 100,
        "source": {"filename": "player_before.json", "imported_at": "before"},
        "units": [
            unit(
                "eldarFarseer",
                "Eldryon",
                progression_index=2,
                rank=1,
                xp_level=8,
                ability_level=7,
                shards=20,
            )
        ],
        "inventory": {
            "ability_badges": {"Xenos": {"Common": 5}},
            "orbs": {"Xenos": {"Uncommon": 10}},
            "shards": {"tauCrisis": 40},
            "mythic_shards": {},
        },
    }
    after = {
        "name": "History Tester",
        "power_level": 150,
        "source": {"filename": "player_after.json", "imported_at": "after"},
        "units": [
            unit(
                "eldarFarseer",
                "Eldryon",
                progression_index=3,
                rank=2,
                xp_level=9,
                ability_level=8,
                shards=5,
            ),
            unit(
                "tauCrisis",
                "Re'vas",
                progression_index=3,
                rank=0,
                xp_level=1,
                ability_level=1,
                shards=0,
            ),
        ],
        "inventory": {
            "ability_badges": {"Xenos": {"Common": 3}},
            "orbs": {"Xenos": {"Uncommon": 0}},
            "shards": {"tauCrisis": 0},
            "mythic_shards": {},
        },
    }

    result = compare_player_snapshots(before, after, progression_models())

    assert result["summary"] == {
        "power_delta": 50,
        "unit_count_delta": 1,
        "unlocked_characters": 1,
        "missing_characters": 0,
        "events": 6,
        "resource_changes": 3,
    }
    assert [event["type"] for event in result["events"]] == [
        "unlock",
        "rank_up",
        "ascension",
        "character_level",
        "ability_level",
        "resource_change",
    ]
    assert result["events"][2]["target_label"] == "Uncommon 2 Stars"
    assert result["resource_changes"] == [
        {
            "resource": "ability_badge",
            "alliance": "Xenos",
            "rarity": "Common",
            "before": 5,
            "after": 3,
            "delta": -2,
        },
        {
            "resource": "orb",
            "alliance": "Xenos",
            "rarity": "Uncommon",
            "before": 10,
            "after": 0,
            "delta": -10,
        },
        {
            "resource": "unowned_character_shard",
            "character_id": "tauCrisis",
            "before": 40,
            "after": 0,
            "delta": -40,
        },
    ]


def test_reports_missing_character_without_inferring_a_cause():
    before = {
        "name": "History Tester",
        "power_level": 1,
        "source": {"filename": "before", "imported_at": None},
        "units": [
            unit(
                "missing",
                "Missing",
                progression_index=0,
                rank=0,
                xp_level=1,
                ability_level=1,
                shards=0,
            )
        ],
        "inventory": {},
    }
    after = {
        "name": "History Tester",
        "power_level": 1,
        "source": {"filename": "after", "imported_at": None},
        "units": [],
        "inventory": {},
    }

    result = compare_player_snapshots(before, after, progression_models())

    assert result["events"] == [
        {
            "type": "character_missing",
            "character": {"id": "missing", "name": "Missing"},
        }
    ]


def recommendation_project(action_id, character_id, score):
    action = {
        "id": action_id,
        "type": "ability_level",
        "character": {"id": character_id, "name": character_id.title()},
        "ability": {"id": "Doom", "current_level": 19, "target_level": 20},
    }
    return {"action": action, "score": score}


def test_compares_added_removed_and_retained_advisor_projects():
    before = {
        "status": "projects_ready",
        "projects": [
            recommendation_project("action:a", "alpha", 80),
            recommendation_project("action:b", "beta", 70),
        ],
        "alternatives": [
            {"action_id": "action:c", "reason": "lower_score"},
        ],
    }
    after = {
        "status": "projects_ready",
        "projects": [
            recommendation_project("action:c", "gamma", 90),
            recommendation_project("action:a", "alpha", 85),
        ],
        "alternatives": [
            {"action_id": "action:b", "reason": "character_project_limit"},
        ],
    }

    result = compare_recommendation_queues(before, after)

    assert result["status"] == "changed"
    assert result["added"][0]["action_id"] == "action:c"
    assert result["added"][0]["reason"] == "promoted_from_alternative"
    assert result["removed"][0]["action_id"] == "action:b"
    assert result["removed"][0]["reason"] == (
        "reprioritized:character_project_limit"
    )
    assert result["retained"] == [
        {
            "action_id": "action:a",
            "type": "ability_level",
            "character": {"id": "alpha", "name": "Alpha"},
            "before_score": 80,
            "after_score": 85,
            "score_delta": 5,
            "action": before["projects"][0]["action"],
        }
    ]


def test_reports_unchanged_empty_advisor_queue():
    result = compare_recommendation_queues(
        {"status": "no_supported_project_ready", "projects": [], "alternatives": []},
        {"status": "no_supported_project_ready", "projects": [], "alternatives": []},
    )

    assert result["status"] == "unchanged"
    assert result["added"] == []
    assert result["removed"] == []
    assert result["retained"] == []
