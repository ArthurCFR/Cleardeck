"""Regression tests for entity matching across underscore separators.

Run standalone (no pytest needed):
    python backend/tests/test_filename_boundary.py

Bug reproduced here: filenames glue terms together with "_" (e.g.
"Synthese_IA_LaPoste_mois"). The boundary regex used to rely on \\w, which
counts "_" as a word char, so a term wedged between underscores was treated as
mid-word and never masked — intermittently, depending on the separator the
user happened to use (spaces/hyphens/parens worked, underscores did not).
The fix uses [^\\W_] (alphanumeric, underscore excluded) for the lookarounds.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.engine.anonymizer import _anonymize_filename
from backend.engine.cross_run import replace_entities_in_text


def test_underscore_is_a_boundary():
    """A term wrapped in underscores must still be replaced."""
    pairs = [("LaPoste", "[ENTREPRISE_5]")]
    assert replace_entities_in_text("Synthese_IA_LaPoste_mois", pairs) == \
        "Synthese_IA_[ENTREPRISE_5]_mois"
    print("OK  test_underscore_is_a_boundary")


def test_other_separators_still_work():
    """Spaces, hyphens and parens must keep working (they always did)."""
    pairs = [("La Poste", "[ENTREPRISE_4]"), ("LaPoste", "[ENTREPRISE_5]")]
    assert replace_entities_in_text("Synthese IA La Poste mois", pairs) == \
        "Synthese IA [ENTREPRISE_4] mois"
    assert replace_entities_in_text("Synthese-IA-LaPoste-mois", pairs) == \
        "Synthese-IA-[ENTREPRISE_5]-mois"
    assert replace_entities_in_text("Extrait (LaPoste) v2", pairs) == \
        "Extrait ([ENTREPRISE_5]) v2"
    print("OK  test_other_separators_still_work")


def test_no_mid_word_match():
    """Boundary still holds: a term inside a longer alnum word is untouched."""
    pairs = [("LaPoste", "[X]")]
    assert replace_entities_in_text("Synthese_LaPosteXY_mois", pairs) == \
        "Synthese_LaPosteXY_mois"
    print("OK  test_no_mid_word_match")


def test_anonymize_filename_underscore():
    """End-to-end on the filename helper, extension preserved."""
    pairs = [("LaPoste", "[ENTREPRISE_5]")]
    out = _anonymize_filename("Synthese_IA_LaPoste_mois.pptx", pairs)
    assert out == "Synthese_IA_[ENTREPRISE_5]_mois.pptx", out
    print("OK  test_anonymize_filename_underscore")


if __name__ == "__main__":
    test_underscore_is_a_boundary()
    test_other_separators_still_work()
    test_no_mid_word_match()
    test_anonymize_filename_underscore()
    print("\nAll tests passed.")
