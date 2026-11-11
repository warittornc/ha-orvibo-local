"""Regression tests for the shared device-state normalization interface."""

import unittest

from custom_components.orvibo_lan.devices.capabilities import (
    battery_percentage,
    finite_number,
    measurement_value,
    percentage_value,
)


class SensorValueTests(unittest.TestCase):
    """Verify state precedence and invalid-value handling through normal imports."""

    def test_measurement_precedence_and_zero_values(self) -> None:
        self.assertEqual(
            measurement_value({"temperature": 0}, "temperature", "value1"),
            0,
        )
        self.assertEqual(
            measurement_value(
                {"properties": {"temperature": {"value": "21.5"}}},
                "temperature",
                "value1",
            ),
            21.5,
        )
        self.assertEqual(
            measurement_value({"value2": "0"}, "humidity", "value2"),
            0,
        )

    def test_battery_range_and_fallbacks(self) -> None:
        self.assertEqual(battery_percentage({"battery": 0}), 0)
        self.assertEqual(battery_percentage({"battery": 101, "value4": 55}), 55)
        self.assertEqual(
            battery_percentage({"properties": {"battery_power": {"percent": 88}}}),
            88,
        )
        self.assertEqual(
            battery_percentage({"properties": {"battery": {"power": 42}}}),
            42,
        )

    def test_invalid_numeric_values_are_rejected(self) -> None:
        self.assertIsNone(finite_number(True))
        self.assertIsNone(finite_number("nan"))
        self.assertIsNone(finite_number("inf"))
        self.assertIsNone(percentage_value(-1))
        self.assertIsNone(percentage_value(101))


class NonFinitePropertyTests(unittest.TestCase):
    def test_invalid_property_percentage_falls_back_to_valid_legacy_state(self):
        for value in ("inf", "-inf", "nan", True, 10**1000):
            with self.subTest(value=repr(value)):
                state = {
                    "properties": {"battery_power": {"percent": value}},
                    "battery": 45,
                }
                self.assertEqual(battery_percentage(state), 45)
                self.assertIsNone(percentage_value(value))


if __name__ == "__main__":
    unittest.main()
