# AstroHealth 2.1 — preserved desktop view

This version preserves the original dark dashboard inside its own **Qt desktop window**. It does not launch a separate browser. The embedded renderer uses a memory-only, private profile. The localhost JSON service remains available for sensor gateways and automation.

The app includes the last supplied thresholds, diagnostic rules, treatments and two separate astronaut baseline profiles. Those five input documents remain unchanged. Patient allergies and exposures now affect assessment and medication safety through explicit application logic and a separate named-family catalog.

## Requirements

- Python **3.10 or newer**.
- A graphical desktop on Windows, Linux or macOS.
- Internet access for the first setup: it installs PySide6/QtWebEngine into a local `.desktop-runtime` folder. The engine download is several hundred MB. Optional serial ingestion requires pyserial.

Use a current supported Python release from python.org or your Linux distribution. Linux also needs Python venv/pip support and the standard Qt graphical libraries. A desktop session is required. The included setup installs the embedded engine without administrator privileges; later launches work offline.

## Install and launch

1. Stop the old monitor before upgrading. Keep your `data` folder.
2. Extract the entire AstroHealth folder to a permanent location, replacing the application files when upgrading. Do not delete your database.
3. Create a desktop launcher once:

| Platform | Shortcut setup |
|---|---|
| Windows | Double-click `install_desktop_windows.bat` |
| Linux | Run `sh install_desktop_linux.sh`; allow/trust launching if prompted |
| macOS | Double-click `install_desktop_macos.command` |

Setup downloads the desktop engine and creates the shortcut. Then double-click **AstroHealth** on your desktop. The launcher starts the desktop window, or restores the already-running current-version app. Windows shortcuts use pythonw when available; Linux desktop entries run without a terminal; macOS setup creates an `.app` launcher. The setup uses your existing Python to create an isolated local runtime; Python itself is not bundled. Run setup again after moving the application folder or upgrading from version 2.0.

Direct launch alternatives:

- Windows: double-click `run_windows.bat` or run `py -3 bootstrap_desktop.py --launch`.
- Linux: `sh run_linux.sh` or `python3 bootstrap_desktop.py --launch`.
- macOS: double-click `run_macos.command` or run `python3 bootstrap_desktop.py --launch`.

Closing the window with **X** hides it while monitoring continues. Reopen the desktop shortcut to restore it. The standard minimize control keeps it in your taskbar/dock. **Quit & save** stops monitoring and saves the current daily summaries. New warnings bring a hidden/minimized window back; an already visible window keeps its control focus.

`python app.py --hidden` starts quietly until a new warning or a shortcut restore. The old `--desktop` and `--open` flags remain accepted, but never open a browser. `--port`, `--data-dir` and `--verbose` are supported. `--headless` runs the JSON gateway without any desktop window for development/gateway use.

## Using the app

- **Vitals:** current values, personal baseline, source, time and assessment. CO2 is absent when no current reading exists; it appears when a report is available and disappears when it expires.
- **Laboratory results / Radiation & exposure windows:** expand either panel on Overview, choose a scenario and click **Run lab simulation** or **Run dose simulation**. All 12 supported labs and all 19 dose quantities are covered. Use the single-measurement scenario to test a selected value. JSON import remains available.
- **Findings:** evidence, escalation, allergy context and guarded treatment references. Each lab/dose row has **Why / linked rules**, showing its effective threshold, window, reference source and the status of linked medical rules. Radiation quantities without a supplied diagnosis rule show the threshold comparison explicitly.
- **Symptoms:** select reported symptoms/context, enter manual measurements and actual recent exposures.
- **Treatments:** search condition names, medicine names and reference details. Query and focus are preserved while measurements update.
- **Medication safety:** edit recorded allergies, check a single ingredient and record medication use only if the allergy guard allows it.
- **History:** daily/session summaries, abnormal events, manual tests and medication records; export JSON.
- **Forecasts:** measured-history projections and separately entered future-rate scenarios.
- **Profile:** view/export the baseline and current medical-history document.

Simulation is **OFF at startup**. Select a mode and click **Start continuous** or **One reading / scenario**. The standard simulator supplies all seven supported vital/environment values. The heart-rate-collapse scenario runs 72 →155 →0 bpm within a few seconds. Zero triggers an immediate possible-arrest warning; signal loss is a separate technical condition. CO2 is an explicitly synthetic instrument-reported one-hour average, not an hour of actual collection by the app.

Dropdowns and search fields stay in place during refresh. Lab and dose simulations are manual numerical fixtures, not a physiological model. Hypothetical dose coverage is labelled synthetic; it never establishes observed exposure. Normal, mixed, high and missing-context reports let you compare assessment states. The low-white-cells-with-fever scenario explicitly adds a synthetic, manually reported core temperature.

## Why previous versions repeated warnings

The old startup code treated saved unacknowledged events as newly encountered warnings every time the process started. It could also report intentionally stopped simulation as sensor loss.

Version2.0 seeds the notifier with existing event IDs at startup. Old events remain in History and the pending-warning list but are not replayed as new popups. Retained laboratory/context findings are deduplicated after restart. New episodes or worsening severity notify once. Acknowledging records that you saw a warning; it does not change a reading or erase history. Intentional simulation stops and completed one-shot tests do not produce sensor-loss alarms. Unexpected loss from an active stream still warns.

## Allergy-aware assessment and medication guard

A recorded allergy is medical history. To use it in a current allergic-reaction assessment, report an **actual recent exposure** in Symptoms, along with the observed symptoms. For example, for A-101, reported amoxicillin exposure matches the recorded penicillin allergy. Existing C01/C02 rules then evaluate the symptoms and escalation criteria with that matching exposure context. History or exposure alone does not manufacture a current diagnosis.

`config/medication_allergens.json` contains explicit ingredient aliases and named-family membership. The current guard includes penicillin-family drugs and named sulfonamide antibiotics. It is a conservative configured policy, not a complete clinical cross-reactivity engine. Uncertain related-drug cases, unknown products and unknown allergy history require review; they are not labelled safe.

- Exact or named-family allergy matches block medication recording in both the desktop UI and the backend API.
- Profile A-101's penicillin allergy blocks amoxicillin and ampicillin, including identified combinations.
- Named-drug instructions/doses are withheld from applicable blocked treatment references. Medication portions lacking an identified ingredient require review.
- Avoidance guidance, such as "Avoid Midodrine", remains visible.
- Allergy edits persist in the local profile store and are audited in session history. Original bundled profile files are unchanged.
- Every attempted medication record is checked again using current profile data; a prior UI result cannot override a newly recorded allergy.

The guard does not calculate doses, prescribe alternatives, physically administer medication, or establish that a drug is safe for all other clinical reasons. Source guidance still requires appropriate medical review. The project remains a theoretical/research prototype, not a validated medical device.

## Storage and assessment

Incoming readings are checked immediately. Normal raw sensor values live only in a rolling **60-second memory buffer**. Daily summaries retain count, mean, min/max, coverage/time-weighted mean and exposure aggregates. Different units are retained separately. Cumulative dose snapshots are not summed.

Daily normal summaries commit at UTC rollover and clean shutdown. Abnormal events and imported blood reports commit immediately. Abrupt termination can lose the unfinished day's normal summary. Stored data is `data/astrohealth.sqlite3`; normal raw sensor readings have no durable raw-sample table.

Observed and synthetic data have separate source partitions and mission anchors. The first valid in-mission measurement anchors dayone; later UTC calendar days continue counting even if acquisition had gaps. A gap is not measured exposure.

Missing, stale, invalid and needs-context states remain distinct from normal/caution/critical results. Blood tests retain their collection dates rather than becoming live sensor readings. Radiation/CO2 comparisons require appropriate windows and provenance. Forecasts are conditional extrapolations, not current alarms; rolling-window forecasts are withheld when age-resolved information is insufficient.

D-dimer uses the replacement thresholds' **mg/L** units (male caution above0.4, female above0.5). Old-unit reports remain stored but unassessed under the new catalog; original baselines with differing units are flagged. No correction is guessed.

## JSON examples and gateways

Run `python make_demo_reports.py` (`python3` on Linux/macOS) to generate complete synthetic lab/dose examples. Import the blood report manually through Labs & dose and use the sensor/dose import for the dose JSON. See **SIMULATION_COVERAGE.md** for all39 distinct threshold-backed inputs and additional manual inputs. No blood tests are run automatically.

The optional localhost JSON API remains at127.0.0.1:8765. Fresh-style JSONL/TCP/serial gateways remain supported:

```sh
python3 gateway.py --astronaut A-101 --file examples/cardiac_sequence.jsonl --replay-now --interval 2
python3 gateway.py --astronaut A-101 --tcp 127.0.0.1:9000
```

The embedded desktop and gateway use the same monitor; the app never launches an external browser. Profile, lab, normalized-packet, symptom, history, forecast and acknowledgement API endpoints remain. New endpoints include `POST .../medication-check`, `POST .../medication`, `PUT .../allergies` and native `POST /api/window/show`. These remain localhost-only with origin/host checks.

## Verification

`python -m unittest discover -s tests -v` runs backend tests. Legacy widget regression tests also run when a graphical display is available. The actual Qt desktop was additionally exercised through its embedded page on Linux/Xvfb. See **VERIFICATION.md** for the checks and limits. Native execution was tested on Linux; Windows and macOS shortcut construction is covered, but actual execution on those platforms was not available.
