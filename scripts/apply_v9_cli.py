# Made in cooperation with ChatGPT
"""Idempotent, strict edit to the existing CLI. Never edits the database.

Run from project root after extracting the ZIP:
    python scripts/apply_v9_cli.py
A backup .v9-backup is made before the first successful patch.
"""
from __future__ import annotations

import argparse
import ast
from pathlib import Path
import shutil
import re


def patch_cli(path: Path) -> str:
    text = path.read_text(encoding='utf-8')
    if '# v9 dashboard integration' in text:
        return 'Already patched; nothing changed.'
    # Fail safely if a newer version has a different layout.
    anchors = {
        'menu': '        self.output_function("8. Exit")',
        'manual': '        self._show_reference_comparison(stored)',
        'summary': '        values = self.sessions.summary(session_id)',
        'def': '    def _list_sessions(self):',
    }
    absent = [name for name, marker in anchors.items() if marker not in text]
    run_anchor = re.search(r'(?m)^( +)elif choice == "8":', text)
    if not run_anchor:
        absent.append('run')
    if absent:
        raise RuntimeError('CLI layout differs from v7; no changes made. Missing anchors: ' + ', '.join(absent))
    text = text.replace(anchors['menu'],
                        anchors['menu'] + '\n        self.output_function("9. Open astronaut dashboard")', 1)
    text = text.replace(anchors['manual'], anchors['manual'] + '\n        self._v9_reading_status(stored)', 1)
    # Sensor streams can be fast: show threshold warnings but not a wall of
    # green results for each packet. All statuses remain in the dashboard.
    sensor_marker = '                self.output_function(f"ID {reading_id} ({packet.origin}_{packet.sensor}): {details}")'
    if sensor_marker in text:
        text = text.replace(sensor_marker, sensor_marker + '\n                self._v9_reading_status(processed.reading, warnings_only=True)', 1)
    text = text.replace(anchors['summary'],
                        anchors['summary'] + '\n        self._v9_session_status(session_id)', 1)
    methods = '''    # v9 dashboard integration (installed via scripts/apply_v9_cli.py)
    def _v9_reading_status(self, reading, warnings_only=False):
        try:
            from astro_health.session_assessment import describe_reading
            for line in describe_reading(reading):
                if not warnings_only or line.startswith(('CAUTION:', 'CRITICAL:')):
                    self.output_function('Project reference: ' + line)
        except (OSError, ValueError, KeyError) as exc:
            self.output_function(f'Project reference unavailable: {exc}')

    def _v9_session_status(self, session_id):
        try:
            from astro_health.session_assessment import print_session_report
            print_session_report(self.sessions, session_id, output=self.output_function)
        except (OSError, ValueError, KeyError) as exc:
            self.output_function(f'Project session assessment unavailable: {exc}')

    def _v9_dashboard(self):
        try:
            from astro_health.dashboard import main
            main(['--db', str(self.service.database.database_path)])
        except (OSError, ValueError, ImportError, RuntimeError) as exc:
            self.output_function(f'Dashboard unavailable: {exc}')

'''
    text = text.replace(anchors['def'], methods + anchors['def'], 1)
    indent = run_anchor.group(1)
    text = text.replace(run_anchor.group(0),
                        indent + 'elif choice == "9":\n' + indent + '    self._v9_dashboard()\n' + run_anchor.group(0), 1)
    ast.parse(text, filename=str(path))
    backup = path.with_name(path.name + '.v9-backup')
    if not backup.exists():
        shutil.copy2(path, backup)
    path.write_text(text, encoding='utf-8')
    return f'CLI updated. Original backup saved as {backup}.'


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('--cli', type=Path, default=Path('src/astro_health/cli.py'))
    a = p.parse_args(argv)
    if not a.cli.is_file():
        p.error(f'Missing CLI: {a.cli}. Run from repository root.')
    print(patch_cli(a.cli))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
