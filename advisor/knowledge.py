"""Load and validate versioned Tacticus strategy knowledge."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


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


def validate_document(document: dict[str, Any], schema: dict[str, Any]) -> None:
    """Validate a knowledge document against a JSON Schema document."""
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
    if not errors:
        return

    messages = []
    for error in errors:
        location = ".".join(str(part) for part in error.path) or "<root>"
        messages.append(f"{location}: {error.message}")
    raise KnowledgeError("Knowledge validation failed: " + "; ".join(messages))


def load_character_knowledge(knowledge_dir: Path) -> dict[str, dict[str, Any]]:
    """Load all validated character knowledge files keyed by stable character ID."""
    schema_path = knowledge_dir / "schema" / "character.schema.json"
    character_dir = knowledge_dir / "characters"
    schema = load_json(schema_path)

    records: dict[str, dict[str, Any]] = {}
    if not character_dir.exists():
        return records

    for path in sorted(character_dir.glob("*.json")):
        document = load_json(path)
        validate_document(document, schema)
        character_id = document["id"]
        if character_id in records:
            raise KnowledgeError(f"Duplicate character knowledge ID: {character_id}")
        records[character_id] = document
    return records
