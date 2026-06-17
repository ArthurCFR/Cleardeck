"""
Reverse anonymization pipeline.

Takes an anonymized file and a mapping JSON, replaces all placeholders
back to the original text using the same cross-run logic.
"""

from __future__ import annotations

from . import docx_handler, pptx_handler


def _reverse_map(mapping: dict) -> dict[str, str]:
    """Build placeholder -> first original from a mapping dict."""
    reverse: dict[str, str] = {}
    for entry in mapping.get("entities", []):
        placeholder = entry.get("placeholder")
        original = entry.get("original")
        if placeholder and placeholder not in reverse:
            reverse[placeholder] = original
    return reverse


def deanonymize_filename(filename: str, mapping: dict) -> str:
    """Restore placeholders in a filename back to their original terms.

    The anonymised filename carries *sanitised* placeholders — the download-name
    sanitiser turns [SENSIBLE_2] into (SENSIBLE_2) — so we reverse both the
    bracketed and parenthesised forms. The "anonymise_" prefix is also dropped
    so the restored title matches the original document name. The document body
    is de-anonymised separately by deanonymize(); without this the title kept
    its placeholder while the rest of the file was restored.
    """
    name = filename
    if name.startswith("anonymise_"):
        name = name[len("anonymise_"):]
    # Longest placeholders first so e.g. [PERSONNE_10] is handled before
    # [PERSONNE_1].
    for placeholder, original in sorted(
        _reverse_map(mapping).items(), key=lambda x: len(x[0]), reverse=True
    ):
        sanitised = placeholder.replace("[", "(").replace("]", ")")
        name = name.replace(placeholder, original).replace(sanitised, original)
    return name


def deanonymize(
    file_bytes: bytes,
    file_type: str,
    mapping: dict,
) -> bytes:
    """Reverse anonymization using the mapping table.

    For each placeholder, we use the first original value that was mapped to it.

    Args:
        file_bytes: anonymized file content
        file_type: "docx" or "pptx"
        mapping: the mapping dict (from anonymization output)

    Returns:
        restored file bytes
    """
    # Build reverse mapping: placeholder -> first original
    reverse_map: dict[str, str] = {}
    for entry in mapping.get("entities", []):
        placeholder = entry["placeholder"]
        original = entry["original"]
        if placeholder not in reverse_map:
            reverse_map[placeholder] = original

    if not reverse_map:
        return file_bytes

    # Sort by placeholder length descending (in case placeholders overlap somehow)
    entities_sorted = sorted(
        reverse_map.items(),
        key=lambda x: len(x[0]),
        reverse=True,
    )

    if file_type == "docx":
        doc, _ = docx_handler.extract_text_blocks(file_bytes)
        docx_handler.apply_replacements(doc, entities_sorted)
        return docx_handler.save_to_bytes(doc)
    elif file_type == "pptx":
        prs, _ = pptx_handler.extract_text_blocks(file_bytes)
        pptx_handler.apply_replacements(prs, entities_sorted)
        return pptx_handler.save_to_bytes(prs)
    else:
        raise ValueError(f"Unsupported file type: {file_type}")
