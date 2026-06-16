"""
Main anonymization pipeline orchestrator — V2 (GLiNER).

Two-layer detection:
  Layer 1: Exact match on project entities (unchanged from V1)
  Layer 2: GLiNER zero-shot NER (replaces fuzzy + spaCy)

Coordinates text extraction, entity detection, and replacement.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime

from . import docx_handler, pptx_handler
from .ai_detector import detect_entities
from .cross_run import replace_entities_in_text
from .entity_merger import merge_entities, CATEGORY_LABELS

# Regex for email detection
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


def _detect_emails(text: str) -> list[dict]:
    """Detect email addresses in text via regex.

    Returns list of dicts compatible with the AI detection format.
    """
    seen = set()
    results = []
    for m in _EMAIL_RE.finditer(text):
        email = m.group()
        if email.lower() not in seen:
            seen.add(email.lower())
            results.append({
                "entity": email,
                "category": "mails",
                "start": m.start(),
                "end": m.end(),
                "confidence": 1.0,
            })
    return results


def _collect_alt_texts(file_bytes: bytes, file_type: str):
    """Extract alt texts from a document.

    Returns:
        alt_texts: list of (alt_text, location_label) — all unique alt texts
        doc_or_prs: the parsed document object (for later modification)
    """
    if file_type == "pptx":
        prs, _ = pptx_handler.extract_text_blocks(file_bytes)
        alt_texts = pptx_handler.extract_alt_texts(prs)
        return alt_texts, prs
    elif file_type == "docx":
        doc, _ = docx_handler.extract_text_blocks(file_bytes)
        alt_texts = docx_handler.extract_alt_texts(doc)
        return alt_texts, doc
    return [], None


def _build_alt_mapping(alt_texts: list[tuple[str, str]]) -> tuple[dict[str, str], list[dict]]:
    """Build [ALT_X] placeholders for unique alt texts.

    Returns:
        alt_mapping: dict of original_alt_text -> placeholder
        mapping_entries: list of mapping dicts for JSON output
    """
    alt_mapping: dict[str, str] = {}
    mapping_entries: list[dict] = []
    counter = 0

    for alt_text, location in alt_texts:
        if alt_text not in alt_mapping:
            counter += 1
            placeholder = f"[ALT_{counter}]"
            alt_mapping[alt_text] = placeholder
            mapping_entries.append({
                "original": alt_text,
                "placeholder": placeholder,
                "type": "alt",
                "source": "alt_text",
                "confidence": 100,
            })

    return alt_mapping, mapping_entries


def preview(
    file_bytes: bytes,
    file_type: str,
    project_entities: dict[str, list[str]] | None = None,
) -> dict:
    """Generate a preview of what will be anonymized.

    Returns structured data for the frontend preview panel.
    """
    # Step A: Extract text
    if file_type == "docx":
        _, blocks = docx_handler.extract_text_blocks(file_bytes)
    elif file_type == "pptx":
        _, blocks = pptx_handler.extract_text_blocks(file_bytes)
    else:
        raise ValueError(f"Unsupported file type: {file_type}")

    # Collect all text for scanning
    all_text = "\n".join(b.text for b in blocks)

    # Flatten all project entities for scanning
    all_project_entities = []
    if project_entities:
        for entities in project_entities.values():
            all_project_entities.extend(entities)

    # Step B: Entity detection

    # Layer 2: GLiNER AI detection
    known_set = set(all_project_entities)
    ai_detections = detect_entities(all_text, known_entities=known_set)

    # Layer 3: Email detection
    email_detections = _detect_emails(all_text)

    # Layer 4: Alt text extraction
    alt_texts, _ = _collect_alt_texts(file_bytes, file_type)
    alt_mapping, _ = _build_alt_mapping(alt_texts)

    # Build preview sections
    sections = []
    confirmed_count = 0
    uncertain_count = 0

    for block in blocks:
        highlights = []

        # Layer 1: Find project entity exact matches in this block
        if project_entities:
            for category, entities in project_entities.items():
                for entity in entities:
                    _find_exact_highlights(block.text, entity, highlights, category, "confirmed")

        # Layer 2: Find AI-detected entities in this block
        for detection in ai_detections:
            pos = block.text.find(detection["entity"])
            if pos != -1:
                highlights.append({
                    "start": pos,
                    "end": pos + len(detection["entity"]),
                    "entity": detection["entity"],
                    "source_entity": "",
                    "placeholder": "",
                    "status": "confirmed",
                    "score": int(detection["confidence"] * 100),
                    "category": detection["category"],
                })

        # Layer 3: Find emails in this block
        for detection in email_detections:
            pos = block.text.find(detection["entity"])
            if pos != -1:
                highlights.append({
                    "start": pos,
                    "end": pos + len(detection["entity"]),
                    "entity": detection["entity"],
                    "source_entity": "",
                    "placeholder": "",
                    "status": "confirmed",
                    "score": 100,
                    "category": "mails",
                })

        # Deduplicate highlights (keep longer matches)
        highlights = _deduplicate_highlights(highlights)

        # Count by status
        for h in highlights:
            if h["status"] == "confirmed":
                confirmed_count += 1
            elif h["status"] == "uncertain":
                uncertain_count += 1

        if highlights:
            sections.append({
                "label": block.section,
                "text_blocks": [{
                    "text": block.text,
                    "highlights": highlights,
                }],
            })

    # Add alt text preview section
    if alt_mapping:
        alt_highlights = []
        for alt_text, placeholder in alt_mapping.items():
            alt_highlights.append({
                "start": 0,
                "end": len(alt_text),
                "entity": alt_text,
                "source_entity": "",
                "placeholder": placeholder,
                "status": "confirmed",
                "score": 100,
                "category": "alts",
            })
        if alt_highlights:
            sections.append({
                "label": "Alt texts (métadonnées images)",
                "text_blocks": [{
                    "text": " | ".join(alt_mapping.keys()),
                    "highlights": alt_highlights,
                }],
            })
            confirmed_count += len(alt_highlights)

    # Assign temporary placeholders for preview
    _assign_preview_placeholders(sections, project_entities)

    return {
        "sections": sections,
        "summary": {
            "confirmed": confirmed_count,
            "uncertain": uncertain_count,
        },
    }


def anonymize(
    file_bytes: bytes,
    file_type: str,
    filename: str,
    project_id: str | None,
    project_entities: dict[str, list[str]] | None = None,
    confirmed_ai: list[dict] | None = None,
    auto_confirm_all: bool = False,
) -> tuple[bytes, dict, str]:
    """Run the full anonymization pipeline.

    Args:
        file_bytes: raw file content
        file_type: "docx" or "pptx"
        filename: original filename
        project_id: project identifier or None
        project_entities: category -> entity list from project
        confirmed_ai: user-confirmed AI detections (from preview)

    Returns:
        (anonymized_file_bytes, mapping_dict, anonymized_filename)
    """
    # Auto-detect entities via CamemBERT-NER
    if file_type == "docx":
        _, blocks = docx_handler.extract_text_blocks(file_bytes)
    elif file_type == "pptx":
        _, blocks = pptx_handler.extract_text_blocks(file_bytes)
    else:
        raise ValueError(f"Unsupported file type: {file_type}")

    # Feed the filename (without extension) to the detector too, so sensitive
    # info that only appears in the document's name — and never in its body —
    # is still detected and masked in the anonymised filename.
    name_for_detection = filename.rsplit(".", 1)[0] if filename else ""
    text_parts = [b.text for b in blocks]
    if name_for_detection:
        text_parts.append(name_for_detection)
    all_text = "\n".join(text_parts)

    all_project_entities = []
    if project_entities:
        for entities in project_entities.values():
            all_project_entities.extend(entities)

    ai_detections = detect_entities(all_text, known_entities=set(all_project_entities))

    # By default, auto-confirm at >= 0.65 (lowered from 0.9). The consultant
    # prefers an over-anonymisation bias: better to mask a few harmless words
    # than to leak real identifying data. Entities between MIN_CONFIDENCE
    # (0.5) and 0.65 still surface in the triage UI so the user can keep
    # them if needed. In batch mode we drop the threshold to 0 to skip
    # per-file triage entirely.
    threshold = 0.0 if auto_confirm_all else 0.65
    auto_ai = [
        {"entity": d["entity"], "category": d["category"]}
        for d in ai_detections
        if d["confidence"] >= threshold
    ]

    # Names split across lines (Prénom on one line, NOM on the next) are
    # handled upstream: pptx/docx handlers keep the cell's line breaks and the
    # detector slices each cross-line span back onto its lines, so every line
    # already arrives here as its own entity. No token expansion needed.

    # Email detection — added as confirmed entities with category "mails"
    email_detections = _detect_emails(all_text)
    email_entities = [
        {"entity": d["entity"], "category": "mails"}
        for d in email_detections
    ]

    # Merge with user-confirmed entities from triage (low-confidence ones user accepted)
    all_ai = auto_ai + email_entities + (confirmed_ai or [])

    # Step C: Merge all entities
    entities_sorted, mapping_entries = merge_entities(
        project_entities=project_entities,
        ai_confirmed=all_ai,
    )

    # Step C2: Alt text extraction and mapping
    alt_texts, _ = _collect_alt_texts(file_bytes, file_type)
    alt_mapping, alt_mapping_entries = _build_alt_mapping(alt_texts)
    mapping_entries.extend(alt_mapping_entries)

    if not entities_sorted and not alt_mapping:
        return file_bytes, _build_mapping(filename, file_type, project_id, []), filename

    # Step D+E: Apply replacements (text + alt texts + title)
    if file_type == "docx":
        doc, _ = docx_handler.extract_text_blocks(file_bytes)
        docx_handler.apply_replacements(doc, entities_sorted, alt_mapping=alt_mapping)
        result_bytes = docx_handler.save_to_bytes(doc)
    elif file_type == "pptx":
        prs, _ = pptx_handler.extract_text_blocks(file_bytes)
        pptx_handler.apply_replacements(prs, entities_sorted, alt_mapping=alt_mapping)
        result_bytes = pptx_handler.save_to_bytes(prs)
    else:
        raise ValueError(f"Unsupported file type: {file_type}")

    # Step F: Anonymize the filename
    anon_filename = _anonymize_filename(filename, entities_sorted)

    # Step G: Build mapping
    mapping = _build_mapping(anon_filename, file_type, project_id, mapping_entries)

    return result_bytes, mapping, anon_filename


def _find_exact_highlights(text: str, entity: str, highlights: list, category: str, status: str):
    """Find exact (case-insensitive) word-boundary-aware occurrences of entity in text."""
    pattern = re.compile(
        r"(?<!\w)" + re.escape(entity) + r"(?!\w)",
        re.IGNORECASE,
    )
    for m in pattern.finditer(text):
        highlights.append({
            "start": m.start(),
            "end": m.end(),
            "entity": text[m.start():m.end()],
            "source_entity": entity,
            "placeholder": "",
            "status": status,
            "score": 100,
        })


def _deduplicate_highlights(highlights: list[dict]) -> list[dict]:
    """Remove overlapping highlights, keeping the longer/higher-confidence match."""
    if not highlights:
        return highlights

    # Sort by length descending, then score descending
    highlights.sort(key=lambda h: (h["end"] - h["start"], h.get("score") or 0), reverse=True)

    kept = []
    for h in highlights:
        overlaps = False
        for k in kept:
            if h["start"] < k["end"] and h["end"] > k["start"]:
                overlaps = True
                break
        if not overlaps:
            kept.append(h)

    kept.sort(key=lambda h: h["start"])
    return kept


def _assign_preview_placeholders(sections: list[dict], project_entities: dict[str, list[str]] | None):
    """Assign placeholder names to preview highlights."""
    from .entity_merger import CATEGORY_LABELS

    entity_to_placeholder: dict[str, str] = {}
    counters: dict[str, int] = {}

    # First pass: collect all unique entities
    for section in sections:
        for block in section["text_blocks"]:
            for h in block["highlights"]:
                entity_lower = h["entity"].lower()
                if entity_lower not in entity_to_placeholder:
                    # Determine category
                    cat = h.get("category") or _guess_category(h["entity"], project_entities)
                    label = CATEGORY_LABELS.get(cat, "SENSIBLE")
                    counters[label] = counters.get(label, 0) + 1
                    entity_to_placeholder[entity_lower] = f"[{label}_{counters[label]}]"

    # Second pass: assign placeholders
    for section in sections:
        for block in section["text_blocks"]:
            for h in block["highlights"]:
                h["placeholder"] = entity_to_placeholder.get(h["entity"].lower(), "[SENSIBLE_?]")


def _guess_category(entity: str, project_entities: dict[str, list[str]] | None) -> str:
    """Guess the category of an entity based on project data."""
    if project_entities:
        entity_lower = entity.lower()
        for cat, entities in project_entities.items():
            for e in entities:
                if e.lower() == entity_lower:
                    return cat
    return "autres"


def _anonymize_filename(filename: str, entities_sorted: list[tuple[str, str]]) -> str:
    """Apply entity replacement to the filename (without extension)."""
    if not entities_sorted or not filename:
        return filename

    # Split name and extension
    dot_pos = filename.rfind(".")
    if dot_pos > 0:
        name_part = filename[:dot_pos]
        ext_part = filename[dot_pos:]
    else:
        name_part = filename
        ext_part = ""

    anonymized_name = replace_entities_in_text(name_part, entities_sorted)
    return anonymized_name + ext_part


def _build_mapping(filename: str, file_type: str, project_id: str | None, entries: list[dict]) -> dict:
    """Build the mapping JSON structure."""
    return {
        "session_id": str(uuid.uuid4()),
        "created_at": datetime.now().isoformat(),
        "source_file": filename,
        "file_type": file_type,
        "project_id": project_id,
        "entities": entries,
    }
