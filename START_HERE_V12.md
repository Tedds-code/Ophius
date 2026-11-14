# V12 — JSON-first complete synthetic measurements

**No changes to `config/thresholds.json`**, the existing SQLite database, Git history, or `.venv`.

## Installation (DO NOT EXTRACT THE ZIP)

1. Put both `Astronaut_Health_Monitor_V12_Overlay.zip` and `Astronaut_Health_Monitor_V12_Install.py` directly inside `C:\Documents\Git\Astronaut_Health_Monitor_Fresh`.
2. In Git Bash:

```bash
cd /c/Documents/Git/Astronaut_Health_Monitor_Fresh
source .venv/Scripts/activate
python Astronaut_Health_Monitor_V12_Install.py
python -m unittest discover -s tests -v
python -m astro_health
```

The installer copies the exact files from inside the ZIP to the appropriate `src/`, `tests/`, and `examples/` locations, regardless of how Windows normally handles ZIP extraction. Existing touched files are backed up under `backups/v12_.../`.

## New behavior

* **On a normal `python -m astro_health` launch**, a new session automatically gets a complete **SYNTHETIC** assessment from **all 44 uploaded JSON signal rules** plus the six condition cutoffs. The dashboard shows those rules, not unrelated old engineering measurements.
* A full **365-day synthetic dated history** is written into `data/simulations/full_catalog_normal_*.json`. Radiation exposure is represented as *daily dose increments*, with separate verified-by-simulation 30-day, annual, and **fictional full career** comparisons. The career coverage refers only to the fictional test subject; it is not a real medical history.
* CLI option **12** creates another full JSON simulation, with normal or mixed-condition scenarios.
* CLI option **13** imports an existing full synthetic history file after validating 365 consecutive dates, JSON rule agreement, units, and recalculating threshold results from its data.
* CLI option **4** offers the JSON-relevant sensor packet simulations: skin thermistor, PPG heart rate + SpO2, ECG QTc, oscillometric blood-pressure cuff, CO2 one-hour average, and radiation reporting packets. Raw data can be supplied by device/serial/TCP using the established packet format. Vendor-specific drivers require the physical device's actual protocol.
* CLI option **1** in normal use offers only manual measurements that are represented in the uploaded JSON, including sex-comparable QTc.
* Blood tests still import or simulate with options **10** and **11**. One measured value is compared independently with the male and female limits.
* Only JSON-defined rules appear in the complete synthetic session dashboard. Reference-only habitat values remain informative, not personal alerts.

## Ready-made data

* `examples/full_year_normal_synthetic.json`: all 44 rules and six conditions, 365 dated records.
* `examples/full_year_mixed_synthetic.json`: test a male-hemoglobin CAUTION / female GOOD and a blood-pressure CRITICAL.

**All readings are artificial.** The JSON thresholds are implemented as uploaded; this does not establish clinical correctness or NASA compliance. Original sensor engineering modules remain in source for historical session compatibility, but normal interactive sensor selection and synthetic status views are restricted to the JSON-related measurements. A real sensor cannot infer organ-specific absorbed doses, blood counts or an astronaut's full prior career history without validated external instruments/models and exposure records.
