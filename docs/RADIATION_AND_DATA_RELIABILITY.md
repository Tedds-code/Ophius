# Radiation representation and reliable sensor recordings

*Made in cooperation with ChatGPT. Educational, offline software; **not a medical device**.*

## What this update does

This release is an **additive** update to the existing project. Session IDs,
reading IDs, the existing `Reading` model and the prior SQLite tables remain.
The application adds `sensor_packet_history` (schema migration version 3) to
associate each sensor reading with its device, packet identity, and any
radiation classification and counting mode. The original raw packet remains
in `data/sensor_logs/sensor_packets.jsonl`.

Do not delete `data/astro_health.db` to install this update. Make a backup
before installation. Pre-update readings remain accessible, but old radiation
packets have no retrospectively verified particle identification.

## Radiation types

`particle_type` is a **reported label**, never inferred from counts or dose.

| Canonical label | Meaning | Accepted alias |
|---|---|---|
| `proton` | Proton | — |
| `helium` | Helium nucleus / alpha particle | `alpha` |
| `heavy_ion` | High-Z heavy ion (HZE) | `hze` |
| `electron` | Electron / beta particle | `beta` |
| `neutron` | Neutron | — |
| `gamma` | Gamma-ray photon | `gamma_ray` |
| `x_ray` | X-ray photon | `xray` |
| `mixed` | Reported mixed field | — |
| `unknown` | Not identified (default) | — |

Neither the software nor a generic Geiger counter can identify these particle
types from a count or dose reading alone. Real devices should only set a
non-`unknown` type if they actually distinguish it, and their calibration
must be evaluated independently. GCR, solar particle events and trapped
radiation are **sources/environments**, not these particle classes; this
software does not infer where the radiation originated.

### Radiation packet fields

- `dose_rate_uSv_h`: **device-reported** equivalent dose rate (µSv/h).
- `dose_uSv`: device-reported dose in µSv. Set `dose_mode` to `interval` or
  `cumulative` to specify whether this is an increment or a running counter.
- `counts`: **integer** detector events. Set `count_mode` to `interval` or
  `cumulative` to indicate whether these are counts within one period or a
  running total. Counts cannot be converted to dose without detector calibration.
- `interval_seconds`: mandatory when using an `interval` count or dose mode.
  The packet timestamp is the **end** of the interval.
- `particle_type`: one of the canonical types above or an accepted alias.
  Omission means `unknown`.

These are illustrative JSONL packets (one complete JSON object per line):

```jsonl
{"sensor":"radiation","timestamp":"2026-11-13T10:00:00Z","origin":"simulated","device_id":"demo_counter","packet_id":"proton-001","data":{"particle_type":"proton","counts":4,"count_mode":"interval","interval_seconds":1,"dose_rate_uSv_h":0.1}}
{"sensor":"radiation","timestamp":"2026-11-13T10:00:01Z","origin":"simulated","device_id":"demo_counter","packet_id":"neutron-002","data":{"particle_type":"neutron","counts":2,"count_mode":"interval","interval_seconds":1}}
{"sensor":"radiation","timestamp":"2026-11-13T10:00:02Z","origin":"simulated","device_id":"demo_counter","packet_id":"mixed-003","data":{"particle_type":"mixed","dose_uSv":3.2,"dose_mode":"cumulative"}}
```

Numbers above are **invented software fixtures**, not spaceflight doses or
medical thresholds. A sensor can supply measurements it actually reports;
never assign invented particle types or dose conversions to real hardware.

## Packet identity, sessions and repeated tests

A `packet_id` is optional but recommended for real hardware. If present,
`(sensor, device_id, packet_id)` uniquely identifies a transmission. If absent,
the program fingerprints `(sensor, device_id, acquisition timestamp,
calibration ID, payload)` and ignores an identical retransmission, even when
imported under `origin=replay`. Equal values taken at **different times** are
separate readings. The same JSONL file can be imported twice without doubling
its sensor readings **after this update**.

Duplicate packets are skipped rather than moved into the current session.
The first session keeps the original reading ID. The `health_sessions` and
`session_readings` relationships are unchanged. Manual entries are **not**
automatically deduplicated; two real manual tests can legitimately agree.

Duplicate detection is based on standardized packet identity; it does not
prove two different packets represent independent exposure. The SQLite
fingerprint constraint enforces unique metadata, but DB writes, session linking
and JSONL append still happen as separate operations. Simultaneous imports from
separate running processes and abrupt crashes between writes are not fully
transaction-safe. Use a single recording process for this prototype.

## Radiation accounting

The session summary still displays the latest complete suitable test reading.
A **separate lifetime radiation breakdown** lists the reported particle types,
including `-` where absent, and keeps these meanings distinct:

- **Interval counts:** summed only for nonoverlapping intervals from the same
  `device_id` and particle type. Overlapping observations are retained as raw
  readings but omitted from the count total.
- **Cumulative counts:** latest reported counter value per device and particle
  type; older snapshots are not added again.
- **Interval dose:** summed for nonoverlapping intervals, with explicit units.
- **Cumulative dose:** latest device-reported value per device, never a sum of
  successive snapshots.
- **Estimated dose from dose rate:** short observed gaps only (default: max
  10 seconds); this is an *engineering estimate*, not a medically validated dose.
- **Legacy readings:** old entries remain, classified `unknown` if there was
  no particle metadata. Unspecified older counters keep compatibility totals,
  which should not be treated as validated exposure.

Cumulative values from **multiple independent dosimeters** must not be treated
as one astronaut's biologically weighted dose. Different particle types and
instruments can be subject to overlap, device response limitations and
calibration; no medical or dose-equivalent risk decision is implemented.

Other sensors retain their existing fixed tests and summary semantics:
heart rate, temperature, SpO₂, CO₂ and other instantaneous values are **not
summed**. The eye capture count retains its running count, but unique image
content detection is not yet implemented. Noise exposure, sleep analysis and
clinical-quality PPG/ECG processing remain future work.

## How to test

1. Back up `data/astro_health.db` and exit the CLI.
2. Merge this ZIP into the project **root** (not into a nested folder).
3. Run `python -m unittest discover -s tests -v`.
4. Run `python -m astro_health`, option **4**, choose **radiation**, and simulate
   at least nine packets. The simulator cycles through the nine canonical
   particle labels, all **synthetic**.
5. Select option **2** to view the current session's summary; inspect the
   **Radiation by reported particle type** section.
6. Import a JSONL test file with option **5**, then import the **same file**
   again. The second import reports duplicates skipped rather than new
   readings. Select option **3** to verify session reading counts.
7. Press **Enter** to stop a continuous simulation without exiting. Option
   **8** or **Ctrl+C** still closes the session and exits.

Note: the fixed mission-day policy remains as previously implemented. This
update does **not** introduce medical criteria or alter the mission-day origin.
