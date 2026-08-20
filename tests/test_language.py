"""English is the language of this application.

A build that opens in a language its user did not pick for *it* is what this
pins down. The preference file lives in the user's home folder, outside the
application, so it is shared with every other copy on the machine — including a
source checkout run long before the build was downloaded. That is how a freshly
installed English application came up in Italian.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from desktop import i18n  # noqa: E402


@pytest.fixture
def settings(tmp_path, monkeypatch):
    """Point the preference file somewhere harmless."""
    path = tmp_path / "prefs.json"
    monkeypatch.setattr(i18n, "_SETTINGS", path)
    yield path
    i18n.set_language(i18n.DEFAULT_LANGUAGE)


def test_the_default_language_is_english(settings):
    assert i18n.DEFAULT_LANGUAGE == "en"
    assert i18n.load_saved_language() is None      # no file, no question asked
    i18n.set_language(i18n.load_saved_language())
    assert i18n.current_language() == "en"
    assert i18n.tr("Production cost") == "Production cost"


def test_a_legacy_preference_file_is_ignored(settings):
    """The file the removed first-run dialog used to write."""
    settings.write_text(json.dumps({"language": "it"}), encoding="utf-8")
    assert i18n.load_saved_language() is None
    i18n.set_language(i18n.load_saved_language())
    assert i18n.current_language() == "en"


def test_a_deliberate_choice_from_the_menu_is_honoured(settings):
    i18n.save_language("it")
    stored = json.loads(settings.read_text(encoding="utf-8"))
    assert stored["settings_version"] == i18n.SETTINGS_VERSION
    assert i18n.load_saved_language() == "it"
    i18n.set_language(i18n.load_saved_language())
    assert i18n.current_language() == "it"
    assert i18n.tr("Production cost") == "Costo di produzione"


def test_an_unreadable_or_foreign_file_falls_back_to_english(settings):
    for content in ("not json at all", json.dumps(["it"]),
                    json.dumps({"settings_version": 2, "language": "klingon"})):
        settings.write_text(content, encoding="utf-8")
        assert i18n.load_saved_language() is None


def test_set_language_rejects_nonsense(settings):
    for bad in (None, "", "xx", "IT"):
        i18n.set_language(bad)
        assert i18n.current_language() == "en", bad


def test_only_english_is_advertised_as_complete():
    assert i18n.COMPLETE_LANGUAGES == frozenset({"en"})
    assert set(i18n.LANGUAGES) == {"en", "it", "es", "fr"}


def test_the_translations_really_are_partial():
    """Not a complaint — the reason the menu has to say so.

    Strings added to the interface since the translations were last revised fall
    back to English. Asserting it keeps the label honest instead of aspirational.
    """
    english_only = [s for s in ("Main product output", "Operating credits (€/yr)")
                    if s not in i18n.TRANSLATIONS["it"]]
    assert english_only, "if the Italian catalogue is complete, revisit the menu label"


def test_the_app_no_longer_asks_for_a_language_on_first_run():
    source = (ROOT / "desktop" / "app.py").read_text(encoding="utf-8")
    assert "QInputDialog" not in source
    assert "load_saved_language" in source
