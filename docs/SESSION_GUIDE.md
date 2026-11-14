# Health-check sessions — implementation guide

Made in cooperation with ChatGPT. Educational prototype; **not a medical device**.

## Behavior

A **session** is one CLI run from startup until selecting `8` or pressing `Ctrl+C`.
The system creates a session row at startup even if no tests are performed.
Manual readings, sensor simulations, and JSONL/USB/TCP/serial packets recorded
in that run are saved as **individual append-only readings**, all linked to
one **session ID**. The raw packet log remains separate from SQLite.

The CLI saves each reading and its session association when acquired; it does
**not** wait until exit. `8`, `Ctrl+C`, and end-of-input finalize the session.
If the process is killed or power is lost, committed data survives but the
session may still be `active` until the **next startup**. The startup recovery
then marks previous active sessions `interrupted`. This is designed for **one
running CLI instance at a time**: do not run simultaneous monitors sharing the
same SQLite database.

The summary displays the **most recently saved complete non-invalid, non-suspect observation** per
predefined measurement field, not the "most accurate" value, not an average,
and not a clinical determination. Paired/multi-axis tests are selected from one complete reading; their components
are never silently mixed across different timestamps. An observation can be structurally valid
but remain medically `unassessed`. To see all readings, choose the detail
option. Unknown tests show a dash (`-`). Skipping tests is permitted; an empty
session is still `completed` on normal exit.

Radiation dose must not be added, averaged, or otherwise interpreted without
knowing the instrument's cumulative-versus-interval semantics. ECG, HRV,
SpO2, and other derived values remain unvalidated simulation outputs or
unverified device values. Medical rules are not invented.

## Menu

1. Enter a predefined manual test; confirm before saving.
2. View a session summary. Enter the session ID, then answer `yes` to see
   **all individual readings**. Enter `r12` to view individual reading ID 12
   directly, including old readings created before this update.
3. List sessions and their statuses, start/end timestamps, reading counts.
   Older unassigned readings are listed separately.
4. Simulate one of ten sensor types for a finite packet count, or continuously.
5. Import a JSON Lines file, e.g. `examples/my_sensor_test.jsonl`.
6. Receive packets from another laptop via a trusted offline local network.
7. Receive packets from a serial-connected gateway (optional `pyserial`).
8. Save/finalize this session and exit.

**Example, no hardware:** start the CLI; choose `5`, enter
`examples/my_sensor_test.jsonl`, then choose `3` to find the active session ID.
Choose `2` and enter that session ID. The summary will show the thermistor,
IMU, and CO2 fields while other test fields show `-`. Answer `yes` to see all
three original readings. Choose `8` to finish the session. Run the CLI again;
option `3` lists the old session as completed and the new session as active.

## SQLite schema migration

`SessionStore.initialize()` calls the existing `Database.initialize()` and
adds only **version 2** objects:

- `health_sessions(id, started_at, ended_at, status)`
- `session_readings(reading_id, session_id)`, with a unique `reading_id`
- `idx_session_readings_session` index
- schema_migrations record for version 2

The original `readings` and `measurement_values` tables, IDs, and values remain
unchanged. No old measurements are deleted or silently assigned to a new
session. Old unassigned readings remain viewable with `r<reading_id>`.

## Raw data and crash guarantees

Raw packets remain in `data/sensor_logs/sensor_packets.jsonl` and now include
`session_id` and `reading_id` for new entries. Earlier raw log records are not
rewritten. Each packet is appended individually; SQLite stores the processed
reading and its session link separately from the raw JSONL append. **These
operations are not one atomic transaction.** An abrupt process termination
between steps may leave an unlinked database reading or a missing raw-log
entry, although already committed records remain preserved. The summary does
not assert perfect losslessness for in-flight samples.

High-frequency and long-running recording may eventually require batching,
transactional ingestion/outbox logging, retention policies, and performance
work. These are not included in this educational update.

## Tests

From the project root with your `.venv` activated:

```bash
python -m unittest discover -s tests -v
python -m astro_health
```

The added `tests/test_sessions.py` checks migration, history retention,
associations, summary selection, empty sessions, Ctrl+C, normal exit,
interrupted recovery, simulation, manual entry, JSONL import, and dashes.
Existing CLI tests are updated to the new menu behavior. Run the full test
suite in your existing project before relying on the update.

## Hardware compatibility

This update does not alter the sensor packet schema or any processor. It works
with simulated and device-reported packets through the existing
`SensorRecorder`, and **does not add device-specific drivers**, calibration,
or clinical validation.
