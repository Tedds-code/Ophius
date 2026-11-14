# Astronaut Health Monitor — V14 JSON-first sensor integration

**Installation:** Place `Astronaut_Health_Monitor_V14_Sensor_Overlay.zip` in the root of your project. Do not unzip it manually. From Git Bash, in that directory, run the inline installer supplied with the download link. The installer backs up replaced files, does not overwrite `config/thresholds.json`, and does not touch your SQLite database.

## What changed

* Option **4 → 0** sends one synthetic packet from each of thermistor, PPG (heart rate/SpO₂), ECG (device-reported QTc), oscillometric blood-pressure cuff, CO₂ monitor (device-reported one-hour partial-pressure average), NASA-aligned radiation snapshot, laboratory analyzer (12 analytes), and **four** modeled dosimetry reports (30-day, 1-year, career, and per-mission-year).
* Option 4's laboratory analyzer is a mock *instrument-reported laboratory result*. A physical analyzer requires a manufacturer-specific adapter to emit the packet format. It is not a blood test derived from a wearable sensor.
* Option 4's dosimetry reports contain **modeled organ-dose quantities**, not fields measurable by an ordinary radiation counter. Without explicit date coverage, these remain `NEEDS CONTEXT`; this is intentional, not a missing-reading bug. **Option 12** generates a synthetic 365-day history and evaluates those exposure windows. **Option 13** imports such a verified-format synthetic history.
* Every ordinary dashboard session now shows exactly the 44 `signals` rules and 6 `condition_cutoffs` from `config/thresholds.json`. Sex-specific values are assessed separately against one recorded analyte. Missing symptoms remain `NOT MEASURED` rather than being fabricated.
* If you ran Fill All, later individual sensor readings now override matching old synthetic report rows when you refresh. All source files keep the previous session/database schema and legacy-compatible entry points.
* Automatic full simulation is **disabled on startup**. Running Option 4 → 0 creates new records in the current session; rerun it to get new readings and hit dashboard Refresh.

## Send sensor values from hardware

Option **5** reads newline-delimited JSON (`.jsonl`) from a USB file, **6** receives the same packets over trusted offline TCP (`localhost:8765` by default), and **7** accepts JSONL from USB serial at `115200` baud (`pip install pyserial` if needed). Device-specific adapters must transform proprietary hardware messages into this format.

Example input (not a validated device or a clinical measurement):

```json
{"sensor":"blood_pressure","timestamp":"2026-11-14T12:00:00+00:00","origin":"device","device_id":"cuff_01","data":{"blood_pressure_systolic":118,"blood_pressure_diastolic":76}}
```

For a laboratory instrument use `sensor: "lab_analyzer"` and data channels matching JSON analyte base names (`hemoglobin`, `platelets`, etc.) with units enforced by `thresholds.json`. For a dosimetry service use `sensor: "dose_report"` with exact radiation rule keys (`lens_dose_30d`, etc.) and one declared `coverage_window`. A 30-day dosimetry report must carry `coverage_start`, `coverage_end` ISO dates covering exactly 30 days; a 1-year report requires at least 365 days. For a career report add `career_complete: "yes"`. For a nuclear-source mission report add `mission_days` and coverage dates. These are **device-declared provenance claims**, not independent authentication.

See `examples/v14_sensor_gateway_samples.jsonl` for synthetic examples. Unlike the example's simulated origin, actual device packets should set `origin: "device"`, and must use a real hardware adapter and appropriate quality/calibration controls.

## Assessment caveats

* *Assessed* means the reference rule was applied. It does not mean the instrument is calibrated or the measurement clinically validated.
* *Needs Context* means the measurement was saved but the required window, date coverage, or other provenance was not present. It is never silently treated as a safe result.
* A daily dose *rate* is not equivalent to a 30-day, annual, or career cumulative personal dose. For live exposure accumulation a dosimetry source must provide a legitimate report covering the appropriate window.
* No pain, vomiting, or symptom duration is invented by any wearable sensor. These values remain manual entry or explicit external records.
* The existing legacy engineering processing modules remain on disk for backwards compatibility, but **JSON-only session display and recording** filter out fields not referenced in the user's thresholds file. The threshold file is not included in the update.

## Test

```
python -m unittest discover -s tests -v
python -m astro_health
```

Select **4** then **0**, and open the dashboard with **9**. For historical doses, choose **12** or import a complete synthetic history using **13**.
