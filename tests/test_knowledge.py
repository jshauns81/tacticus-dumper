import json
from pathlib import Path

import pytest

from advisor.knowledge import (
    KnowledgeError,
    load_character_knowledge,
    load_knowledge_collection,
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
    "base_rarity": "Common",
    "abilities": ["exampleActive"],
    "traits": [],
    "roles": ["support", "damage"],
    "mode_evaluations": [],
    "breakpoints": [],
    "sources": [
        {
            "type": "observed_player_data",
            "reference": "sanitized test fixture"
        }
    ]
}


def knowledge_document(record_id: str, name: str, **fields):
    return {
        "schema_version": 1,
        "knowledge_version": "2026.08.05",
        "effective_from": "2026-08-05",
        "last_reviewed": "2026-08-05",
        "id": record_id,
        "name": name,
        **fields,
        "sources": [
            {
                "type": "observed_player_data",
                "reference": "sanitized test fixture",
            }
        ],
    }


VALID_DOCUMENTS = {
    "characters": VALID_CHARACTER,
    "abilities": knowledge_document(
        "exampleActive",
        "Example Active",
        ability_type="active",
        targets=["single_enemy"],
        mechanics=["damage"],
        produces_effects=["exampleDebuff"],
        consumes_effects=[],
        scaling_dimensions=["damage"],
        breakpoint_notes=[],
    ),
    "effects": knowledge_document(
        "exampleDebuff",
        "Example Debuff",
        effect_type="debuff",
        scope="single_enemy",
        duration="one round",
        stacking_rule="does not stack",
        producer_ability_ids=["exampleActive"],
        beneficiary_character_ids=[],
        beneficiary_roles=["damage"],
    ),
    "modes": knowledge_document(
        "exampleMode",
        "Example Mode",
        team_size=5,
        reuse_rule="unrestricted",
        restrictions=[],
        scoring_objectives=["deal damage"],
        resources_consumed=["exampleToken"],
    ),
    "encounters": knowledge_document(
        "exampleEncounter",
        "Example Encounter",
        mode_id="exampleMode",
        effective_game_version="example-version",
        restrictions=[],
        phases=[
            {"id": "phaseOne", "name": "Phase One", "mechanics": ["example"]}
        ],
        counter_effect_ids=["exampleDebuff"],
        scoring_considerations=["example consideration"],
    ),
    "team_archetypes": knowledge_document(
        "exampleTeam",
        "Example Team",
        mode_ids=["exampleMode"],
        required_roles=["damage"],
        optional_roles=["support"],
        enabling_effect_ids=["exampleDebuff"],
        exclusions=[],
        candidates_by_role={"damage": ["exampleCharacter"]},
    ),
    "progression_models": knowledge_document(
        "exampleAbilityCosts",
        "Example Ability Costs",
        action_type="ability_level",
        level_bands=[
            {
                "rarity": "Common",
                "first_target_level": 2,
                "coin_costs": [25],
                "badge_costs": [1],
            }
        ],
    ),
    "scoring_models": knowledge_document(
        "exampleScoring",
        "Example Scoring",
        mode_id="exampleMode",
        team_archetype_id="exampleTeam",
        max_projects=3,
        max_projects_per_character=1,
        weights={
            "required_role": 30,
            "optional_role": 10,
            "role_aligned_ability": 35,
            "general_progression": 20,
            "unlock_missing_required_role": 25,
            "ready": 10,
            "conditional_resources": 5,
            "complete_required_role_core": 15,
        },
    ),
}


def write_schemas(root: Path) -> None:
    target_dir = root / "schema"
    target_dir.mkdir(parents=True)
    for repository_schema in Path("knowledge/schema").glob("*.schema.json"):
        target = target_dir / repository_schema.name
        target.write_text(
            repository_schema.read_text(encoding="utf-8"), encoding="utf-8"
        )


def write_valid_documents(root: Path) -> None:
    for collection, document in VALID_DOCUMENTS.items():
        collection_dir = root / collection
        collection_dir.mkdir()
        (collection_dir / "example.json").write_text(
            json.dumps(document), encoding="utf-8"
        )


def test_loads_valid_character_knowledge(tmp_path: Path):
    write_schemas(tmp_path)
    character_dir = tmp_path / "characters"
    character_dir.mkdir()
    (character_dir / "example.json").write_text(
        json.dumps(VALID_CHARACTER), encoding="utf-8"
    )

    records = load_character_knowledge(tmp_path)

    assert list(records) == ["exampleCharacter"]
    assert records["exampleCharacter"]["roles"] == ["support", "damage"]


def test_rejects_invalid_alliance(tmp_path: Path):
    write_schemas(tmp_path)
    character_dir = tmp_path / "characters"
    character_dir.mkdir()
    invalid = dict(VALID_CHARACTER)
    invalid["alliance_id"] = "UnknownAlliance"
    (character_dir / "invalid.json").write_text(json.dumps(invalid), encoding="utf-8")

    with pytest.raises(KnowledgeError, match="alliance_id"):
        load_character_knowledge(tmp_path)


def test_rejects_duplicate_character_ids(tmp_path: Path):
    write_schemas(tmp_path)
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

    assert {collection: sorted(entries) for collection, entries in records.items()} == {
        "characters": ["eldarFarseer", "tauCrisis"],
        "abilities": [
            "CyclicIonBlaster",
            "Doom",
            "EarlyWarningOverride",
            "Executioner",
        ],
        "effects": ["doomNormalAttackAmplification"],
        "modes": ["guildRaid"],
        "encounters": [],
        "team_archetypes": ["doomMultiHitCore"],
        "progression_models": [
            "characterAbilityLevelCosts",
            "characterRanks",
            "characterUnlockCosts",
            "unitPromotionAscensionCosts",
        ],
        "scoring_models": ["guildRaidCoreV1"],
    }


def test_loads_every_supported_knowledge_collection(tmp_path: Path):
    write_schemas(tmp_path)
    write_valid_documents(tmp_path)

    records = validate_knowledge_repository(tmp_path)

    assert {
        collection: list(collection_records)
        for collection, collection_records in records.items()
    } == {
        collection: [document["id"]]
        for collection, document in VALID_DOCUMENTS.items()
    }


def test_shared_metadata_rules_apply_to_new_collections(tmp_path: Path):
    write_schemas(tmp_path)
    ability_dir = tmp_path / "abilities"
    ability_dir.mkdir()
    invalid = dict(VALID_DOCUMENTS["abilities"])
    invalid["last_reviewed"] = "not-a-date"
    (ability_dir / "invalid.json").write_text(json.dumps(invalid), encoding="utf-8")

    with pytest.raises(KnowledgeError, match="last_reviewed"):
        load_knowledge_collection(tmp_path, "abilities")


def test_rejects_unsupported_knowledge_collection(tmp_path: Path):
    with pytest.raises(KnowledgeError, match="Unsupported knowledge collection"):
        load_knowledge_collection(tmp_path, "unknown")


def test_repository_validation_rejects_unknown_references(tmp_path: Path):
    write_schemas(tmp_path)
    write_valid_documents(tmp_path)
    ability_path = tmp_path / "abilities" / "example.json"
    invalid = json.loads(ability_path.read_text(encoding="utf-8"))
    invalid["produces_effects"] = ["missingEffect"]
    ability_path.write_text(json.dumps(invalid), encoding="utf-8")

    with pytest.raises(
        KnowledgeError,
        match=r"abilities\.exampleActive\.produces_effects: missingEffect",
    ):
        validate_knowledge_repository(tmp_path)


def test_repository_validation_rejects_candidate_role_mismatch(tmp_path: Path):
    write_schemas(tmp_path)
    write_valid_documents(tmp_path)
    character_path = tmp_path / "characters" / "example.json"
    invalid = json.loads(character_path.read_text(encoding="utf-8"))
    invalid["roles"] = ["support"]
    character_path.write_text(json.dumps(invalid), encoding="utf-8")

    with pytest.raises(KnowledgeError, match="does not declare candidate role damage"):
        validate_knowledge_repository(tmp_path)


def test_repository_validation_rejects_unhandled_json(tmp_path: Path):
    write_schemas(tmp_path)
    unsupported_dir = tmp_path / "unhandled"
    unsupported_dir.mkdir()
    (unsupported_dir / "entry.json").write_text("{}", encoding="utf-8")

    with pytest.raises(KnowledgeError, match="unhandled/entry.json"):
        validate_knowledge_repository(tmp_path)
