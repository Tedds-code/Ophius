# Astronaut Health Monitor — Sensor Integration Guide

*Made in cooperation with ChatGPT · Educational offline prototype · Not a medical device*

## 1. Architecture

```text
THERMISTOR / PPG / IMU / ECG / EDA / RADIATION / CO2 / NOISE /
BIOIMPEDANCE / EYE-IMAGE CAPTURE
       |                              |
  synthetic packets             real devices (future)
       |                              |
       |               I2C/SPI/ADC -> microcontroller/firmware
       |               USB serial / vendor software / LAN gateway
       +----------------------+-------+
                              |
                standard JSON Lines packets
                              |
         sensor_packets.py  -> structure/provenance checks
                              |
         sensor_processing.py -> engineering conversion/features
                              |
          fixed_tests.py -> identifiers and units ENFORCED
                              |
            Reading (UNCHANGED) / HealthService (UNCHANGED)
                              |
               existing SQLite, quality="unassessed"
                              |
          optional external reference_rules.json comparison

In parallel, sensor_io.SensorRecorder appends raw packets with SQLite IDs
and processing notes to data/sensor_logs/sensor_packets.jsonl.
```

The astronaut manually chooses a fixed test. A device does **not** choose its
destination: `process_packet()` maps the recognized sensor and input channels
to fixed measurement identifiers and units. The stable `Reading` class need
not change. Later, a schema migration should store `test_id`, `session_id`,
`device_id`, `calibration_id`, waveform file IDs and quality metadata explicitly.

## 2. Supported sensors and limits

| Sensor | Accepted raw/device channels | Saved `MeasurementValue` identifiers (fixed units) | What is **not** calculated |
|---|---|---|---|
| Thermistor | `adc_count` (NTC divider) or `temperature_c` | `skin_temperature` (`degC`) | Core body temperature, fever diagnosis |
| Optical PPG | `ir_samples`, optional `red_samples`, `sample_rate_hz`; or `heart_rate_bpm`, `spo2_percent` with `calibration_id` | `heart_rate` (`bpm`), `hrv_rmssd` (`ms`), optional `spo2` (`%`) | Clinically validated HR/HRV; SpO₂ **from raw LEDs**; infection/stress/hypoxia diagnosis |
| IMU | `ax_m_s2`,`ay_m_s2`,`az_m_s2` (numbers or matched-length windows), optional `gx_dps`,`gy_dps`,`gz_dps` | `acceleration_x/y/z` (`m/s^2`), optional `angular_velocity_x/y/z` (`deg/s`) | Step count or sleep stages |
| ECG | `ecg_samples`, `sample_rate_hz`; or `heart_rate_bpm` | `ecg_heart_rate` (`bpm`), optional `ecg_hrv_rmssd` (`ms`) | Arrhythmia diagnosis, QT interval, clinical ECG interpretation |
| EDA | `conductance_us` | `skin_conductance` (`uS`) | Stress or psychological state |
| Radiation dosimeter | `counts`, `dose_uSv`, `dose_rate_uSv_h` | `radiation_counts` (`count`), `radiation_dose` (`uSv`), `radiation_dose_rate` (`uSv/h`) | Counts→dose conversion without calibration; identifying GCR/SPE particle type |
| Habitat CO₂ | `co2_ppm` | `co2_concentration` (`ppm`) | Human symptoms, health impact |
| Habitat noise | `sound_level_dba`, or `audio_samples` | `sound_level` (`dBA`), or `audio_relative_rms` (`relative`) | Converting uncalibrated microphone samples to dBA |
| Bioimpedance | `impedance_ohms` | `bioimpedance` (`ohm`) | Muscle mass, fat percentage, atrophy |
| Eye imaging | `image_path` under local image root | `eye_image_captured` (`count`) | Image diagnosis / SANS assessment; image pixel interpretation |

### Important physical details

- **Thermistor:** `adc_count` uses **illustrative** 10 kΩ/β=3950, 12-bit ADC,
  thermistor-high/fixed-resistor-low divider parameters. These defaults are not
  suitable for arbitrary hardware. Change `ThermistorConfig` to datasheet and
  circuit values, then verify with calibration standards. A thermistor must be
  connected through a known divider and ADC; most laptops cannot read its
  resistance directly.
- **PPG:** a red+IR module, e.g. one communicating via I²C, returns optical
  signals. The demonstrative local-max pulse detector is tested only on clean
  synthetic waves. Clinical SpO₂ needs a validated device algorithm and
  calibration; **the code will reject a device-reported SpO₂ without at least a
  `calibration_id`**, although providing such an ID does not prove accuracy.
- **IMU:** choose the axes and units in firmware; individual sensors may report
  raw register counts or units of `g` rather than `m/s^2`. Conversion must be
  done in the device gateway using the selected full-scale range and datasheet.
  Axes are not automatically "steps" in microgravity.
- **ECG/EDA/bioimpedance:** physical acquisition requires safe, appropriate
  analog front-end circuitry and isolation. **Do not connect homemade
  mains-powered electrode circuits to a person.** Use tested/approved modules
  and a suitable isolated interface. The present code cannot replace clinical
  instrumentation or electrical safety design.
- **Radiation:** detector counts depend on efficiency, particle type, energy
  and geometry. No counts→µSv conversion is invented.
- **Noise:** `sound_level_dba` is treated as a device-reported value. For raw
  samples, relative RMS is a signal statistic, not decibels or A-weighted SPL.
- **Eye imaging:** `image_path` must be relative to
  `data/sensor_logs/eye_images/` and point to an existing nonempty `.png`,
  `.jpg`, `.jpeg`, or `.bmp` file. The database stores a capture marker, **not**
  image pixels. The JSONL log contains the filename. The synthetic PNG is a
  1-pixel placeholder, not an actual eye picture.

## 3. Hardware-independent packet protocol (JSON Lines)

Each line is ONE JSON object containing:

```json
{
  "sensor": "imu",
  "timestamp": "2026-11-11T18:00:00Z",
  "origin": "device",
  "device_id": "imu_board_01",
  "calibration_id": null,
  "data": {
    "ax_m_s2": 0.12,
    "ay_m_s2": -0.04,
    "az_m_s2": 9.79
  }
}
```

- `sensor` is fixed: `thermistor`, `ppg`, `imu`, `ecg`, `eda`, `radiation`,
  `co2`, `noise`, `bioimpedance`, or `eye_imaging`.
- `timestamp` must be ISO 8601 with UTC offset (`Z`, `+00:00`, etc.).
- `origin` is `simulated`, `device`, or `replay`. Keep simulated origins
  truthful and never disguise generated data as an actual body measurement.
- `device_id` identifies the producing gateway; it is **not** a patient ID.
- `calibration_id` is optional metadata; it does not validate a sensor.
- `data` is a bounded set of finite numeric channels, numeric arrays,
  or a short string for an image path. The receiving code checks packet
  structure, supported sensor type, and key-specific processing inputs.
- One packet can be a single sample or a **window** of waveform samples.
  A waveform window contains its own sample rate; its packet timestamp
  identifies the start of the window for our convention.
- Maximum one JSON line: 2 MB; max samples per channel: 20,000. These are
  defensive software bounds, not sensor requirements.

A PPG window (shortened here — real processing needs many samples):

```json
{
  "sensor": "ppg",
  "timestamp": "2026-11-11T18:00:00Z",
  "origin": "device",
  "device_id": "ppg_01",
  "data": {
    "sample_rate_hz": 50,
    "ir_samples": [1000, 1020, 1040, 1020, 1000],
    "red_samples": [900, 910, 920, 910, 900]
  }
}
```

Five samples illustrate the **format**, not enough for real pulse extraction.
Use CLI simulation to generate full-length sample windows.

A device with an independently calculated oxygen saturation would transmit
`{"spo2_percent": 97.0}` plus a nonempty `calibration_id`; the software
labels this **device-reported**, not confirmed medically accurate.

## 4. Five ways to supply packets

### A. Built-in simulation — no hardware

Run `python -m astro_health`, choose **4**, select a sensor, and provide a
positive packet count. Press Enter for continuous recording; press `Ctrl+C`
to stop. The default CLI waits ~1 second between simulated **packet reports**.
For PPG/ECG, every packet contains a synthetic 12-second waveform window;
this is a development fixture, **not** real-time biomedical acquisition.

### B. USB flash drive — offline recording/replay

Copy a `.jsonl` text recording onto a USB drive. Plug it into the computer.
Choose CLI option **5**, type its exact path, for example:

```text
E:/sensor_packets.jsonl
```

The program reads the file, computes supported values, and stores processed
readings in SQLite. `examples/demo_sensor_packets.jsonl` is ready to try.

**A USB flash drive is storage**, not a sensor. It cannot live-stream the
signals on its own. Replay is useful for reproducible testing.

### C. USB serial — real gateway when available

Connect a USB-capable microcontroller, which reads the physical sensor using
ADC/I²C/SPI/UART and **transmits one JSON object per line over USB serial**.
On Windows it typically appears as `COM3`, `COM4`, etc.

Install only when needed:

```bash
python -m pip install pyserial
```

Choose CLI **7** and type the port. Receiver settings are 115200 baud, UTF-8,
one JSON message per line (`\n`). The actual microcontroller firmware must
translate native registers or proprietary packets into this JSON protocol.
The generic Python receiver **cannot automatically interpret arbitrary raw
I²C/SPI registers**.

Illustrative firmware/gateway flow:

```text
initialize I2C / ADC (native device-specific code)
repeat:
    read correct sensor data
    convert registers using the hardware's range, scale and calibration
    create {sensor, timestamp UTC, origin=device, device_id, data}
    send JSON line over USB CDC serial
```

If a vendor provides a computer application that can save CSV or transmit
serial/network data, a small bridge can transform it to these JSON packets.

### D. Another laptop — trusted offline TCP connection

Connect both computers to a trusted, isolated LAN (the internet is **not**
needed). In CLI option **6**, the receiver binds to `127.0.0.1` by default
(loopback-only). To accept a second laptop, explicitly enter `0.0.0.0` and
allow TCP port 8765 through the local firewall **only on the isolated LAN**.

On the sender laptop (with the project installed), run:

```bash
python -m astro_health.sensor_demo_sender 192.168.1.100 imu --count 10
```

Replace `192.168.1.100` with the receiver's IP address. A second laptop
therefore behaves like an external sensor gateway without needing to purchase
hardware. The sender provides synthetically generated measurements.

This demo protocol has **no authentication or encryption** and should never
be exposed to an untrusted network or the internet. It accepts only one
connection at a time and the listener stops after disconnect/timeout.

### E. Native Bluetooth Low Energy or vendor USB device

These are **not yet directly implemented**, because the GATT characteristic
UUIDs, binary format, USB vendor endpoints and calibration depend on the exact
model. Bluetooth LE typically needs an optional Python library such as
`bleak`. Once a model is selected, write an adapter that builds `SensorPacket`
objects or emits JSONL; **none of the processors or fixed catalog need to
change**.

## 5. Reference JSON comparison — no invented thresholds

If you eventually obtain appropriate sourced criteria, store them at:

`data/reference_rules.json`

A safe file until then is:

```json
{"schema_version": 1, "rules": []}
```

The CLI's **view reading** action will show that no reference is available.
If a rule is present, it can be mechanically compared against the reading.
A rule requires an exact fixed measurement ID, compatible unit, at least one
finite numeric bound, `source`, and `context`. Example *format only*:

```text
{
  "schema_version": 1,
  "rules": [
    {
      "measurement_type": "<a fixed catalog ID>",
      "unit": "<matching fixed unit>",
      "lower": null,
      "upper": "<externally sourced number>",
      "source": "<reference document, page, version>",
      "context": "<population/conditions to which the rule applies>"
    }
  ]
}
```

Replace placeholders only after evidence review. No numeric clinical limits
are supplied in this project. `reference_comparison.py` returns
`no_reference`, `within_reference_range`, or `outside_reference_range`;
**these are arithmetic comparisons, not diagnoses** and do not modify
`Reading.quality`, which remains `unassessed`.

Important: the current comparator does not itself verify whether a source is
credible or matches astronaut physiology. It merely requires provenance text.
A full rules engine must implement context applicability, uncertainty and
provenance verification in the original roadmap step 3.

## 6. Logging, privacy and scale

The **processed readings** go to your original `data/astro_health.db` with
unchanged tables. Full **raw packets** go to
`data/sensor_logs/sensor_packets.jsonl`, one appended object per reading:

```json
{"reading_id": 42, "packet": {"sensor": "imu", "...": "..."}, "notes": []}
```

This shape is schematic. The actual log retains the full original packet.
It links each raw event to the numeric reading's SQLite ID. Eye images live
in `data/sensor_logs/eye_images/` with path references in the JSONL log.
These raw logs can reveal sensitive biological or environmental information;
keep the computer and removable drives secured and do not upload recordings.
The `sensor_logs` directory contains a `.gitignore` to prevent accidental
Git commits of raw recordings.

**Prototype limitations:** JSONL and SQLite writes are not a single atomic
transaction; a crash or disk-full error could leave unmatched records.
`list_readings()` currently fetches every record and is inefficient at very
high volumes. For continuous high-frequency/multi-day logging, future work
must add chunked waveform storage, per-session metadata, database batch
transactions, rotation, retention rules, overflow behavior, clock sync,
reconnect logic, provenance, sensor-signal quality and explicit data migrations.

## 7. Testing

From the project root, with `.venv` activated:

```bash
python -m unittest discover -s tests -v
```

Tests include waveform arithmetic on deterministic artificial signals, fixed
measurement units, NTC conversion, range-independent signal processing,
rejection of malformed/flat/saturated samples, all ten simulators, raw-log
linkage, file replay, mocked USB serial, loopback TCP, imaging path safety,
reference-rule validation and CLI flows. Tests create temporary databases;
they do not overwrite `data/astro_health.db`.

For the actual program:

```bash
python -m astro_health
```

To run an individual test module:

```bash
python -m unittest discover -s tests -p 'test_sensor_processing.py' -v
```

Passing tests establishes software behavior on test fixtures; it **does not**
validate a sensor's accuracy, electrical safety or medical efficacy.

## 8. Reference hardware notes

Before purchasing a board, identify: sensor IC and breakout board model,
operating and I/O voltages, bus (I²C/SPI/UART/USB/BLE), sampling rate,
output registers/units, available vendor firmware, calibration documentation,
communication protocol, safety/isolation needs, and whether the vendor's
computed values are validated for the intended application.

For background on possible **interfaces** (not endorsement of equipment):

- Analog Devices MAX30102 product page/datasheet: <https://www.analog.com/en/products/MAX30102.html>
- Bosch Sensortec BMI270 product information: <https://www.bosch-sensortec.com/en/products/motion-sensors/imus/bmi270>
- pySerial official project documentation: <https://pyserial.readthedocs.io/en/latest/shortintro.html>

Your original Gupta & Ghosh (2025) review can guide *sensor selection*, but
it does not replace hardware-specific datasheets, calibration, medical
validation, or environmental/spaceflight qualification.
