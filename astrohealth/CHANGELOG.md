# Version 1.1

- Replaced thresholds.json with the latest uploaded file, unchanged byte-for-byte.
- D-dimer now uses mg/L: male caution above0.4, female above0.5. Stored old-unit results are unassessed; original baseline units remain visible with a mismatch notice.
- SQLite daily summaries migrate transactionally to retain different units separately.
- Treatment searches include medicine names and details; query, cursor/focus and filters persist through two-second refreshes. Symptom/context search supports multiword queries and no-match feedback.
- Added actual Windows .lnk and Linux .desktop shortcut installers; shortcuts start the backend and open the dashboard, or reopen a running current-version app.
- Added missing cabin CO2 synthetic one-hour-average reading and high-CO2 scenario.
- Added explicit manual symptom-duration field used by the condition cutoffs.
- Added on-demand dated JSON generator covering all12 supported lab measurements and all19 configured radiation quantities. No automatic lab tests.
- All changes stay private. No historical data is included in the distribution.
