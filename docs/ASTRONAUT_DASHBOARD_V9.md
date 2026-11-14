# Astronaut Health Monitor v9 — dashboard + project reference alerts

Made in cooperation with ChatGPT.

**Scope:** Offline software prototype, not a medical device or NASA-approved flight system. The project's validated-for-project JSON is used as supplied, including entries with `verified_by_team: false`; this does not independently validate their medical meaning. Colors represent **comparisons to the configured project references**, not a diagnosis or a mission go/no-go determination.

## Install (Windows Git Bash; your NEW repository)

1. Commit/backup your current repository and make an independent copy of `data/astro_health.db`. Shut down the CLI.
2. Extract this overlay ZIP **into the ROOT** of `Astronaut_Health_Monitor_Fresh` (or whatever your **new** repository folder is called). Merge folders. Do **not** delete any existing files. This ZIP contains only new files, not your core source or database.
3. Verify `config/thresholds.json` exists and has your current limits. This ZIP does **not** overwrite it.
4. Run `python scripts/apply_v9_cli.py` to add an option 9 to the existing CLI and automatic project-status summaries. It leaves a `src/astro_health/cli.py.v9-backup`. If the CLI differs, the script stops without modifying it; you can still run the dashboard separately.
5. In the repository root with your Python environment activated:

   ```bash
   python -m unittest discover -s tests -p 'test_v9_*.py' -v
   python -m unittest discover -s tests -v
   python -m astro_health.dashboard --db data/astro_health.db
   ```

   Or launch your original `python -m astro_health` and choose **9. Open astronaut dashboard**.

6. If Python cannot find `astro_health`, install your existing project as usual (`python -m pip install -e .`) rather than copying `src` onto arbitrary directories.

## Dashboard

- A left-hand list of sessions; a completed session means its recording run ended successfully, **not** that every planned test was performed.
- Per fixed test: `YES` or `NO` for a saved complete non-invalid, non-suspect reading. Tests that were not performed are **gray**.
- `GOOD` green = within applicable configured project reference; `CAUTION` yellow and `CRITICAL` red = a configured threshold was crossed; `UNASSESSED` gray/blue = missing thresholds, unverified dose coverage, or unusable comparison context.
- Heart rate, SpO2, skin temperature, and CO2 are assessed in their stored units. The project's original CO2 percent reference (if using v1 thresholds) is converted to ppm exactly (1% = 10,000 ppm). **These are project references, not clinical clearance.**
- Radiation is limited to seven NASA-oriented measurements already stored by v7. GCR environment rate is **never** treated as the individual's accumulated personal dose. Older particle/count modes stay retired.
- UI refreshes every five seconds; it is **read-only** and never mutates the mission database. It does not connect to sensors by itself; keep CLI ingestion running separately to record readings.
- Rows include text status as well as color for accessibility.

## Dose accumulation and predictions — important restrictions

The existing seven radiation fields alone do **not** establish whether a given value is a cumulative counter or a dose increment. Adding dose snapshots together can give dangerously false numbers. v9 therefore keeps 30-day/year/career totals and forecasts **unavailable** until the operator explicitly confirms the source semantics and coverage.

To opt in, copy `config/monitoring_settings.example.json` to `config/monitoring_settings.json` and fill in the actual mission duration and verified source semantics. Do not set `career_history_complete: true` unless all prior flight exposure/baseline is represented. For NASA-aligned **cumulative counters**, an example is:

```json
{
  "mission_days": 75,
  "career_history_complete": true,
  "interval_history_file": null,
  "dose_semantics": {
    "career_effective_dose": {"mode": "cumulative", "verified": true},
    "lens_dose": {"mode": "cumulative", "verified": true},
    "skin_dose": {"mode": "cumulative", "verified": true},
    "bfo_dose": {"mode": "cumulative", "verified": true}
  }
}
```

**Only use that example if it matches the actual instrument data.** A counter report uses **differences**, not sums, to compute observed exposure. Rolling 30-day and 1-year totals require a measurement at the beginning of the window (within 60 seconds) and a recent measurement at its end. If those are absent, v9 shows `unavailable`; it does not extrapolate or interpolate for a threshold decision.

An alternative data mode is **verified dose intervals** from a source that already provides incremented dose. Use records with explicit UTC start/end, non-overlapping intervals, source ID, correct units and `verified: true`. See `examples/radiation_intervals_EXAMPLE.jsonl`. Set `interval_history_file` to the correct JSONL path and set that field's `dose_semantics.mode` to `interval` with `verified: true`. Exact, contiguous coverage is required to compute rolling windows. Incomplete coverage remains unassessed. These interval records are *additional input*, not automatically generated from the legacy SQLite snapshots.

Projections require at least three verified cumulative samples over at least three days (or three consecutive dose intervals spanning at least three days), a confirmed career baseline and an existing configured career reference. **Forecast is a very rough linear estimate**, not a prediction of astronaut risk, an alarm clearance, or a NASA certification.

### Mission and settings caveats

- Set `mission_days` based on the actual mission period if you want a mission-year-scaled nuclear-source reference. A date inferred solely from database creation is not a verified mission duration.
- Lens, skin, and BFO windows are distinct from career counters. A latest sensor snapshot does not itself count as a 30-day dose.
- A nuclear-source reading is compared to the project's per-mission-year scale only when mission duration is set **and** `dose_semantics.nuclear_effective_dose` is `{ "mode": "mission_cumulative", "verified": true }`, confirming a mission-to-date dose rather than an isolated event.
- Environmental free-space / planetary GCR reference values remain informational design contexts, not green/red personal-health thresholds.
- The source JSON's symptom cutoffs without matching instrument data are still listed as project references, not simulated as completed tests.

## Preserved and changed files

New Python modules: `astronaut_assessment.py`, `session_assessment.py`, `radiation_trends.py`, `radiation_intervals.py`, `dashboard.py`. Your `threshold_monitor.py`, `session_store.py`, database schema, and seven-category radiation pipeline are **not** overwritten. Optional CLI patch only appends a small integration and makes a backup. Existing old radiation history is not resurrected.

## Git after testing

```bash
git status
git add src/astro_health/astronaut_assessment.py src/astro_health/session_assessment.py src/astro_health/radiation_trends.py src/astro_health/radiation_intervals.py src/astro_health/dashboard.py src/astro_health/cli.py scripts/apply_v9_cli.py tests/test_v9_*.py docs/ASTRONAUT_DASHBOARD_V9.md config/monitoring_settings.example.json examples/radiation_intervals_EXAMPLE.jsonl
git commit -m "Add astronaut dashboard and project threshold alerts"
git push
```

Do **not** stage `src/astro_health/cli.py.v9-backup`; it is your local safety backup. You may wish to add `*.v9-backup` to `.gitignore`. Also consider adding `config/monitoring_settings.json` to `.gitignore` if mission settings or IDs are private. Do not commit real astronaut medical records or raw personal data to a public repository.
