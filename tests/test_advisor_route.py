import json
import os
from pathlib import Path

import pytest

import app as app_module
from advisor.parser import normalize_player, summarize_roster


def sample_payload():
    return {
        "player": {
            "details": {"name": "Route Test Commander", "powerLevel": 21},
            "inventory": {
                "abilityBadges": {
                    "Test Alliance": [
                        {"name": "Uncommon Badge", "rarity": "Uncommon", "amount": 2}
                    ]
                }
            },
            "units": [
                {
                    "id": "testUnit",
                    "name": "Test Unit",
                    "faction": "Test Faction",
                    "grandAlliance": "Test Alliance",
                    "progressionIndex": 7,
                    "xpLevel": 12,
                    "rank": 3,
                    "abilities": [
                        {"id": "testAbility", "level": 11},
                        {"id": "testPassive", "level": 11},
                    ],
                    "items": [],
                    "shards": 125,
                    "mythicShards": 0,
                }
            ],
        }
    }


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    dumps_dir = tmp_path / "dumps"
    dumps_dir.mkdir()
    monkeypatch.setattr(app_module, "DUMPS_DIR", dumps_dir)
    app_module.app.config.update(TESTING=True)
    with app_module.app.test_client() as test_client:
        yield test_client, dumps_dir


def test_advisor_summary_uses_latest_player_dump(client):
    test_client, dumps_dir = client
    payload = sample_payload()
    dump = dumps_dir / "player_20260805_120000.json"
    dump.write_text(
        json.dumps(payload), encoding="utf-8"
    )
    import_timestamp = 1_700_000_000
    os.utime(dump, (import_timestamp, import_timestamp))

    response = test_client.get("/api/advisor/summary")

    assert response.status_code == 200
    assert response.get_json() == summarize_roster(
        normalize_player(payload, source_path=dump)
    )
    assert response.get_json()["source"] == {
        "filename": "player_20260805_120000.json",
        "imported_at": "2023-11-14T22:13:20Z",
    }


def test_advisor_summary_returns_404_when_no_dump_exists(client):
    test_client, _ = client

    response = test_client.get("/api/advisor/summary")

    assert response.status_code == 404
    assert response.get_json() == {
        "ok": False,
        "error": "No player_*.json dumps were found.",
    }


def test_advisor_summary_returns_422_for_malformed_json(client):
    test_client, dumps_dir = client
    (dumps_dir / "player_20260805_120000.json").write_text(
        '{"player":', encoding="utf-8"
    )

    response = test_client.get("/api/advisor/summary")

    assert response.status_code == 422
    assert response.get_json() == {
        "ok": False,
        "error": "Latest player dump is invalid JSON: player_20260805_120000.json",
    }


def test_advisor_summary_returns_422_for_invalid_player_structure(client):
    test_client, dumps_dir = client
    (dumps_dir / "player_20260805_120000.json").write_text(
        json.dumps({"guild": {}}), encoding="utf-8"
    )

    response = test_client.get("/api/advisor/summary")

    assert response.status_code == 422
    assert response.get_json() == {
        "ok": False,
        "error": "Invalid player structure: Player dump does not contain a player object.",
    }


def test_advisor_actions_returns_supported_unranked_actions(client):
    test_client, dumps_dir = client
    payload = sample_payload()
    dump = dumps_dir / "player_20260805_120000.json"
    dump.write_text(json.dumps(payload), encoding="utf-8")

    response = test_client.get("/api/advisor/actions")

    assert response.status_code == 200
    result = response.get_json()
    assert result["coverage"] == {
        "supported_action_types": [
            "ability_level",
            "ascension",
            "promotion",
            "rank",
            "unlock",
        ],
        "pending_action_types": ["equipment"],
        "unreported_resources": ["coins"],
        "evaluation": "Each action is evaluated independently, not as a combined spend plan.",
        "unlock_knowledge": {
            "known_characters": 2,
            "unmapped_unowned_shard_records": 0,
        },
    }
    assert result["counts"]["returned"] == 3
    assert result["actions"][0]["id"] == "ability_level:testUnit:testAbility:12"
    assert result["actions"][0]["costs"] == [
        {
            "resource": "ability_badge",
            "alliance": "Test Alliance",
            "rarity": "Uncommon",
            "required": 2,
            "available": 2,
            "sufficient": True,
        },
        {
            "resource": "coins",
            "required": 800,
            "available": None,
            "sufficient": None,
        },
    ]
    assert result["actions"][2]["id"] == "promotion:testUnit:8"
    assert result["actions"][2]["availability"] == "ready"


def test_advisor_actions_returns_404_when_no_dump_exists(client):
    test_client, _ = client

    response = test_client.get("/api/advisor/actions")

    assert response.status_code == 404
    assert response.get_json()["error"] == "No player_*.json dumps were found."


def test_advisor_actions_returns_422_for_malformed_json(client):
    test_client, dumps_dir = client
    (dumps_dir / "player_20260805_120000.json").write_text(
        '{"player":', encoding="utf-8"
    )

    response = test_client.get("/api/advisor/actions")

    assert response.status_code == 422
    assert response.get_json()["error"] == (
        "Latest player dump is invalid JSON: player_20260805_120000.json"
    )
