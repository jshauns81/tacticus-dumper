import json
from pathlib import Path

import pytest

from advisor.knowledge import (
    KnowledgeError,
    load_character_knowledge,
    validate_document,
    validate_knowledge_repository,
)


VALID_CHARACTER = {
    "schema_version": 1,
    "knowledge_version": "2026.08.05",
    "effective_from": "2026-08-05",
    "last_reviewed": "2026-08-05",
    "id": "exampleCharacter",
    "name": "Example Character",
    "faction_id": "ExampleFaction",
    "alliance_id": "Imperial",
    "abilities": ["exampleActive", "examplePassive"],
    "traits": [],
    "roles": ["support"],
    "mode_evaluations": [],
    "breakpoints": [],
    "sources": [
        {
            "type": "observed_player_data",
            "reference": "sanitized test fixture"
        }
    ]
}


def write_schema(root: Path) -> None:
    repository_schema = Path("knowledge/schema/character.schema.json")
    target = root / "schema" / "character.schema.json"
    target.parent.mkdir(parents=True)
    target.write_text(repository_schema.read_text(encoding="utf-8"), encoding="utf-8")


def test_loads_valid_character_knowledge(tmp_path: Path):
    write_schema(tmp_path)
    character_dir = tmp_path / "characters"
    character_dir.mkdir()
    (character_dir / "example.json").write_text(
        json.dumps(VALID_CHARACTER), encoding="utf-8"
    )

    records = load_character_knowledge(tmp_path)

    assert list(records) == ["exampleCharacter"]
    assert records["exampleCharacter"]["roles"] == ["support"]


def test_rejects_invalid_alliance(tmp_path: Path):
    write_schema(tmp_path)
    character_dir = tmp_path / "characters"
    character_dir.mkdir()
    invalid = dict(VALID_CHARACTER)
    invalid["alliance_id"] = "UnknownAlliance"
    (character_dir / "invalid.json").write_text(json.dumps(invalid), encoding="utf-8")

    with pytest.raises(KnowledgeError, match="alliance_id"):
        load_character_knowledge(tmp_path)


def test_rejects_duplicate_character_ids(tmp_path: Path):
    write_schema(tmp_path)
    character_dir = tmp_path / "characters"
    character_dir.mkdir()
    for filename in ("one.json", "two.json"):
        (character_dir / filename).write_text(
            json.dumps(VALID_CHARACTER), encoding="utf-8"
        )

    with pytest.raises(KnowledgeError, match="Duplicate character knowledge ID"):
        load_character_knowledge(tmp_path)


def test_reports_schema_errors():
    schema = {
        "type": "object",
        "required": ["name"],
        "properties": {"name": {"type": "string"}}
    }

    with pytest.raises(KnowledgeError, match="name"):
        validate_document({}, schema)


def test_repository_knowledge_is_valid():
    records = validate_knowledge_repository(Path("knowledge"))

    assert records == {"characters": {}}


def test_repository_validation_rejects_unhandled_json(tmp_path: Path):
    write_schema(tmp_path)
    unsupported_dir = tmp_path / "unhandled"
    unsupported_dir.mkdir()
    (unsupported_dir / "entry.json").write_text("{}", encoding="utf-8")

    with pytest.raises(KnowledgeError, match="unhandled/entry.json"):
        validate_knowledge_repository(tmp_path)
