"""Load and validate versioned Tacticus strategy knowledge."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource


KNOWLEDGE_COLLECTIONS = {
    "characters": ("character.schema.json", "character"),
    "abilities": ("ability.schema.json", "ability"),
    "effects": ("effect.schema.json", "effect"),
    "modes": ("mode.schema.json", "mode"),
    "encounters": ("encounter.schema.json", "encounter"),
    "team_archetypes": ("team-archetype.schema.json", "team archetype"),
    "progression_models": ("progression-model.schema.json", "progression model"),
    "scoring_models": ("scoring-model.schema.json", "scoring model"),
}


class KnowledgeError(ValueError):
    """Raised when a knowledge document cannot be loaded or validated."""


def load_json(path: Path) -> dict[str, Any]:
    """Load one JSON object with a useful error message."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise KnowledgeError(f"Could not read knowledge file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise KnowledgeError(f"Knowledge file is invalid JSON: {path}") from exc

    if not isinstance(payload, dict):
        raise KnowledgeError(f"Knowledge file must contain a JSON object: {path}")
    return payload


def validate_document(
    document: dict[str, Any],
    schema: dict[str, Any],
    *,
    registry: Registry | None = None,
) -> None:
    """Validate a knowledge document against a JSON Schema document."""
    if registry is None:
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
    else:
        validator = Draft202012Validator(
            schema,
            format_checker=FormatChecker(),
            registry=registry,
        )
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
    if not errors:
        return

    messages = []
    for error in errors:
        location = ".".join(str(part) for part in error.path) or "<root>"
        messages.append(f"{location}: {error.message}")
    raise KnowledgeError("Knowledge validation failed: " + "; ".join(messages))


def load_schema_catalog(knowledge_dir: Path) -> tuple[dict[str, dict[str, Any]], Registry]:
    """Load and register every local knowledge schema."""
    schemas: dict[str, dict[str, Any]] = {}
    resources: list[tuple[str, Resource]] = []
    for path in sorted((knowledge_dir / "schema").glob("*.schema.json")):
        schema = load_json(path)
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            raise KnowledgeError(f"Knowledge schema is invalid: {path}: {exc.message}") from exc

        schema_id = schema.get("$id")
        if not isinstance(schema_id, str) or not schema_id:
            raise KnowledgeError(f"Knowledge schema is missing $id: {path}")
        schemas[path.name] = schema
        resources.append((schema_id, Resource.from_contents(schema)))

    registry = Registry().with_resources(resources)
    return schemas, registry


def _load_collection(
    knowledge_dir: Path,
    collection: str,
    schemas: dict[str, dict[str, Any]],
    registry: Registry,
) -> dict[str, dict[str, Any]]:
    schema_filename, record_label = KNOWLEDGE_COLLECTIONS[collection]
    try:
        schema = schemas[schema_filename]
    except KeyError as exc:
        raise KnowledgeError(f"Knowledge schema is missing: {schema_filename}") from exc

    records: dict[str, dict[str, Any]] = {}
    collection_dir = knowledge_dir / collection
    if not collection_dir.exists():
        return records

    for path in sorted(collection_dir.glob("*.json")):
        document = load_json(path)
        validate_document(document, schema, registry=registry)
        record_id = document["id"]
        if record_id in records:
            raise KnowledgeError(f"Duplicate {record_label} knowledge ID: {record_id}")
        records[record_id] = document
    return records


def load_knowledge_collection(
    knowledge_dir: Path, collection: str
) -> dict[str, dict[str, Any]]:
    """Load one supported knowledge collection keyed by stable record ID."""
    if collection not in KNOWLEDGE_COLLECTIONS:
        raise KnowledgeError(f"Unsupported knowledge collection: {collection}")
    schemas, registry = load_schema_catalog(knowledge_dir)
    return _load_collection(knowledge_dir, collection, schemas, registry)


def load_character_knowledge(knowledge_dir: Path) -> dict[str, dict[str, Any]]:
    """Load all validated character knowledge files keyed by stable character ID."""
    return load_knowledge_collection(knowledge_dir, "characters")


def _require_references(
    records: dict[str, dict[str, dict[str, Any]]],
    *,
    source_collection: str,
    source_id: str,
    field: str,
    values: list[str],
    target_collection: str,
) -> None:
    missing = sorted(set(values) - records[target_collection].keys())
    if missing:
        missing_list = ", ".join(missing)
        raise KnowledgeError(
            f"Unknown {target_collection} reference in "
            f"{source_collection}.{source_id}.{field}: {missing_list}"
        )


def validate_knowledge_references(
    records: dict[str, dict[str, dict[str, Any]]],
) -> None:
    """Validate typed relationships between loaded knowledge documents."""
    for character_id, character in records["characters"].items():
        _require_references(
            records,
            source_collection="characters",
            source_id=character_id,
            field="abilities",
            values=character.get("abilities", []),
            target_collection="abilities",
        )
        mode_ids = [
            evaluation["mode"] for evaluation in character.get("mode_evaluations", [])
        ]
        mode_ids.extend(
            mode_id
            for breakpoint in character.get("breakpoints", [])
            for mode_id in breakpoint.get("modes", [])
        )
        _require_references(
            records,
            source_collection="characters",
            source_id=character_id,
            field="mode references",
            values=mode_ids,
            target_collection="modes",
        )

    for ability_id, ability in records["abilities"].items():
        for field in ("produces_effects", "consumes_effects"):
            _require_references(
                records,
                source_collection="abilities",
                source_id=ability_id,
                field=field,
                values=ability.get(field, []),
                target_collection="effects",
            )

    for model_id, model in records["scoring_models"].items():
        _require_references(
            records,
            source_collection="scoring_models",
            source_id=model_id,
            field="mode_id",
            values=[model["mode_id"]],
            target_collection="modes",
        )
        _require_references(
            records,
            source_collection="scoring_models",
            source_id=model_id,
            field="team_archetype_id",
            values=[model["team_archetype_id"]],
            target_collection="team_archetypes",
        )

    for effect_id, effect in records["effects"].items():
        _require_references(
            records,
            source_collection="effects",
            source_id=effect_id,
            field="producer_ability_ids",
            values=effect.get("producer_ability_ids", []),
            target_collection="abilities",
        )
        _require_references(
            records,
            source_collection="effects",
            source_id=effect_id,
            field="beneficiary_character_ids",
            values=effect.get("beneficiary_character_ids", []),
            target_collection="characters",
        )

    for encounter_id, encounter in records["encounters"].items():
        _require_references(
            records,
            source_collection="encounters",
            source_id=encounter_id,
            field="mode_id",
            values=[encounter["mode_id"]],
            target_collection="modes",
        )
        _require_references(
            records,
            source_collection="encounters",
            source_id=encounter_id,
            field="counter_effect_ids",
            values=encounter.get("counter_effect_ids", []),
            target_collection="effects",
        )

    for archetype_id, archetype in records["team_archetypes"].items():
        _require_references(
            records,
            source_collection="team_archetypes",
            source_id=archetype_id,
            field="mode_ids",
            values=archetype["mode_ids"],
            target_collection="modes",
        )
        _require_references(
            records,
            source_collection="team_archetypes",
            source_id=archetype_id,
            field="enabling_effect_ids",
            values=archetype.get("enabling_effect_ids", []),
            target_collection="effects",
        )

        declared_roles = set(archetype["required_roles"])
        declared_roles.update(archetype.get("optional_roles", []))
        for role, character_ids in archetype.get("candidates_by_role", {}).items():
            if role not in declared_roles:
                raise KnowledgeError(
                    f"Undeclared candidate role in team_archetypes.{archetype_id}: {role}"
                )
            _require_references(
                records,
                source_collection="team_archetypes",
                source_id=archetype_id,
                field=f"candidates_by_role.{role}",
                values=character_ids,
                target_collection="characters",
            )
            for character_id in character_ids:
                if role not in records["characters"][character_id].get("roles", []):
                    raise KnowledgeError(
                        f"Character {character_id} does not declare candidate role {role} "
                        f"for team_archetypes.{archetype_id}"
                    )


def validate_knowledge_repository(
    knowledge_dir: Path,
) -> dict[str, dict[str, dict[str, Any]]]:
    """Validate every supported knowledge document in a repository tree."""
    schemas, registry = load_schema_catalog(knowledge_dir)
    records = {
        collection: _load_collection(knowledge_dir, collection, schemas, registry)
        for collection in KNOWLEDGE_COLLECTIONS
    }

    schema_dir = knowledge_dir / "schema"
    supported_files = {
        path
        for collection in KNOWLEDGE_COLLECTIONS
        for path in (knowledge_dir / collection).glob("*.json")
    }
    data_files = {
        path
        for path in knowledge_dir.rglob("*.json")
        if not path.is_relative_to(schema_dir)
    }
    unsupported_files = sorted(data_files - supported_files)
    if unsupported_files:
        names = ", ".join(str(path.relative_to(knowledge_dir)) for path in unsupported_files)
        raise KnowledgeError(f"Unsupported knowledge document location: {names}")

    validate_knowledge_references(records)
    return records
