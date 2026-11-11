"""Tests for device selection helpers."""

from custom_components.orvibo_lan.devices import selection as _selection


def test_config_entry_unique_id_includes_family():
    assert _selection.config_entry_unique_id("user-1", "family-1") == "global:user-1:family-1"
    assert _selection.config_entry_unique_id("user-1", None) == "global:user-1"


def test_selected_device_ids_default_all():
    """Legacy entries without selected_device_ids return all available devices."""
    available = {"dev1", "dev2", "dev3"}
    result = _selection.selected_device_ids({}, available)
    assert result == available


def test_selected_device_ids_filters():
    """Return the intersection when selected_device_ids is configured."""
    options = {_selection.CONF_SELECTED_DEVICE_IDS: ["dev1", "dev2", "dev99"]}
    available = {"dev1", "dev2", "dev3"}
    result = _selection.selected_device_ids(options, available)
    assert result == {"dev1", "dev2"}


def test_selected_device_ids_empty_configured():
    """Empty selected_device_ids returns an empty set."""
    options = {_selection.CONF_SELECTED_DEVICE_IDS: []}
    available = {"dev1", "dev2"}
    result = _selection.selected_device_ids(options, available)
    assert result == set()


def test_selected_device_ids_invalid_type():
    """Non-list selected_device_ids returns an empty set."""
    options = {_selection.CONF_SELECTED_DEVICE_IDS: "not_a_list"}
    result = _selection.selected_device_ids(options, {"dev1"})
    assert result == set()


def test_device_id_string_vs_int():
    """String and numeric IDs can be used interchangeably."""
    options = {_selection.CONF_SELECTED_DEVICE_IDS: ["123", "456"]}
    available = {123, 456, 789}
    result = _selection.selected_device_ids(options, available)
    assert result == {"123", "456"}
