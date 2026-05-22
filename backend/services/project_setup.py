"""
Project setup utilities (manual entity entry — no external API call).

Builds the on-disk project data structure and provides helpers to pre-seed
entity lists from comma-separated user inputs (subsidiaries, contacts).
"""

from __future__ import annotations

import re
from datetime import datetime


def _slugify(text: str) -> str:
    """Convert text to a URL-friendly slug."""
    text = text.lower().strip()
    text = re.sub(r'[àâäã]', 'a', text)
    text = re.sub(r'[éèêë]', 'e', text)
    text = re.sub(r'[îï]', 'i', text)
    text = re.sub(r'[ôö]', 'o', text)
    text = re.sub(r'[ùûü]', 'u', text)
    text = re.sub(r'[ç]', 'c', text)
    text = re.sub(r'[^a-z0-9]+', '-', text)
    text = text.strip('-')
    return text


# Minimum length per category (characters)
_MIN_LENGTHS = {
    "entreprises": 3,
    "personnes": 3,
    "lieux": 3,
    "autres": 3,
}


def sanitize_entities(entities: dict[str, list[str]]) -> dict[str, list[str]]:
    """Remove entities that are too short or likely to cause false positives."""
    result = {}
    for category, items in entities.items():
        min_len = _MIN_LENGTHS.get(category, 3)
        filtered = []
        for item in items:
            stripped = item.strip()
            if len(stripped) < min_len:
                continue
            clean = stripped.replace(".", "").replace(" ", "")
            if re.fullmatch(r'[A-ZÀ-Ü]+', clean) and len(clean) <= 2:
                continue
            if category == "personnes" and " " not in stripped and "." not in stripped:
                if len(stripped) < 5:
                    continue
            if re.fullmatch(r'[A-ZÀ-Ü]{1,3}', stripped):
                continue
            filtered.append(stripped)
        # Deduplicate while preserving order
        seen = set()
        deduped = []
        for it in filtered:
            key = it.lower()
            if key not in seen:
                seen.add(key)
                deduped.append(it)
        result[category] = deduped
    return result


def _expand_person_variants(full_name: str) -> list[str]:
    """Generate common written variants of a person's name."""
    parts = full_name.strip().split()
    if len(parts) < 2:
        return [full_name.strip()]
    first, last = parts[0], " ".join(parts[1:])
    variants = [
        f"{first} {last}",
        f"{last.upper()} {first}",
        f"{first[0]}. {last}",
    ]
    return variants


def seed_entities(
    client_name: str,
    subsidiaries: str = "",
    contacts: str = "",
) -> dict[str, list[str]]:
    """Build a starter entity dict from the project creation form.

    The user is expected to review and enrich the lists in the entity editor.
    """
    entities: dict[str, list[str]] = {
        "entreprises": [],
        "personnes": [],
        "lieux": [],
        "autres": [],
    }

    if client_name.strip():
        entities["entreprises"].append(client_name.strip())

    for sub in (subsidiaries or "").split(","):
        sub = sub.strip()
        if sub:
            entities["entreprises"].append(sub)

    for contact in (contacts or "").split(","):
        contact = contact.strip()
        if contact:
            entities["personnes"].extend(_expand_person_variants(contact))

    return sanitize_entities(entities)


def build_project_data(
    project_name: str,
    client_name: str,
    entities: dict[str, list[str]],
    logo_hashes: list[str] | None = None,
) -> dict:
    """Build the full project data structure for saving."""
    slug = _slugify(project_name)
    return {
        "id": slug,
        "name": project_name,
        "client": client_name,
        "created_at": datetime.now().isoformat(),
        "entities": entities,
        "logo_hashes": logo_hashes or [],
    }
