# Measurement coverage — version 1.1

The threshold catalog has **44 rules**, representing **39 distinct measurement
keys** once the five male/female reference pairs are combined. Personal baseline
documents are reference data and never supply missing current observations.

| Measurements | Count | Input / simulation |
|---|---:|---|
| Heart rate, systolic BP, diastolic BP, QTc, SpO₂, skin temperature, cabin CO₂ | 7 | Continuous sensor simulation and supported JSON packets |
| Hemoglobin, hematocrit, RBC, WBC, neutrophils, lymphocytes, monocytes, eosinophils, basophils, platelets, reticulocytes, D-dimer | 12 | Manually imported lab JSON; complete synthetic example generated on demand |
| Configured personal/organ radiation quantities and windows | 19 | Dose-report JSON; complete synthetic examples generated on demand |
| Vomiting episodes | 1 | Manual entry in Symptoms; not inferred from a generic sensor |

**The missing live simulator field was cabin CO₂; version 1.1 includes it.**
Its synthetic one-hour average is reported explicitly in mmHg, with synthetic
coverage metadata. This is a test fixture and does not claim one hour of actual
measurements. An actual instrument report still needs its real averaging context.

Radiation reports retain the distinction between effective, organ and heavy-ion
dose quantities. The example generator does not derive organ doses from a generic
detector. Missing actual coverage remains unassessed outside the synthetic reports.

## Additional manual inputs

These support diagnostic rules and are not automatically simulated or measured:

- Core temperature (separate from sensor skin temperature).
- Watery-stool count over 24 hours.
- Systolic and diastolic pressure drop on standing.
- Symptom duration in hours.
- Reported symptoms and exposure/context selections.

The current mission day is calculated from the first valid measurement date.
The six configured condition cutoffs use heart rate, symptom duration or mission
day; they are not six additional independent sensor readings.

## Profile-only information

PT, aPTT, potassium, magnesium, PR interval, QRS duration, HRV/RMSSD and vascular
ultrasound details appear in the supplied profiles but have no corresponding
threshold rules. They remain baseline/history information. No automated detection,
replacement treatment or continuous sensor value is invented for these fields.

## Generate complete test JSON

Run `python make_demo_reports.py` (Linux: `python3 make_demo_reports.py`).
It generates dated, uniquely identified fixtures in `examples/generated/`:

- `blood_panel_all_supported.json`: all 12 supported lab measurements, including
  D-dimer in the replacement catalog's mg/L units.
- `dose_career.json`, `dose_30_days.json`, `dose_1_year.json`,
  `dose_per_mission_year.json`: together cover all 19 configured dose rules.

Import the blood report using **Import blood test**. Import each dose report using
**Import sensor packet**. Nothing is imported automatically. Generate fresh files
before beginning a live simulation so per-measurement acquisition timestamps remain
in order. A source can be labelled synthetic and still be assessed against a project
reference; it must not be mistaken for real exposure history.
