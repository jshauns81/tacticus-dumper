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

    return records
