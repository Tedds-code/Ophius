# Made in cooperation with ChatGPT
from pathlib import Path
from tempfile import TemporaryDirectory
import ast
import unittest


class CLIPatchTests(unittest.TestCase):
    def test_script_is_idempotent_and_backups_source(self):
        # Import the patch by path so it does not need to live inside astro_health.
        import importlib.util
        script = Path(__file__).resolve().parents[1] / 'scripts' / 'apply_v9_cli.py'
        spec = importlib.util.spec_from_file_location('apply_v9_cli', script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        source = '''class HealthCLI:
    def _show_menu(self):
        self.output_function("8. Exit")
    def _enter_reading(self):
        self._show_reference_comparison(stored)
    def _view_session(self):
        values = self.sessions.summary(session_id)
    def _list_sessions(self):
        return
    def run(self):
        if choice == "7":
            pass
        elif choice == "8":
            pass
'''
        with TemporaryDirectory() as d:
            p = Path(d) / 'cli.py'
            p.write_text(source, encoding='utf-8')
            result = module.patch_cli(p)
            self.assertIn('updated', result)
            new_source = p.read_text(encoding='utf-8')
            ast.parse(new_source)
            self.assertIn('9. Open astronaut dashboard', new_source)
            self.assertIn('self._v9_session_status(session_id)', new_source)
            self.assertEqual(p.with_name('cli.py.v9-backup').read_text(), source)
            self.assertIn('Already patched', module.patch_cli(p))


if __name__ == '__main__':
    unittest.main()
