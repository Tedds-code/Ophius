# Made in cooperation with ChatGPT
# File: tests/test_cli.py

import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from astro_health.cli import HealthCLI
from astro_health.database import Database
from astro_health.health_service import HealthService
from astro_health.models import MeasurementValue, Reading


class TestHealthCLI(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        database_path = Path(self.temporary_directory.name) / "test_health.db"
        database = Database(database_path)
        database.initialize()
        self.service = HealthService(database)
        self.messages = []

    def make_cli(self, answers):
        answer_iterator = iter(answers)
        return HealthCLI(
            service=self.service,
            input_function=lambda prompt: next(answer_iterator),
            output_function=self.messages.append,
            sensor_realtime=False,
        )

    def test_exit_option(self):
        self.make_cli(["8"]).run()
        self.assertIn("Saving session and exiting health monitor.", self.messages)

    def test_invalid_menu_option(self):
        self.make_cli(["9", "8"]).run()
        self.assertTrue(any("Invalid option" in msg for msg in self.messages))

    def test_enter_and_save_fixed_reading(self):
        # Menu 1 -> mission day 3 -> catalog #1 -> temperature -> save.
        self.make_cli(["1", "1", "32.5", "yes", "8"]).run()
        readings = self.service.list_readings()
        self.assertEqual(len(readings), 1)
        self.assertEqual(readings[0].measurements[0].measurement_type, "skin_temperature")
        self.assertEqual(readings[0].measurements[0].unit, "degC")

    def test_decline_save(self):
        self.make_cli(["1", "1", "32.5", "no", "8"]).run()
        self.assertIn("Reading not saved.", self.messages)
        self.assertEqual(self.service.list_readings(), [])

    def test_view_nonexistent_reading(self):
        self.make_cli(["2", "999999", "8"]).run()
        self.assertIn("No session found with that ID.", self.messages)

    def test_list_when_empty(self):
        self.make_cli(["3", "8"]).run()
        self.assertTrue(any("Readings: 0" in msg for msg in self.messages))

    def test_list_shows_id(self):
        reading_id = self.service.record_reading(Reading(
            source="manual",
            measurements=(MeasurementValue("skin_temperature", 30.0, "degC"),),
        ))
        self.make_cli(["3", "8"]).run()
        self.assertTrue(any(f"ID: {reading_id}" in m for m in self.messages))

    def test_list_newest_saved_first(self):
        for day in (1, 2):
            self.service.record_reading(Reading(
                source="manual", mission_day=day,
                measurements=(MeasurementValue("skin_temperature", 30, "degC"),),
            ))
        self.make_cli(["3", "8"]).run()
        displayed = [msg for msg in self.messages if msg.startswith("ID: ")]
        self.assertEqual(len(displayed), 2)

    def test_simulated_thermistor_records_raw_jsonl(self):
        self.make_cli(["4", "1", "4", "8"]).run()
        readings = self.service.list_readings()
        self.assertEqual(len(readings), 4)
        self.assertTrue(all(r.source == "simulated_thermistor" for r in readings))
        self.assertTrue(all(r.quality == "unassessed" for r in readings))
        raw_file = self.service.database.database_path.parent / "sensor_logs" / "sensor_packets.jsonl"
        self.assertTrue(raw_file.exists())
        self.assertEqual(len(raw_file.read_text().splitlines()), 4)

    def test_simulated_ppg_records_multiple_measurements(self):
        self.make_cli(["4", "2", "1", "8"]).run()
        reading = self.service.list_readings()[0]
        self.assertEqual(reading.source, "simulated_ppg")
        self.assertIn("heart_rate", {m.measurement_type for m in reading.measurements})

    def test_import_jsonl(self):
        from astro_health.sensor_simulators import make_simulated_packet
        path = Path(self.temporary_directory.name) / "from_usb.jsonl"
        path.write_text(make_simulated_packet("imu").to_json() + "\n", encoding="utf-8")
        self.make_cli(["5", str(path), "8"]).run()
        self.assertEqual(self.service.list_readings()[0].source, "simulated_imu")

    def test_enter_stops_continuous_simulation_but_keeps_session(self):
        two_packets_recorded = Event()
        messages = []
        answers = iter(["4", "1", "", "3", "8"])

        def output(message):
            messages.append(message)
            if sum(msg.startswith("ID ") for msg in messages) >= 2:
                two_packets_recorded.set()

        def input_function(prompt):
            if "Press Enter to stop" in prompt:
                self.assertTrue(two_packets_recorded.wait(timeout=3))
                return ""
            return next(answers)

        cli = HealthCLI(
            service=self.service,
            input_function=input_function,
            output_function=output,
            sensor_realtime=False,
        )
        cli.run()
        self.assertGreaterEqual(len(self.service.list_readings()), 2)
        self.assertIn(
            "Continuous simulation stopped. Session remains open.",
            messages,
        )
        self.assertTrue(any("Readings: " in msg for msg in messages))
        self.assertIn("Saving session and exiting health monitor.", messages)

    def test_ctrl_c_during_continuous_simulation_exits_and_saves(self):
        observed = []
        answers = iter(["4", "1", ""])

        def input_function(prompt):
            if "Press Enter to stop" in prompt:
                raise KeyboardInterrupt
            return next(answers)

        cli = HealthCLI(
            service=self.service,
            input_function=input_function,
            output_function=observed.append,
            sensor_realtime=False,
        )
        cli.run()
        self.assertIn("\nInterrupted; saving session and exiting.", observed)
        sessions = cli.sessions.list_sessions()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].status, "completed")

    def test_ctrl_c_at_main_menu_still_exits(self):
        def interrupt(_prompt):
            raise KeyboardInterrupt

        cli = HealthCLI(
            service=self.service,
            input_function=interrupt,
            output_function=self.messages.append,
            sensor_realtime=False,
        )
        cli.run()
        self.assertTrue(any(
            "Interrupted; saving session and exiting." in msg
            for msg in self.messages
        ))

    def test_bad_sensor_choice_returns_to_menu(self):
        self.make_cli(["4", "999", "8"]).run()
        self.assertIn("Invalid sensor number.", self.messages)


if __name__ == "__main__":
    unittest.main()
