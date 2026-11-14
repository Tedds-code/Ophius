# Made in cooperation with ChatGPT
# File: src/astro_health/fixed_manual_input.py
"""Manual input from the fixed, predefined test catalog."""

from astro_health.fixed_tests import MANUAL_TESTS
from astro_health.manual_input import ManualInput
from astro_health.models import MeasurementValue


class FixedManualInput(ManualInput):
    """Ask for a test, then only its required numeric fields and units."""

    def __init__(self, *args, test_catalog=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.test_catalog = test_catalog if test_catalog is not None else MANUAL_TESTS

    def _collect_measurements(self) -> tuple[MeasurementValue, ...]:
        while True:
            self.output_function("\n=== Available health tests ===")
            for index, test in enumerate(self.test_catalog, start=1):
                self.output_function(f"{index}. {test.display_name}")

            choice = self.input_function("Choose a test number: ").strip()
            try:
                index = int(choice)
            except ValueError:
                index = 0
            if 1 <= index <= len(self.test_catalog):
                chosen_test = self.test_catalog[index - 1]
                break
            self.output_function("Invalid test number. Please try again.")

        self.output_function(f"\nSelected: {chosen_test.display_name}")
        measurements = []
        for field in chosen_test.fields:
            value = self._ask_number(f"{field.display_name} ({field.unit}): ")
            measurements.append(MeasurementValue(
                measurement_type=field.measurement_type,
                value=value,
                unit=field.unit,
            ))
        return tuple(measurements)
