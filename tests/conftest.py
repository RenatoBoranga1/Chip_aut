"""Opt-in configuration for existing tests that exercise every retained page."""

from dataclasses import replace

import pytest

from ui import navigation


@pytest.fixture
def all_navigation(monkeypatch):
    monkeypatch.setattr(
        navigation, "NAVIGATION_ITEMS", tuple(replace(item, visible=True) for item in navigation.NAVIGATION_ITEMS)
    )
