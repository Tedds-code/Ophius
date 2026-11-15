# Verification — version 1.1

- **67 automated tests passed** on Linux/Python3.12, including the original regression suite.
- New tests cover all seven live simulator fields, synthetic hourly CO2 coverage, high-CO2 warnings, all12 lab and19 dose example fields, sex-specific D-dimer limits/units, old-unit stored-report handling and legacy database migration without mixing units.
- Linux .desktop installation tested against temporary desktop/application directories; Windows .lnk command construction tested with mocked native COM execution. Actual Windows execution remains unverified.
- Chromium desktop/mobile checks pass for medicine/condition/multiword search, no matches, reset to all42 treatment topics, query and focus retention across live polling, symptom/context filtering, liveCO2 card, baseline-unit mismatch notices, and mobile layout. No JavaScript errors.
- Python compilation, JavaScript syntax and Linux shell syntax checks pass.
- Latest supplied thresholds preserved byte-for-byte; see INPUT_MANIFEST.json.
- Existing clinical/hardware limitations remain: theoretical prototype, no manufacturer device driver validation, no real clinical validation; normal current-day aggregate loss is possible on abrupt termination.

Screenshots from the updated checks are in docs/screenshots/. Earlier screenshots are retained as illustrations of the original merge checks.
