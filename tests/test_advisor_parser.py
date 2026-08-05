import json
from pathlib import Path

import pytest

from advisor.parser import load_latest_player_dump, normalize_player, summarize_roster


def sample_payload():
    return {
        "player": {
            "details": {"name": "Test Commander", "powerLevel": 44},
            "units": [
                {
                    "id": "eldarFarseer",
                    "name": "Eldryon",
                    "faction": "Aeldari",
                    "grandAlliance": "Xenos",
                    "progressionIndex": 13,
                    "xpLevel": 33,
                    "rank": 10,
                    "abilities": [{"id": "Executioner", "level": 33}, {"id": "Doom", "level": 33}],
                    "items": [{"slotId": "Slot1"}],
                    "shards": 181,
                    "mythicShards": 0,
                },
                {
                    "id": "bloodIntercessor",
                    "name": "Mataneo",
                    "faction": "BloodAngels",
                    "grandAlliance": "Imperial",
                    "progressionIndex": 8,
                    "xpLevel": 15,
                    "rank": 1,
                    "abilities": [{"id": "HammerOfWrath", "level": 9}, {"id": "AggressiveOnslaught", "level": 8}],
                    "items": [],
                    "shards": 453,
                    "mythicShards": 0,
                },
            ],
        }
    }


def test_normalize_and_summarize_player():
    normalized = normalize_player(sample_payload())
    summary = summarize_roster(normalized)

    assert normalized["name"] == "Test Commander"
    assert normalized["unit_count"] == 2
    assert summary["top_invested"][0]["name"] == "Eldryon"
    assert summary["promotion_candidates"][0]["name"] == "Mataneo"
    assert summary["developed_but_low_rank"][0]["name"] == "Mataneo"
    assert summary["faction_counts"] == {"Aeldari": 1, "BloodAngels": 1}


def test_load_latest_player_dump(tmp_path: Path):
    old_dump = tmp_path / "player_20260801_000000.json"
    new_dump = tmp_path / "player_20260805_000000.json"
    old_dump.write_text(json.dumps({"old": True}), encoding="utf-8")
    new_dump.write_text(json.dumps(sample_payload()), encoding="utf-8")
    old_dump.touch()
    new_dump.touch()
    old_dump.chmod(0o600)
    new_dump.chmod(0o600)
    old_dump_mtime = 1_700_000_000
    new_dump_mtime = old_dump_mtime + 60
    import os
    os.utime(old_dump, (old_dump_mtime, old_dump_mtime))
    os.utime(new_dump, (new_dump_mtime, new_dump_mtime))

    path, payload = load_latest_player_dump(tmp_path)

    assert path == new_dump
    assert payload["player"]["details"]["powerLevel"] == 44


def test_normalized_player_preserves_source_metadata(tmp_path: Path):
    dump = tmp_path / "player_20260805_120000.json"
    dump.write_text(json.dumps(sample_payload()), encoding="utf-8")
    import_timestamp = 1_700_000_000
    import os
    os.utime(dump, (import_timestamp, import_timestamp))

    normalized = normalize_player(sample_payload(), source_path=dump)
    summary = summarize_roster(normalized)

    assert normalized["source"] == {
        "filename": "player_20260805_120000.json",
        "imported_at": "2023-11-14T22:13:20Z",
    }
    assert summary["source"] == normalized["source"]


def test_missing_player_object_is_rejected():
    with pytest.raises(ValueError, match="player object"):
        normalize_player({"guild": {}})
