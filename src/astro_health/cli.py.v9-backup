# Made in cooperation with ChatGPT
# File: src/astro_health/cli.py
"""CLI with fixed manual tests and complete simulated/physical sensor inputs."""

from pathlib import Path
from datetime import datetime, timezone
from threading import Event, Thread

from astro_health.fixed_manual_input import FixedManualInput
from astro_health.health_service import HealthService
from astro_health.sensor_io import (
    DuplicatePacket, SensorRecorder, packets_from_file,
    packets_from_serial, packets_from_tcp,
)
from astro_health.sensor_packets import PacketError, SENSOR_TYPES
from astro_health.reference_comparison import (
    ReferenceError, compare_reading, load_reference_rules,
)
from astro_health.sensor_processing import ProcessingError
from astro_health.sensor_simulators import simulated_stream
from astro_health.session_store import SessionStore
from astro_health.fixed_tests import FIXED_TESTS
from astro_health.sensor_history import metadata_by_reading


class HealthCLI:
    """Terminal interface for the offline educational monitor."""

    def __init__(
        self, service: HealthService, input_function=input,
        output_function=print, sensor_realtime=True,
    ):
        self.service = service
        self.input_function = input_function
        self.output_function = output_function
        self.sensor_realtime = sensor_realtime
        self.sessions = SessionStore(service.database)
        self.current_session_id = None

    def _show_menu(self):
        self.output_function("\n=== Astronaut Health Monitor ===")
        self.output_function("Offline educational prototype, NOT a medical device")
        self.output_function("1. Enter a fixed test manually")
        self.output_function("2. View session summary / reading details")
        self.output_function("3. List sessions")
        self.output_function("4. Simulate a sensor (finite or continuous)")
        self.output_function("5. Import sensor packets from JSONL / USB drive")
        self.output_function("6. Receive packets from another laptop (offline TCP)")
        self.output_function("7. Receive packets from USB serial (optional pyserial)")
        self.output_function("8. Exit")

    def _enter_reading(self):
        source = FixedManualInput(
            mission_day=0,  # suppress old manual day prompt; service assigns actual day
            input_function=self.input_function,
            output_function=self.output_function,
        )
        reading = source.read()
        self.output_function("\nReview your entry:")
        self.output_function("Mission day: calculated automatically when saved")
        self.output_function(f"Timestamp: {reading.timestamp}")
        for measurement in reading.measurements:
            self.output_function(
                f"  {measurement.measurement_type}: "
                f"{measurement.value} {measurement.unit}"
            )
        confirmation = self.input_function(
            "\nSave this reading? (yes/no): "
        ).strip().lower()
        if confirmation not in ("yes", "y"):
            self.output_function("Reading not saved.")
            return
        reading_id = self.service.record_reading(reading)
        self.sessions.attach_reading(self.current_session_id, reading_id)
        stored = self.service.get_reading(reading_id)
        self.output_function(f"Reading saved successfully with ID {reading_id}.")
        self.output_function(f"Quality status: {stored.quality}")
        self.output_function(f"Mission day: {stored.mission_day}")
        self._show_reference_comparison(stored)

    def _show_reference_comparison(self, reading):
        """Show optional JSON comparisons WITHOUT changing medical quality."""
        reference_path = (
            self.service.database.database_path.parent / "reference_rules.json"
        )
        if not reference_path.exists():
            self.output_function("No offline reference rules loaded; medically unassessed.")
            return
        try:
            rules = load_reference_rules(reference_path)
            comparisons = compare_reading(reading, rules)
        except ReferenceError as exc:
            self.output_function(f"Reference rules unavailable: {exc}")
            return
        for result in comparisons:
            self.output_function(
                f"Reference comparison for {result.measurement_type}: "
                f"{result.status}"
            )
        self.output_function("Comparisons are not diagnoses; quality remains unassessed.")

    def _list_sessions(self):
        sessions = self.sessions.list_sessions()
        if not sessions:
            self.output_function("No sessions have been saved yet.")
        else:
            self.output_function("\n=== Health-check sessions ===")
            for session in sessions:
                self.output_function(
                    f"Session {session.id} | Start: {session.started_at} | "
                    f"End: {session.ended_at or '-'} | "
                    f"Status: {session.status} | "
                    f"Readings: {session.reading_count}"
                )
        # Old readings predating session support must remain accessible.
        unassigned = self._unassigned_readings()
        if unassigned:
            self.output_function("\nHistorical readings without session IDs:")
            for reading in unassigned:
                self.output_function(f"ID: {reading.id} | Source: {reading.source}")

    def _unassigned_readings(self):
        """Older readings are retained and browsable with their original IDs."""
        connection = self.service.database._connect()
        try:
            rows = connection.execute(
                """SELECT r.id FROM readings r
                   LEFT JOIN session_readings sr ON sr.reading_id = r.id
                   WHERE sr.reading_id IS NULL ORDER BY r.id DESC"""
            ).fetchall()
        finally:
            connection.close()
        return [self.service.get_reading(row["id"]) for row in rows]

    def _view_session(self):
        raw = self.input_function(
            "Session ID (or r followed by reading ID, e.g. r12): "
        ).strip().lower()
        if raw.startswith("r"):
            raw_id = raw[1:]
            try:
                reading_id = int(raw_id)
                if reading_id <= 0:
                    raise ValueError
            except ValueError:
                self.output_function("Error: Invalid reading ID.")
                return
            self._display_reading_by_id(reading_id)
            return
        try:
            session_id = int(raw)
            if session_id <= 0:
                raise ValueError
        except ValueError:
            self.output_function("Error: Enter a positive session ID.")
            return
        session = self.sessions.get_session(session_id)
        if session is None:
            self.output_function("No session found with that ID.")
            return
        self.output_function(
            f"\n=== Session {session.id} ({session.status}) ==="
        )
        self.output_function(f"Started: {session.started_at}")
        self.output_function(f"Ended: {session.ended_at or '-'}")
        self.output_function(f"Individual readings: {session.reading_count}")
        self.output_function(f"Mission day today (UTC): {self.sessions.mission_day_now() or '-'}")
        self.output_function(
            "Summary policy: latest SAVED complete non-invalid, non-suspect test; "
            "not an accuracy or medical assessment."
        )
        values = self.sessions.summary(session_id)
        for test in FIXED_TESTS:
            # NASA radiation fields are displayed below, grouped by sensor and
            # source; avoid showing the same values twice.
            if test.sensor_type in ('radiation', 'radiation_environment'):
                continue
            parts = []
            for field in test.fields:
                entry = values.get(field.measurement_type)
                if entry is None:
                    parts.append('-' if len(test.fields) == 1 else f"{field.display_name}: -")
                else:
                    label = f"{field.display_name}: " if len(test.fields) > 1 else ''
                    parts.append(f"{label}{entry.value:g} {entry.unit} (reading {entry.reading_id})")
            self.output_function(f"{test.display_name}: " + ', '.join(parts))
        report = self.sessions.nasa_radiation_report(session_id=session_id)
        for sensor, title in (
            ('radiation', 'Astronaut radiation (THIS session)'),
            ('radiation_environment', 'Spacecraft radiation environment (THIS session)'),
        ):
            self.output_function(f"\n=== {title} ===")
            found = False
            for stream_name, measurements in report['streams'].items():
                if stream_name.split(' | ', 1)[0] != sensor:
                    continue
                found = True
                self.output_function(stream_name)
                for field, result in measurements.items():
                    if result['value'] is not None:
                        self.output_function(
                            f"  {field}: {result['value']:.8g} {result['unit']} "
                            '(latest reported snapshot)'
                        )
                    else:
                        self.output_function(f"  {field}: unavailable (conflicting observations)")
            if not found:
                self.output_function('No NASA-aligned radiation measurements in this session.')
        if report['warnings']:
            self.output_function('Radiation data warnings:')
            for warning in report['warnings']:
                self.output_function(f'  - {warning}')
        self.output_function(
            'Radiation quantities are instrument/model-reported, not independently '
            'validated or assessed against NASA compliance limits.'
        )
        if self.input_function(
            "Show ALL individual readings for this session? (yes/no): "
        ).strip().lower() in ("y", "yes"):
            for reading in self.sessions.readings_for_session(session_id):
                if reading is not None:
                    self._display_reading(reading)

    def _display_reading_by_id(self, reading_id):
        try:
            reading = self.service.get_reading(reading_id)
        except (TypeError, ValueError):
            reading = None
        if reading is None:
            self.output_function("No reading found with that ID.")
        else:
            self._display_reading(reading)

    def _display_reading(self, reading):
        self.output_function(f"\nReading ID: {reading.id}")
        self.output_function(f"Source: {reading.source}")
        self.output_function(f"Timestamp: {reading.timestamp}")
        self.output_function("Mission day: calculated automatically when saved")
        self.output_function(f"Quality: {reading.quality}")
        if reading.quality_reason:
            self.output_function(f"Quality reason: {reading.quality_reason}")
        for measurement in reading.measurements:
            self.output_function(
                f"  {measurement.measurement_type}: "
                f"{measurement.value} {measurement.unit}"
            )
        metadata = metadata_by_reading(self.service.database, reading.id)
        if metadata is not None:
            self.output_function(
                f"Device: {metadata['device_id']} | Origin: {metadata['origin']} | "
                f"Ingest: {metadata.get('ingest_channel', 'unspecified')}"
            )
            if metadata['sensor'] in ('radiation', 'radiation_environment'):
                self.output_function(
                    f"Radiation source: {metadata.get('radiation_source') or 'unknown'} | "
                    f"Environment: {metadata.get('environment') or 'unspecified'} | "
                    f"Basis: {metadata.get('measurement_basis') or 'unspecified'}"
                )
        self._show_reference_comparison(reading)

    def _recorder(self, *, ingest_channel='unspecified'):
        log_root = self.service.database.database_path.parent / "sensor_logs"
        return SensorRecorder(
            self.service, log_root / "sensor_packets.jsonl",
            image_root=log_root / "eye_images",
            session_store=self.sessions,
            session_id=self.current_session_id,
            ingest_channel=ingest_channel,
        )

    def _record_packets(self, packets, stop_event=None, *, ingest_channel='unspecified'):
        recorder = self._recorder(ingest_channel=ingest_channel)
        saved = 0
        errors = 0
        skipped = 0
        try:
            for packet in packets:
                if stop_event is not None and stop_event.is_set():
                    break
                try:
                    reading_id, processed = recorder.record(packet)
                except DuplicatePacket as exc:
                    skipped += 1
                    self.output_function(f"Duplicate packet skipped ({exc}).")
                    continue
                except (PacketError, ProcessingError) as exc:
                    errors += 1
                    self.output_function(f"Rejected {packet.sensor} packet: {exc}")
                    continue
                saved += 1
                details = ", ".join(
                    f"{m.measurement_type}={m.value:.3f} {m.unit}"
                    for m in processed.reading.measurements
                )
                self.output_function(f"ID {reading_id} ({packet.origin}_{packet.sensor}): {details}")
        except (PacketError, OSError, TimeoutError) as exc:
            errors += 1
            self.output_function(f"Input stream stopped: {exc}")
        self.output_function(
            f"Recorded {saved} readings; skipped {skipped} duplicates; "
            f"rejected {errors} packets/streams."
        )
        self.output_function(f"Raw packet log: {recorder.raw_log_path}")

    def _simulate_sensor(self):
        self.output_function("\n=== Simulated sensors ===")
        for index, sensor in enumerate(SENSOR_TYPES, start=1):
            self.output_function(f"{index}. {sensor}")
        raw = self.input_function("Choose sensor number: ").strip()
        try:
            index = int(raw)
        except ValueError:
            index = 0
        if not 1 <= index <= len(SENSOR_TYPES):
            self.output_function("Invalid sensor number.")
            return
        sensor = SENSOR_TYPES[index - 1]
        count_raw = self.input_function(
            "How many packets? (10 suggested; Enter = continuous until stopped): "
        ).strip()
        if count_raw:
            try:
                count = int(count_raw)
            except ValueError:
                count = 0
            if count <= 0:
                self.output_function("Packet count must be positive.")
                return
        else:
            count = None
        image_root = self._recorder().image_root
        packets = simulated_stream(
            sensor, count=count, realtime=self.sensor_realtime,
            image_root=image_root,
        )
        if count is not None:
            self.output_function(f"Recording {count} synthetic {sensor} packets.")
            self._record_packets(packets, ingest_channel='simulation')
            return

        # Keep reading from the terminal on the main thread. The acquisition
        # thread records packets until Enter is pressed. Ctrl+C interrupts
        # the main thread and propagates to run(), ending the session.
        stop_event = Event()
        worker_errors = []

        def record_until_stopped():
            try:
                self._record_packets(packets, stop_event=stop_event,
                                     ingest_channel='simulation')
            except Exception as exc:
                worker_errors.append(exc)

        worker = Thread(target=record_until_stopped, daemon=True)
        worker.start()
        try:
            self.input_function(
                "Continuous simulation running. Press Enter to stop "
                "and return to the menu (Ctrl+C exits the program): "
            )
        finally:
            stop_event.set()
            worker.join()

        if worker_errors:
            raise worker_errors[0]
        self.output_function(
            "Continuous simulation stopped. Session remains open."
        )

    def _import_file(self):
        path = self.input_function(
            "Path to a sensor JSONL file (USB drive is fine): "
        ).strip().strip('"')
        if not path:
            self.output_function("No file selected.")
            return
        self._record_packets(packets_from_file(Path(path)), ingest_channel='jsonl')

    def _receive_tcp(self):
        host = self.input_function(
            "Listen address (Enter = 127.0.0.1; use 0.0.0.0 only on trusted LAN): "
        ).strip() or "127.0.0.1"
        self.output_function(
            "Listening on port 8765. No authentication or encryption; "
            "use only a trusted offline LAN."
        )
        self._record_packets(packets_from_tcp(host=host, port=8765), ingest_channel='tcp')

    def _receive_serial(self):
        port = self.input_function("Serial port (e.g. COM3): ").strip()
        if not port:
            self.output_function("Serial port is required.")
            return
        self.output_function("Reading JSONL at 115200 baud. Ctrl+C exits the program.")
        try:
            self._record_packets(packets_from_serial(port, baudrate=115200),
                                 ingest_channel='serial')
        except (RuntimeError, OSError) as exc:
            self.output_function(f"Serial unavailable: {exc}")

    def run(self):
        """Start a durable session; exit 8 or Ctrl+C finalizes it."""
        self.sessions.initialize()
        recovered = self.sessions.recover_interrupted()
        if recovered:
            self.output_function(
                f"Recovered {recovered} prior interrupted session(s); "
                "previously saved readings were retained."
            )
        self.current_session_id = self.sessions.start()
        self.output_function(f"Started session {self.current_session_id}.")
        try:
            while True:
                self._show_menu()
                choice = self.input_function("\nChoose an option: ").strip()
                if choice == "1":
                    self._enter_reading()
                elif choice == "2":
                    self._view_session()
                elif choice == "3":
                    self._list_sessions()
                elif choice == "4":
                    self._simulate_sensor()
                elif choice == "5":
                    self._import_file()
                elif choice == "6":
                    self._receive_tcp()
                elif choice == "7":
                    self._receive_serial()
                elif choice == "8":
                    self.output_function("Saving session and exiting health monitor.")
                    break
                else:
                    self.output_function("Invalid option. Please choose 1 through 8.")
        except (KeyboardInterrupt, EOFError):
            self.output_function("\nInterrupted; saving session and exiting.")
        finally:
            try:
                self.sessions.finish(self.current_session_id)
            finally:
                self.current_session_id = None
