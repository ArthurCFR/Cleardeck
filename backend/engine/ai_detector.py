"""
AI-powered entity detection using CamemBERT-NER.

Replaces both fuzzy_matcher.py and ner_engine.py from V1.
CamemBERT-NER is a ~400Mo model fine-tuned for French NER on WikiNER-fr.
Runs locally on CPU — no data leaves the machine.

F1 scores on WikiNER-fr (entity-level):
  PER: 94.8%  |  ORG: 81.8%  |  LOC: 89.6%  |  MISC: 81.5%

Architecture:
  - Layer 1 (exact match) is handled in anonymizer.py (unchanged)
  - Layer 2 (this module) uses CamemBERT-NER to detect PER, ORG, LOC, MISC
    directly from the text — much more accurate than spaCy fr_core_news_sm.
"""

from __future__ import annotations

import torch
from transformers import pipeline, AutoTokenizer, AutoModelForTokenClassification

_ner_pipeline = None

# CamemBERT-NER labels → our internal categories
LABEL_TO_CATEGORY = {
    "PER": "personnes",
    "ORG": "entreprises",
    "LOC": "lieux",
    "MISC": "autres",
}

# Minimum entity length to avoid noise
MIN_ENTITY_LENGTH = 3

# Minimum confidence score (0-1). Lowered from 0.8 → 0.5 so the detector
# surfaces moderate-confidence candidates too — the consultant prefers a
# few false positives (visible in triage, can be dismissed) over missing
# real identifying data. Below this the noise floor is too high.
MIN_CONFIDENCE = 0.5

# Words that should never be flagged as entities
_STOPWORDS = {
    # Job titles
    "manager", "partner", "associé", "associée", "directeur", "directrice",
    "président", "présidente", "officer", "chief", "head", "leader",
    "consultant", "dsi", "cdo", "cto", "ceo", "cfo",
    # Generic business terms
    "direction", "service", "stratégie", "performance", "transformation",
    "innovation", "intelligence artificielle", "data", "digital",
    "projet", "programme", "mission", "plan", "atelier",
    "analyse", "diagnostic", "audit", "étude",
    # Common French words that look like proper nouns
    "quelques", "notre", "votre", "synthèse", "conclusion",
    "introduction", "annexe", "sommaire", "agenda",
}

# Acronyms that are NOT entities
_ACRONYM_BLACKLIST = {
    "LLM", "LLMS", "GPT", "DSI", "CDO", "CTO", "CEO", "CFO", "COO",
    "COMEX", "ETI", "PME", "ROI", "KPI", "OKR", "ESG", "RSE",
    "NLP", "POC", "MVP", "API", "SLA", "RPA", "ERP", "CRM",
    "IA", "AI", "ML", "DL", "IT", "SI", "RH", "BU",
}


def get_pipeline():
    """Load the CamemBERT-NER pipeline (lazy singleton)."""
    global _ner_pipeline
    if _ner_pipeline is None:
        model_name = "Jean-Baptiste/camembert-ner"
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModelForTokenClassification.from_pretrained(model_name)
        _ner_pipeline = pipeline(
            "ner",
            model=model,
            tokenizer=tokenizer,
            aggregation_strategy="simple",
            device=-1,  # CPU
        )
    return _ner_pipeline


def detect_entities(
    text: str,
    known_entities: set[str] | None = None,
    confidence_threshold: float = MIN_CONFIDENCE,
) -> list[dict]:
    """Detect named entities in text using CamemBERT-NER.

    Args:
        text: the full text to scan
        known_entities: entities already detected by exact matching (to skip)
        confidence_threshold: minimum score (0-1)

    Returns:
        list of dicts with keys: entity, category, start, end, confidence
    """
    known_lower = {e.lower() for e in (known_entities or set())}
    ner = get_pipeline()

    # CamemBERT has a 512-token limit. Split long texts into chunks.
    chunks = _split_text(text, max_chars=1500)
    raw_results = []

    for chunk_text, chunk_offset in chunks:
        predictions = ner(chunk_text)
        for pred in predictions:
            # The HF pipeline returns entity_group (with aggregation_strategy)
            label = pred["entity_group"]
            # Strip B-/I- prefixes if present
            if label.startswith(("B-", "I-")):
                label = label[2:]

            if label not in LABEL_TO_CATEGORY:
                continue

            # Skip MISC — generates too many false positives on business docs
            # (e.g. "Schéma Directeur", "Business Case", "Python", "Excel")
            if label == "MISC":
                continue

            # Use the real source substring (not pred["word"], which the
            # tokenizer detokenises with spaces) so newlines inside the span
            # are preserved — they are the boundaries we split on below.
            surface = chunk_text[pred["start"]:pred["end"]]

            raw_results.append({
                "entity": surface,
                "label": label,
                "start": pred["start"] + chunk_offset,
                "end": pred["end"] + chunk_offset,
                "confidence": pred["score"],
            })

    # Split spans that cross line boundaries. The text fed to CamemBERT joins
    # every paragraph/cell line with "\n"; with aggregation_strategy="simple"
    # the model merges contiguous same-label tokens *across* those newlines, so
    # a column of stacked names (one person per line) collapses into a single
    # giant PER span. We slice each span back onto its line boundaries: every
    # line becomes its own entity. This guarantees one fragment = one
    # placeholder downstream, while detection still ran on the full joined
    # context (so an isolated surname like "ETTAHAR" still inherits PER).
    raw_results = _split_on_newlines(raw_results)

    # Filter and clean
    results = []
    for r in raw_results:
        entity = r["entity"].strip()

        # CamemBERT tokenizer sometimes adds leading/trailing spaces or ▁
        entity = entity.strip("▁ ")

        if len(entity) < MIN_ENTITY_LENGTH:
            continue
        if r["confidence"] < confidence_threshold:
            continue
        if entity.lower() in known_lower:
            continue
        if entity.lower() in _STOPWORDS:
            continue
        if entity.upper() in _ACRONYM_BLACKLIST:
            continue
        if "\n" in entity:
            continue

        # Skip single-word results that are all lowercase (not proper nouns)
        if " " not in entity and entity[0].islower():
            continue

        category = LABEL_TO_CATEGORY[r["label"]]

        results.append({
            "entity": entity,
            "category": category,
            "start": r["start"],
            "end": r["end"],
            "confidence": round(r["confidence"], 3),
        })

    return _deduplicate(results)


def _split_text(text: str, max_chars: int = 1500) -> list[tuple[str, int]]:
    """Split text into chunks respecting CamemBERT's 512-token window.

    Splits on paragraph boundaries to avoid cutting entities.
    ~1500 chars ≈ ~400 tokens, safely under the 512 limit.

    Returns:
        list of (chunk_text, char_offset_in_original)
    """
    if len(text) <= max_chars:
        return [(text, 0)]

    chunks = []
    paragraphs = text.split("\n")
    current_chunk = ""
    current_offset = 0
    char_pos = 0

    for para in paragraphs:
        para_with_nl = para + "\n"

        if len(current_chunk) + len(para_with_nl) > max_chars and current_chunk:
            chunks.append((current_chunk, current_offset))
            current_offset = char_pos
            current_chunk = ""

        current_chunk += para_with_nl
        char_pos += len(para_with_nl)

    if current_chunk.strip():
        chunks.append((current_chunk, current_offset))

    return chunks


def _split_on_newlines(raw_results: list[dict]) -> list[dict]:
    """Split any detected span that contains newlines into per-line fragments.

    Each fragment inherits the parent span's label and confidence and gets
    accurate start/end offsets (leading whitespace per line is trimmed and
    the offset adjusted). Spans with no newline pass through unchanged.
    """
    fragments: list[dict] = []
    for r in raw_results:
        surface = r["entity"]
        if "\n" not in surface:
            fragments.append(r)
            continue

        cursor = 0  # offset of the current line within `surface`
        for line in surface.split("\n"):
            stripped = line.strip()
            if stripped:
                lead = len(line) - len(line.lstrip())
                frag_start = r["start"] + cursor + lead
                fragments.append({
                    "entity": stripped,
                    "label": r["label"],
                    "start": frag_start,
                    "end": frag_start + len(stripped),
                    "confidence": r["confidence"],
                })
            cursor += len(line) + 1  # +1 for the consumed "\n"

    return fragments


def _deduplicate(results: list[dict]) -> list[dict]:
    """Remove overlapping detections, keeping higher-confidence ones."""
    if not results:
        return results

    # Sort by confidence descending
    results.sort(key=lambda r: r["confidence"], reverse=True)

    kept = []
    for r in results:
        overlaps = False
        for k in kept:
            if r["start"] < k["end"] and r["end"] > k["start"]:
                overlaps = True
                break
        if not overlaps:
            if not any(r["entity"].lower() == k["entity"].lower() for k in kept):
                kept.append(r)

    kept.sort(key=lambda r: r["start"])
    return kept
