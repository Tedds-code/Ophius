# Automatic mission days and accumulated measurements

Made in cooperation with ChatGPT. Educational prototype only; **not a medical device**.

## Install

Back up `data/astro_health.db`, close the CLI, and extract this ZIP directly into the project root (`C:\Documents\Git\astro-health`). Allow its `src`, `tests`, and `docs` folders to merge. The ZIP contains **no SQLite database** and does not delete existing readings. Run:

```bash
python -m unittest discover -s tests -v
python -m astro_health
```

## Mission day

- The UTC calendar date of the **first saved reading by database ID** is mission day 1.
- A reading saved or imported with a timestamp on the following UTC date is day 2, and so on, even if there was no monitoring that day.
- UTC is used to avoid daylight-saving and timezone inconsistencies. A day changes at 00:00 UTC, not local midnight.
- The software computes the mission day automatically on new readings saved through `HealthService`; manual entry no longer prompts for a day in the CLI. Already saved rows are not rewritten.
- Historical imports **use their packet timestamps**. If a later import predates the first stored reading, its day is clamped to 1; for a genuine mission, start with the correct first-day anchor. Importing pre-mission example data into a live database can set an unwanted mission epoch. To reset development data only, back up and remove `data/astro_health.db` while the CLI is closed.
- Direct calls to `Database.save_reading` bypass the service and are not assigned an automatic mission day. Application entry points should use `HealthService.record_reading`.

## Lifetime accumulations

The session summary now presents selected totals **across the whole saved database**, including prior sessions. Each individual reading is still preserved. Accumulations do not reset at session boundaries.

| Display | Computation | Important limits |
|---|---|---|
| Radiation detector counts | Sum `radiation_counts` per reading | Assumes each reading gives newly detected events, **not an instrument-running counter**; repeated imports double-count. |
| Eye images captured | Sum `eye_image_captured` event values | Number of capture records, not a medical result. |
| Device-reported cumulative radiation dose | Latest stored `radiation_dose` (uSv) | **Assumes** the instrument reports its own cumulative register. Cannot safely add values from different devices or counter resets; requires device-specific handling. |
| Estimated radiation dose | Integrate two consecutive `radiation_dose_rate` values (uSv/h), with the trapezoid rule, over the elapsed time **only if the interval is positive and <=10 seconds** | Does not invent exposure over unsampled periods, e.g. overnight. It is a software engineering estimate, **not a calibrated personal dose**. The 10-second maximum is a sampling-continuity rule, not a medical threshold; `SessionStore.accumulated_totals(max_gap_seconds=...)` is configurable. |

If only one dose-rate sample exists, **no dose estimate is displayed**. A new measurement tomorrow does not retrospectively create yesterday's missing exposure. Previous accrued estimates remain visible.

If a device reports cumulative dose, it is shown in preference to the estimated dose in the fixed-test summary, and the estimate appears separately when available. Those two values are **not added together**.

Other measurements such as temperature, heart rate, SpO2, CO2 concentration, acceleration, sound level and impedance are **not additive**. The normal per-session summary keeps the most recent valid observation for those fields. In future, genuinely cumulative measurements (e.g. steps accumulated per interval, if a validated step processor is added) should be registered with explicit semantics rather than blindly summed.

### Data provenance / caveats

The current `Reading` schema identifies the source (`simulated_radiation`, etc.) but does not persist a distinct physical device identity in SQLite. Radiation integration treats a matching source as one stream; multiple instruments sharing that source could lead to invalid integration. Raw JSONL packets preserve more metadata but are not yet used to deduplicate or reconcile instruments. **Do not use this estimator for actual astronaut radiation safety**.

### Quick test

1. Run `python -m astro_health` and select option 4 (radiation), then request 3 simulated packets.
2. Option 2: view current session summary. You should see dose rate, accumulated counts and a **small estimated accumulated dose**; both are explicitly labeled.
3. Option 8: exit. Start again tomorrow or import another dated test packet, and inspect the new session. Accumulated counts and the previously recorded dose estimate carry forward; unmeasured time is not fabricated.
4. Select any other sensor; temperature or heart rate will **not** be summed across days.
