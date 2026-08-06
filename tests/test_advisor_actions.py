from advisor.actions import ActionModelError, generate_candidate_actions


def ability_cost_model():
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
        }
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
            }
        },
        "units": [
            {
                "id": "zeta",
                "name": "Zeta",
                "grand_alliance": "Xenos",
                "xp_level": 8,
                "abilities": [
                    {"id": "zetaActive", "level": 7},
                    {"id": "zetaPassive", "level": 7},
                ],
            },
            {
                "id": "alpha",
                "name": "Alpha",
                "grand_alliance": "Xenos",
                "xp_level": 10,
                "abilities": [
                    {"id": "alphaActive", "level": 8},
                    {"id": "alphaPassive", "level": 8},
                ],
            },
            {
                "id": "blocked",
                "name": "Blocked",
                "grand_alliance": "Imperial",
                "xp_level": 10,
                "abilities": [
                    {"id": "atCap", "level": 10},
                    {"id": "needsBadge", "level": 8},
                ],
            },
        ],
    }


def test_generates_deterministic_actions_and_filters_known_blockers():
    result = generate_candidate_actions(normalized_player(), ability_cost_model())

    assert [action["id"] for action in result["actions"]] == [
        "ability_level:alpha:alphaActive:9",
        "ability_level:alpha:alphaPassive:9",
        "ability_level:zeta:zetaActive:8",
        "ability_level:zeta:zetaPassive:8",
    ]
    assert result["counts"] == {
        "returned": 4,
        "excluded": 2,
        "excluded_by_reason": {
            "ability_at_character_level": 1,
            "insufficient_ability_badges": 1,
            "unsupported_unit_ability_layout": 0,
            "unsupported_target_level": 0,
        },
    }


def test_reports_known_costs_and_marks_unreported_coins_unknown():
    result = generate_candidate_actions(normalized_player(), ability_cost_model())
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


def test_rejects_ambiguous_or_malformed_cost_models():
    models = ability_cost_model()
    models["duplicate"] = dict(models["testCosts"], id="duplicate")

    try:
        generate_candidate_actions(normalized_player(), models)
    except ActionModelError as exc:
        assert "exactly one" in str(exc)
    else:
        raise AssertionError("Expected an ambiguous model to be rejected")

    malformed = ability_cost_model()
    malformed["testCosts"]["level_bands"][0]["badge_costs"] = [1]
    try:
        generate_candidate_actions(normalized_player(), malformed)
    except ActionModelError as exc:
        assert "unequal cost arrays" in str(exc)
    else:
        raise AssertionError("Expected unequal cost arrays to be rejected")
