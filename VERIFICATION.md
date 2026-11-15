# Verification

- Python 3.12.14 on Linux: **59 automated tests passed**.
- JavaScript syntax, Python compilation and Linux launcher syntax passed.
- Chromium desktop (1440 px) and mobile (390 px): all six sections, imports, symptoms, warnings and responsive layout checked; no JavaScript/CSP errors or horizontal overflow.
- Actual timed simulation: 72 → 155 → 0 bpm over approximately four seconds; possible-arrest warning and six linked treatment references appeared.
- Explicit synthetic dose report: 35 mSv current mission total, 1 mSv/day assumed future rate, 730-day mission: configured 40 mSv limit conditionally reached in 5 days.
- Byte-for-byte preservation of all five final supplied JSON documents verified; see INPUT_MANIFEST.json.
- Automated tests cover buffer expiration, stale-stream warnings, source/profile isolation, mission epochs, abnormal retention, daily-summary restart merge, acquisition-order watermarks, duplicate rejection, units/nonfinite validation, red flags, lab rules, dose coverage, counter resets and forecasts.

Native Windows and graphical Tk warning execution were unavailable in this environment. Python standard-library code and separate Windows/Linux launchers are supplied. Physical hardware and clinical validity have not been tested.

Screenshots are in docs/screenshots/. They are illustrations of checks, not stored patient observations.
