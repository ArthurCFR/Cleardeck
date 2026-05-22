"""
Entity merger — V2 (GLiNER).

Merge, deduplicate, sort, and assign placeholders.
Two sources: project entities (exact) and AI-detected entities (GLiNER).
"""

from __future__ import annotations

from dataclasses import dataclass


# Category labels for placeholders
CATEGORY_LABELS = {
    "entreprises": "ENTREPRISE",
    "personnes": "PERSONNE",
    "lieux": "LIEU",
    "autres": "SENSIBLE",
    "alts": "ALT",
    "mails": "MAIL",
}


@dataclass
class EntityGroup:
    """A group of entity variants that map to the same placeholder."""
    placeholder: str
    category: str
    variants: list[str]
    source: str  # "project" or "ai"
    confidence: int | None


def merge_entities(
    project_entities: dict[str, list[str]] | None,
    ai_confirmed: list[dict] | None = None,
) -> tuple[list[tuple[str, str]], list[dict]]:
    """Merge entities from all sources into a sorted replacement list.

    Args:
        project_entities: dict of category -> list of entity strings from project
        ai_confirmed: list of AI-detected entity dicts with "entity" and "category"

    Returns:
        entities_sorted: list of (original, placeholder) sorted by len DESC
        mapping_entries: list of mapping dicts for the JSON output
    """
    project_entities = project_entities or {}
    ai_confirmed = ai_confirmed or []

    # Counter per category for placeholder numbering
    counters: dict[str, int] = {}
    # Track which normalized entities we've seen -> their placeholder
    seen_normalized: dict[str, str] = {}
    # All (original, placeholder) pairs
    all_pairs: list[tuple[str, str]] = []
    # Mapping entries for JSON output
    mapping_entries: list[dict] = []

    def _get_or_create_placeholder(entity: str, category: str) -> str:
        """Get existing placeholder for an entity or create a new one."""
        normalized = entity.lower().strip()
        if normalized in seen_normalized:
            return seen_normalized[normalized]

        label = CATEGORY_LABELS.get(category, "SENSIBLE")
        counters[label] = counters.get(label, 0) + 1
        placeholder = f"[{label}_{counters[label]}]"
        seen_normalized[normalized] = placeholder
        return placeholder

    def _assign_group_placeholder(variants: list[str], category: str) -> str:
        """Assign a single placeholder for a group of variants."""
        # Check if any variant already has a placeholder
        for v in variants:
            normalized = v.lower().strip()
            if normalized in seen_normalized:
                placeholder = seen_normalized[normalized]
                for v2 in variants:
                    seen_normalized[v2.lower().strip()] = placeholder
                return placeholder

        # Create new placeholder
        label = CATEGORY_LABELS.get(category, "SENSIBLE")
        counters[label] = counters.get(label, 0) + 1
        placeholder = f"[{label}_{counters[label]}]"
        for v in variants:
            seen_normalized[v.lower().strip()] = placeholder
        return placeholder

    # Layer 1: Project entities — group variants by category
    for category, entities in project_entities.items():
        if not entities:
            continue

        groups = _group_variants(entities)

        for group in groups:
            placeholder = _assign_group_placeholder(group, category)
            for entity in group:
                all_pairs.append((entity, placeholder))
                mapping_entries.append({
                    "original": entity,
                    "placeholder": placeholder,
                    "type": category.rstrip("s") if category.endswith("s") else category,
                    "source": "project",
                    "confidence": 100,
                })

    # Layer 2: AI-detected entities
    for ent in ai_confirmed:
        entity = ent["entity"]
        category = ent.get("category", "autres")
        normalized = entity.lower().strip()

        # Skip if already covered by project entities
        if normalized in seen_normalized:
            continue

        # Try to link to existing group via variant matching
        linked_placeholder = _find_variant_match(entity, seen_normalized)
        if linked_placeholder:
            placeholder = linked_placeholder
        else:
            placeholder = _get_or_create_placeholder(entity, category)

        seen_normalized[normalized] = placeholder
        all_pairs.append((entity, placeholder))
        mapping_entries.append({
            "original": entity,
            "placeholder": placeholder,
            "type": category.rstrip("s") if category.endswith("s") else category,
            "source": "ai",
            "confidence": int(ent.get("confidence", 0) * 100) if ent.get("confidence") else None,
        })

    # Sort by entity length descending (critical to avoid partial replacement)
    all_pairs.sort(key=lambda x: len(x[0]), reverse=True)

    # Deduplicate pairs (same original, same placeholder)
    seen_pairs = set()
    unique_pairs = []
    for original, placeholder in all_pairs:
        key = (original.lower(), placeholder)
        if key not in seen_pairs:
            seen_pairs.add(key)
            unique_pairs.append((original, placeholder))

    return unique_pairs, mapping_entries


def _find_variant_match(entity: str, seen: dict[str, str]) -> str | None:
    """Try to match an AI-detected entity to an existing project entity group.

    Checks if the entity is a substring of, or shares significant words with,
    an already-seen entity.
    """
    entity_lower = entity.lower().strip()
    entity_words = {w for w in entity_lower.split() if len(w) > 2}

    for seen_entity, placeholder in seen.items():
        # Substring match
        if entity_lower in seen_entity or seen_entity in entity_lower:
            return placeholder

        # Significant word overlap
        seen_words = {w for w in seen_entity.split() if len(w) > 2}
        if entity_words and seen_words:
            common = entity_words & seen_words
            if any(len(w) > 3 for w in common):
                return placeholder

    return None


def _group_variants(entities: list[str]) -> list[list[str]]:
    """Group entity strings that are likely variants of the same entity.

    Heuristics:
    - One entity is a substring of another (case-insensitive)
    - One entity is a "compressed" form (spaces/hyphens removed) of another
    - They share a significant common word (len > 2)
    """
    if not entities:
        return []

    def _normalize(s: str) -> str:
        return s.lower().replace(" ", "").replace("-", "").replace("'", "")

    sorted_entities = sorted(entities, key=len, reverse=True)
    groups: list[list[str]] = []
    assigned = set()

    for entity in sorted_entities:
        if entity in assigned:
            continue

        group = [entity]
        assigned.add(entity)
        entity_lower = entity.lower()
        entity_norm = _normalize(entity)

        for other in sorted_entities:
            if other in assigned:
                continue

            other_lower = other.lower()
            other_norm = _normalize(other)

            if other_lower in entity_lower or entity_lower in other_lower:
                group.append(other)
                assigned.add(other)
                continue

            if other_norm in entity_norm or entity_norm in other_norm:
                group.append(other)
                assigned.add(other)
                continue

            entity_words = set(entity_lower.split())
            other_words = set(other_lower.split())
            if entity_words and other_words:
                common = entity_words & other_words
                if any(len(w) > 2 for w in common):
                    group.append(other)
                    assigned.add(other)

        groups.append(group)

    return groups
