"""
Cross-run entity replacement logic.

This is the most critical module in the project. In DOCX and PPTX files,
a paragraph's visible text is split across multiple "runs", each with
independent formatting. An entity like "Jean Dupont" might span multiple
runs with different formatting (bold, italic, etc.).

This module handles offset-based merge-and-replace to correctly replace
entities that span multiple runs while preserving all run-level formatting.
"""

from __future__ import annotations

import copy
import re
from typing import Protocol, runtime_checkable
from lxml import etree


@runtime_checkable
class RunLike(Protocol):
    """Protocol for objects that behave like a run (docx or pptx)."""
    text: str
    font: object


def copy_run_formatting(source_run, target_run, file_type: str = "docx"):
    """Copy all formatting properties from source to target run.

    Handles both python-docx and python-pptx run objects.
    """
    if source_run is None:
        return

    sf = source_run.font
    tf = target_run.font

    # Common properties
    tf.name = sf.name
    tf.size = sf.size
    tf.bold = sf.bold
    tf.italic = sf.italic
    tf.underline = sf.underline

    # Color handling — be careful with None values
    try:
        if sf.color and sf.color.rgb is not None:
            tf.color.rgb = sf.color.rgb
    except (AttributeError, TypeError):
        pass

    try:
        if sf.color and sf.color.theme_color is not None:
            tf.color.theme_color = sf.color.theme_color
    except (AttributeError, TypeError):
        pass

    if file_type == "pptx":
        try:
            if sf.color and hasattr(sf.color, 'brightness') and sf.color.brightness is not None:
                tf.color.brightness = sf.color.brightness
        except (AttributeError, TypeError):
            pass
        try:
            if hasattr(sf, 'language_id') and sf.language_id is not None:
                tf.language_id = sf.language_id
        except (AttributeError, TypeError):
            pass

    # Additional common properties
    try:
        tf.strikethrough = sf.strikethrough
    except (AttributeError, TypeError):
        pass
    try:
        tf.subscript = sf.subscript
    except (AttributeError, TypeError):
        pass
    try:
        tf.superscript = sf.superscript
    except (AttributeError, TypeError):
        pass
    try:
        if hasattr(sf, 'highlight_color'):
            tf.highlight_color = sf.highlight_color
    except (AttributeError, TypeError):
        pass


def _build_run_map(runs):
    """Build a character-offset map of all runs.

    Returns:
        run_map: list of (start_char, end_char, run_object, run_index)
        full_text: concatenated text of all runs
    """
    run_map = []
    offset = 0
    for i, run in enumerate(runs):
        text = run.text or ""
        run_map.append((offset, offset + len(text), run, i))
        offset += len(text)
    full_text = "".join(r.text or "" for r in runs)
    return run_map, full_text


def _is_word_boundary(text: str, pos: int) -> bool:
    """Check if position is at a word boundary (start or end of a word)."""
    if pos <= 0 or pos >= len(text):
        return True
    char = text[pos] if pos < len(text) else " "
    prev = text[pos - 1] if pos > 0 else " "
    # Boundary = transition between word char and non-word char
    return not (prev.isalnum() and char.isalnum())


def _find_replacements(full_text: str, entities_sorted: list[tuple[str, str]]) -> list[tuple[int, int, str]]:
    """Find all entity match positions in full_text using word-boundary-aware matching.

    Args:
        full_text: the concatenated text to search in
        entities_sorted: list of (original_text, placeholder) sorted by length DESC

    Returns:
        list of (match_start, match_end, placeholder) sorted by position
    """
    replacements = []

    for original, placeholder in entities_sorted:
        # Use regex with word boundaries for clean matching
        # re.escape handles special chars in entity names
        pattern = re.compile(
            r"(?<!\w)" + re.escape(original) + r"(?!\w)",
            re.IGNORECASE,
        )
        for m in pattern.finditer(full_text):
            pos = m.start()
            match_end = m.end()
            # Check no overlap with already-found replacements
            if not any(r_start < match_end and r_end > pos for r_start, r_end, _ in replacements):
                replacements.append((pos, match_end, placeholder))

    replacements.sort(key=lambda x: x[0])
    return replacements


def _build_new_runs_data(full_text: str, runs, run_map, replacements):
    """Build new run segments with replacements applied.

    Returns:
        list of (text, formatting_source_run)
    """
    new_runs_data = []
    char_idx = 0
    repl_idx = 0
    current_segment = ""
    current_format_run = runs[0] if runs else None

    def get_run_at(pos):
        """Get the run object at a given character position."""
        for rm_start, rm_end, rm_run, _ in run_map:
            if rm_start <= pos < rm_end:
                return rm_run
        return runs[-1] if runs else None

    while char_idx <= len(full_text):
        # Check if we're at a replacement start
        if repl_idx < len(replacements) and char_idx == replacements[repl_idx][0]:
            # Flush current segment
            if current_segment:
                new_runs_data.append((current_segment, current_format_run))
                current_segment = ""

            r_start, r_end, placeholder = replacements[repl_idx]

            # Use formatting from the run where the replacement starts
            format_run = get_run_at(r_start) or (runs[0] if runs else None)
            new_runs_data.append((placeholder, format_run))
            char_idx = r_end
            repl_idx += 1

            # Update current_format_run for next segment
            if char_idx < len(full_text):
                current_format_run = get_run_at(char_idx) or current_format_run
            continue

        if char_idx >= len(full_text):
            break

        # Update current formatting based on which run we're in
        run_at = get_run_at(char_idx)
        if run_at is not None and current_format_run != run_at and current_segment:
            # Formatting changed — flush segment
            new_runs_data.append((current_segment, current_format_run))
            current_segment = ""
            current_format_run = run_at
        elif run_at is not None:
            current_format_run = run_at

        current_segment += full_text[char_idx]
        char_idx += 1

    # Flush last segment
    if current_segment:
        new_runs_data.append((current_segment, current_format_run))

    return new_runs_data


def replace_entities_in_paragraph_docx(paragraph, entities_sorted: list[tuple[str, str]]):
    """Replace entities in a python-docx paragraph while preserving formatting.

    Args:
        paragraph: a python-docx Paragraph object
        entities_sorted: list of (original_text, placeholder) sorted by len DESC
    """
    runs = list(paragraph.runs)
    if not runs:
        return

    run_map, full_text = _build_run_map(runs)
    if not full_text.strip():
        return

    replacements = _find_replacements(full_text, entities_sorted)
    if not replacements:
        return

    new_runs_data = _build_new_runs_data(full_text, runs, run_map, replacements)

    # Clear existing runs and rebuild
    p_element = paragraph._p
    # Remove all existing run elements
    for run in runs:
        p_element.remove(run._r)

    # Add new runs with correct formatting
    for text, format_source in new_runs_data:
        new_run = paragraph.add_run(text)
        copy_run_formatting(format_source, new_run, file_type="docx")


def replace_entities_in_paragraph_pptx(paragraph, entities_sorted: list[tuple[str, str]]):
    """Replace entities in a python-pptx paragraph while preserving formatting.

    Args:
        paragraph: a python-pptx paragraph object
        entities_sorted: list of (original_text, placeholder) sorted by len DESC
    """
    runs = list(paragraph.runs)
    if not runs:
        return

    run_map, full_text = _build_run_map(runs)
    if not full_text.strip():
        return

    replacements = _find_replacements(full_text, entities_sorted)
    if not replacements:
        return

    new_runs_data = _build_new_runs_data(full_text, runs, run_map, replacements)

    # For pptx, we need to manipulate the XML directly
    p_elem = paragraph._p
    nsmap = p_elem.nsmap
    a_ns = nsmap.get('a', 'http://schemas.openxmlformats.org/drawingml/2006/main')

    # Remove all existing <a:r> elements
    for run in runs:
        r_elem = run._r
        p_elem.remove(r_elem)

    # Add new runs
    for text, format_source in new_runs_data:
        # Create a new <a:r> element
        new_r = copy.deepcopy(format_source._r)
        # Update the text
        t_elems = new_r.findall(f'{{{a_ns}}}t')
        if t_elems:
            t_elems[0].text = text
        else:
            t_elem = etree.SubElement(new_r, f'{{{a_ns}}}t')
            t_elem.text = text
        p_elem.append(new_r)


def replace_entities_in_text(text: str, entities_sorted: list[tuple[str, str]]) -> str:
    """Simple text-level replacement for preview purposes.

    Args:
        text: plain text string
        entities_sorted: list of (original_text, placeholder) sorted by len DESC

    Returns:
        text with all entities replaced
    """
    replacements = _find_replacements(text, entities_sorted)
    if not replacements:
        return text

    result = []
    last_end = 0
    for start, end, placeholder in replacements:
        result.append(text[last_end:start])
        result.append(placeholder)
        last_end = end
    result.append(text[last_end:])
    return "".join(result)
