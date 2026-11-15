# AstroHealth — merged continuous monitor

A local, English-only Windows/Linux application combining Paris's crew dashboard,
symptom logic and explanations with Fresh-inspired validated sensor ingestion,
SQLite sessions, exposure-context checks and conditional forecasts.

The supplied final thresholds, updated diagnostics, treatments and two astronaut
profiles are included unchanged. This is a theoretical/research prototype; no
physical device or clinical algorithm has been validated.

## Start

Requires **Python 3.10 or newer**. There are no mandatory pip dependencies.

**Windows:** double-click `run_windows.bat`, or run:

```bat
py -3 app.py --desktop
```

**Linux:** run:

```sh
sh run_linux.sh
```

The background monitor prints its address, normally **http://127.0.0.1:8765**.
Open that address whenever you want the dashboard. It opens automatically for a
new warning. For an immediate dashboard at startup, add `--open`:

```sh
python3 app.py --desktop --open
```

Closing the browser **does not stop monitoring**. Keep the Python process running.
Press **Ctrl+C in its terminal** to save current daily summaries and stop cleanly.
The supplied launchers leave a terminal open so shutdown remains accessible.

`--desktop` adds native warning windows through Python's Tkinter. On Linux this
may require your distribution's `python3-tk` package and a graphical session.
If Tk is unavailable, monitoring and browser warning opening continue. Browser
and window focus are subject to operating-system policy. This version does not
install an operating-system startup service or system-tray integration.

Options: `--port 8766`, `--data-dir PATH`, `--no-alert-browser`, `--verbose`.
With `--no-alert-browser`, use desktop alerts or open the dashboard yourself.
Sound/browser notifications can also be enabled inside the dashboard.

## First use

1. Select A-101 or A-102. Their preflight baselines appear alongside current
   measurements. Current measurements start **missing**.
2. In the simulation controls, explicitly start normal streaming or a scenario.
   Nothing is simulated automatically at launch.
3. Try the QTc scenario to inspect the threshold-linked treatment entry.
4. Try the cardiac-arrest scenario. Heart rate runs **72 → 155 → 0 bpm** over
   approximately four seconds. A valid zero warns immediately; the preceding
   increase is recorded as context for a **possible arrest**, not confirmation.
5. Stop simulation and inspect History for abnormal events and session summaries.
6. Import `examples/blood_panel_example.json` manually to exercise blood findings.
   The file is labelled synthetic and stays separate from observed data.

For a forecast demonstration, select an astronaut without an existing later dose
acquisition, choose **Import sensor packet**, and import
`examples/mission_dose_example.json`. It is an explicitly synthetic 35 mSv
mission-to-date report. In Forecasts, enter **1 mSv/day** for **21 days**:
the result is conditional crossing of the configured **40 mSv** limit in **5 days**.
The fixed example acquisition date is 2026-11-14; update its timestamp and matching
coverage end together if needed. Its declared historical exposure is a fixture,
not a claim of actual monitoring before the first acquisition.

The first valid measurement anchors mission day one for that astronaut. Subsequent
days use elapsed UTC calendar dates, including days when the app was not running.
Simulation and observed data have independent anchors. Missing monitoring time
does not become measured exposure. Both supplied missions last 730 days.

## Continuous monitoring and storage

- Every incoming sensor reading is validated and assessed immediately.
- Normal raw readings live **only in a rolling 60-second memory buffer**. Expired
  readings disappear from current values; timestamps indicate stale sources.
- Previously active vital streams that stop reporting generate one technical
  warning after 60 seconds; a new valid sample records recovery.
- Daily/session summaries retain count, arithmetic mean, min/max, coverage,
  time-weighted mean where supported and abnormal counts.
- Dose summaries retain verified increments or declared cumulative totals.
  Cumulative snapshots are **not summed**.
- Ordinary daily summaries are saved on UTC day rollover and clean shutdown.
  The in-progress day is visible through History before the write.
- Abnormal-event records and manually imported laboratory reports are saved
  immediately. These intentionally outlive the raw buffer. Warning events include
  offending values; a possible-arrest event includes its short preceding sequence.
- Acknowledging a warning does not change measurements or declare recovery.
- Simulation and observed summaries/diagnostics are partitioned. Source labels
  remain visible. A simulation never silently supplies missing observed values.

Storage is `data/astrohealth.sqlite3`. It contains no table of ordinary raw vital
samples. Back up the data directory only after a clean shutdown, or use SQLite's
backup facilities. **Abrupt termination or a power loss can lose the unfinished
day's normal summaries**, because continuous raw persistence was deliberately
removed. Already committed abnormal events and reports remain durable.

Sessions are grouped by astronaut, UTC date and source, making long-term daily
data available without retaining the entire day's sensor stream. Sensor buffers
start empty after restart. Historical baselines and blood tests are not live vitals.

## Assessment states

| State | Meaning |
|---|---|
| Missing | No measurement was supplied |
| Stale | No sensor sample remains within the last 60 seconds |
| Invalid | Device quality is invalid/disconnected |
| Needs context | A value exists but its coverage, window or provenance is insufficient |
| Normal / caution / critical | Eligible value compared with the supplied threshold |
| Projected | Conditional future scenario, separate from the current alert level |

Normal describes assessed inputs; it does not certify that every measurement is
available. Individual missing/stale/context states stay visible. Blood-test report
dates remain visible; the application does not invent a clinical expiry period.
Missing personal baselines display **Not supplied**.

## Diagnostic and treatment data

`config/thresholds.json` is the sole numeric threshold catalog. The original
boundary policies are explicit in the engine: heart-rate critical upper and
blood-pressure caution upper limits are inclusive; other bounds use `>`/`<`.
The supplied mission-year nuclear-source dose limit scales by duration/365
(730 days gives 40 mSv). Different radiation quantities and units remain separate.

`config/diagnostic_rules.json` supplies 38 rules. `config/treatment.json` supplies
linked detailed treatment references. Their source text and warnings are displayed,
including incomplete or older references. Treatment prose is not parsed into
new diagnostic thresholds or dosing calculations. Benign guidance is suppressed
for applicable red-flag/escalation-only findings.

QTc prolongation uses the supplied sex-specific QTc thresholds and its linked
catalog entry. Potassium/magnesium have no entries in the final thresholds file,
so they do not generate automated findings or treatment selection. Unsupported
laboratory values are noted as not assessed; a report containing no supported
measurements is rejected. There is no automatic blood sampling.

Invalid/disconnected signal is a technical warning, distinct from a valid numeric
zero. A zero heart rate warns without requiring a preceding spike. A preceding
above-caution heart rate inside the 60-second buffer adds possible-arrest context.
The sequence does not prove cardiac arrest or replace checking the person/sensor.

## Radiation, CO₂ and forecasts

CO₂ comparisons require a declared, verified one-hour average in **mmHg**.
Instantaneous ppm is not silently converted or compared. Radiation reports require
the matching dose quantity/unit, coverage start/end and verification flags. Calendar
dates in Fresh reports are adapted as inclusive days; normalized timestamp intervals
use an exclusive end. Missing coverage stays unassessed.

The Forecasts tab supports measured-history trends when enough qualifying exposure
history exists, plus manually entered constant future-rate scenarios. Both require
a known current total and label all assumptions. Projection alone never creates a
current clinical alarm. Planned mission duration supports mission-limit scaling and
mission-end estimates. A future rate alone cannot establish missing current exposure.

The profiles' 120/145 mSv career baselines are retained as supplied; the documents
do not independently establish complete verified career dosimetry. A suitable
verified career report is required for a career-total assessment. No generic detector
reading is converted into organ dose. Rolling-window predictions are withheld when
the age-resolved history required to age old exposure out is unavailable.

## JSON imports and gateways

Use **Import blood test** for a manually acquired report. Fresh's
`astro_health_blood_panel_v1` format is supported: a timestamp, `synthetic` flag
and `measurements` mapping with explicit `value` and `unit`. See the example.
Use a new `report_id` for each distinct report; duplicates are rejected.

Import another crew member using their own profile JSON through **Import crew
profile**. IDs must be distinct. The profile document is the baseline reference,
not a set of current observations. Profile export is available in the Profile tab.
This version rejects same-ID replacement rather than silently rewriting history.

Normalized packets can be sent to:

```text
POST /api/astronauts/A-101/ingest
Content-Type: application/json
```

```json
{
  "packet_id": "unique-acquisition-id",
  "timestamp": "2026-11-15T12:00:00Z",
  "source": "simulation",
  "quality": "ok",
  "readings": {
    "heart_rate": {"value": 72, "unit": "bpm"},
    "spo2": {"value": 98, "unit": "%"}
  }
}
```

Use actual acquisition timestamps. Units must match the JSON catalog. Supported
source labels are `simulation`, `jsonl`, `tcp`, `serial`; quality is `ok`, `invalid`
or `disconnected`. Out-of-order per-measurement timestamps, future timestamps,
non-finite numbers, duplicate JSON keys and duplicate packet identifiers are rejected.

Fresh-style packets (`sensor`, `timestamp`, `data`, device metadata) are adapted for
PPG, ECG, cuff pressure, thermistor, hourly CO₂ and dose reports. Clean synthetic
waveform heart-rate extraction is retained as a demonstration only. Actual hardware
requires a device-specific adapter; no manufacturer's driver is included.

The optional gateway forwards existing JSONL, TCP or serial streams:

```sh
python3 gateway.py --astronaut A-101 --file examples/cardiac_sequence.jsonl --replay-now --interval 2
python3 gateway.py --astronaut A-101 --tcp 127.0.0.1:9000
python3 gateway.py --astronaut A-101 --serial /dev/ttyUSB0
```

On Windows a serial port might be `COM3`. Serial alone needs optional `pyserial`.
`--replay-now` deliberately labels rebased file packets as simulation. Data cannot
be assumed trustworthy solely because it carries a calibration/verification flag.

## Verification and architecture

```sh
python3 -m unittest discover -s tests -v
```

`astrohealth/engine.py` owns shared thresholds/rules/treatment matching.
`monitor.py` owns ingestion, buffers, context, sessions and projections.
`storage.py` owns SQLite persistence. `transport.py` adapts Fresh-style packets.
`simulation.py` owns explicit synthetic streams. `server.py` exposes only a
localhost HTTP API. `static/` contains the English dashboard.

The implementation is verified on Linux with Python 3.12 and Chromium. Windows
launchers and portable code are supplied, but native Windows execution was not
available in the build environment. Native Tk warning windows also require a
graphical desktop and have not been validated against every desktop environment.

This is a new merged data store. Historical database/state files from the two
original ZIPs are not automatically migrated or included as current observations.
