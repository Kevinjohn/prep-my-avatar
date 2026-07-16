import pytest

from app.version import APP_VERSION, calver_key, is_newer_version


def test_current_app_version_uses_release_calver():
    assert APP_VERSION == '2026.07.17.1'
    assert calver_key(APP_VERSION) == (2026, 7, 17, 1)


def test_calver_comparison_is_numeric_not_lexical():
    assert is_newer_version('v2026.07.17.10', '2026.07.17.9') is True
    assert is_newer_version('2026.07.18.1', '2026.07.17.99') is True
    assert is_newer_version('2026.07.17.2', '2026.07.17.10') is False


def test_legacy_date_tags_and_invalid_release_tags_are_safe():
    assert calver_key('v2026.07.17') == (2026, 7, 17, 0)
    assert is_newer_version('not-a-version', APP_VERSION) is False
    with pytest.raises(ValueError):
        calver_key('2026.02.30.1')
