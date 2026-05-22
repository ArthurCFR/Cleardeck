"""
Reverse anonymization pipeline.

Takes an anonymized file and a mapping JSON, replaces all placeholders
back to the original text using the same cross-run logic.
"""

from __future__ import annotations

from . import docx_handler, pptx_handler


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
