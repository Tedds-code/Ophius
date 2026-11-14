# Made in cooperation with ChatGPT
# Astronaut Health Monitor V11 – Uploaded JSON Integration & Blood Panel Simulation

This version works with the **exact uploaded `thresholds (2).json`**, copied to
`config/thresholds.json`. It supports all 44 signal rules, 6 condition cutoffs,
and preserves reference-only habitat information as *non-alert* data.

## Install in Windows Git Bash

1. In your repository folder, back up your DB and existing sources (or commit):
   `git status` and `cp config/thresholds.json config/thresholds.before_v11.json`.
2. **For the overlay ZIP:** extract into the repository ROOT, merging the `src`,
   `tests`, `config`, `examples` directories. Do **NOT** delete `data/`, `.venv`,
   or your `.git` folder. Do not run the obsolete `scripts/apply_v10_catalog.py`;
   V11's catalog is already complete.
3. Activate virtual environment:
   `source .venv/Scripts/activate`
4. Run `python -m pip install -e .`
5. Run `python -m unittest discover -s tests -v`.
6. Run `python -m astro_health`, then choose:
   - **9** – desktop dashboard
   - **10** – import a blood-test JSON file
   - **11** – simulate a blood panel and save the generated JSON + readings
   - **8** – exit and save the session

To launch the dashboard separately:
`python -m astro_health.dashboard`

## Blood-test JSON

The program asks for a **.json file path** when you select option 10.
Use `examples/blood_test_example.json` as a template. Set `synthetic` to `false`
for an externally obtained data file; this does not validate that file's
accuracy. Partial panels are supported. Every lab measurement is one numeric
value and an **explicit unit**. The parser rejects unknown fields, wrong units,
negative/non-finite numbers, and duplicate JSON keys. No automatic unit guessing.

The blood panel supports 12 shared analytes: hemoglobin, hematocrit, RBC, WBC,
neutrophils, lymphocytes, monocytes, eosinophils, basophils, platelets,
reticulocytes and D-dimer. The same hemoglobin, hematocrit, RBC, and D-dimer
values are independently assessed against the source's male/female reference
ranges. QTc (manually entered ECG result) is displayed in the same side-by-side
panel. This comparison does **not** infer the patient's sex or choose one band.

Option 11 prompts for simulation profile:
- **1 or Enter**: all values within both configured male/female bands.
- **2**: mixed-caution demo: synthetic hemoglobin is 12.5 g/dL (male CAUTION,
  female GOOD), and WBC/platelets trigger CAUTION.

The synthetic report is written to `data/simulations/blood_panel_*.json` and
its measurements are saved in the current SQLite session, labeled `SYNTHETIC`.
All simulation numbers are test fixtures, **not** a physiological simulation
or trustworthy blood-test result. No additional pip dependencies are needed.

## Important semantics

- Body temperature is a **manual** `temperature` measurement and is compared
  with the **uploaded** `skin_temperature` rule in memory. The existing
  thermistor remains explicitly a *skin-surface* sensor and is not treated as a
  body thermometer. The source JSON itself is unchanged.
- Blood-test and QTc bands are project reference comparisons, not medical
  diagnoses. Many blood-panel source rules have caution bounds but **no red
  (critical) bounds**; the software does not invent them.
- NASA-inspired dose windows still require verified exposure intervals,
  full-career context or mission duration. Unknown context means gray/unassessed.
  No organ-dose sensor has been invented; manually reported dose quantities
  must have operator-verified provenance before their interval comparisons.
- CO2 is constrained by the uploaded 1-hour *partial-pressure* mmHg rule.
  Spot sensor ppm values cannot be compared without a verified hourly average
  and measured cabin pressure. Habitat references in `reference_only` never
  generate astronaut health alerts.
- Back-pain days 2–5 is an onset *context* and not inherently a bad reading.
- The uploaded JSON's threshold values and stated sources are **not independently
  clinically verified**. In particular, check blood-test units and source
  references with qualified experts before any real-world interpretation.
  This is an educational prototype, **not a medical device**.
