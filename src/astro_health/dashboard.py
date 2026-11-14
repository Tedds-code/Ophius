# Made in cooperation with ChatGPT
"""Offline Tkinter astronaut dashboard; read-only over existing session SQLite.

Run: python -m astro_health.dashboard --db data/astro_health.db
No external Python packages; refresh manually or every 5 seconds.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from tkinter import messagebox, ttk
import tkinter as tk

from astro_health.session_assessment import (
    evaluate_session, load_project_configuration, radiation_for_store,
)

from astro_health.astronaut_assessment import assess_sex_references

PALETTE = {
    'good': ('#ddf7e5', '#14532d', 'GOOD'),
    'caution': ('#fff0bd', '#7c4a00', 'CAUTION'),
    'critical': ('#ffe0e0', '#991b1b', 'CRITICAL'),
    'unassessed': ('#e8eefa', '#334155', 'UNASSESSED'),
    'missing': ('#f1f5f9', '#64748b', 'NOT RECORDED'),
    'context_only': ('#e8eefa', '#334155', 'CONTEXT'),
}


def default_path(rel):
    return Path(rel)


class AstronautDashboard:
    """Display completed sessions and individual fixed-test results."""

    def __init__(self, root, store, config, settings, *, auto_refresh=True):
        self.root = root
        self.store = store
        self.config = config
        self.settings = settings
        self.auto_refresh = auto_refresh
        self.selected_session = None
        self._refresh_scheduled = False

        root.title('Astronaut Health Monitor | Crew Dashboard')
        root.geometry('1300x900')
        root.minsize(940, 650)
        root.configure(bg='#f7fafc')

        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('TFrame', background='#f7fafc')
        style.configure('TLabelframe', background='#f7fafc')
        style.configure('TLabelframe.Label', background='#f7fafc', foreground='#17243b', font=('Segoe UI', 11, 'bold'))
        style.configure('TLabel', background='#f7fafc', foreground='#25324b', font=('Segoe UI', 10))
        style.configure('Header.TLabel', font=('Segoe UI', 21, 'bold'), foreground='#132947')
        style.configure('Summary.TLabel', font=('Segoe UI', 12, 'bold'))
        style.configure('TButton', font=('Segoe UI', 10), padding=7)
        style.configure('Treeview', rowheight=33, font=('Segoe UI', 10))
        style.configure('Treeview.Heading', font=('Segoe UI', 10, 'bold'))

        header = ttk.Frame(root, padding=(20, 16))
        header.pack(fill='x')
        ttk.Label(header, text='ASTRONAUT HEALTH MONITOR', style='Header.TLabel').pack(side='left')
        ttk.Button(header, text='Refresh data', command=self.refresh).pack(side='right')
        ttk.Button(header, text='Habitat design references',
                   command=self._show_reference_only).pack(side='right', padx=(0, 8))
        ttk.Label(root, text='Offline prototype | Project reference comparisons, not medical clearance',
                  foreground='#526077').pack(anchor='w', padx=22, pady=(0, 10))

        layout = ttk.Panedwindow(root, orient='horizontal')
        layout.pack(fill='both', expand=True, padx=16, pady=(0, 10))
        left = ttk.Labelframe(layout, text='Saved sessions', padding=8)
        right = ttk.Frame(layout)
        layout.add(left, weight=1)
        layout.add(right, weight=4)

        self.sessions_tree = ttk.Treeview(left, columns=('status', 'readings'), show='tree headings', height=15)
        self.sessions_tree.heading('#0', text='Session')
        self.sessions_tree.heading('status', text='State')
        self.sessions_tree.heading('readings', text='#')
        self.sessions_tree.column('#0', width=95, stretch=False)
        self.sessions_tree.column('status', width=106, stretch=True)
        self.sessions_tree.column('readings', width=35, stretch=False, anchor='center')
        self.sessions_tree.pack(fill='both', expand=True)
        self.sessions_tree.bind('<<TreeviewSelect>>', self._selected)

        info = ttk.Frame(right, padding=(10, 2))
        info.pack(fill='x')
        self.title_var = tk.StringVar(value='Select a session')
        self.progress_var = tk.StringVar(value='Test results will appear here')
        ttk.Label(info, textvariable=self.title_var, style='Header.TLabel').pack(anchor='w')
        ttk.Label(info, textvariable=self.progress_var, style='Summary.TLabel').pack(anchor='w', pady=(2, 6))
        self.legend = ttk.Label(info, text='GREEN: within project reference  •  YELLOW: caution  •  RED: critical  •  GRAY: missing/unassessed',
                                foreground='#334155')
        self.legend.pack(anchor='w', pady=(0, 8))

        table_holder = ttk.Frame(right)
        table_holder.pack(fill='both', expand=True, padx=(10, 0))
        self.results_tree = ttk.Treeview(table_holder,
             columns=('completion', 'result', 'status', 'detail'), show='headings', height=15)
        for key, text, width in (
            ('completion', 'Recorded', 87), ('result', 'Test / Measurement', 225),
            ('status', 'Rating', 108), ('detail', 'Saved value / reason', 370)):
            self.results_tree.heading(key, text=text)
            self.results_tree.column(key, width=width, stretch=key in ('result', 'detail'))
        for status, (bg, fg, _) in PALETTE.items():
            self.results_tree.tag_configure(status, background=bg, foreground=fg)
        scroll = ttk.Scrollbar(table_holder, command=self.results_tree.yview)
        self.results_tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.results_tree.pack(side='left', fill='both', expand=True)
        self.results_tree.bind('<<TreeviewSelect>>', self._test_selected)

        lower = ttk.Frame(right, padding=(10, 6))
        lower.pack(fill='both', expand=False)
        self.detail_var = tk.StringVar(value='Click a test to see how its rating was determined.')
        ttk.Label(lower, textvariable=self.detail_var, wraplength=780).pack(anchor='w', pady=(0, 7))
        # Standard ttk.Treeview cannot apply colors to individual cells.
        # Use native Tk labels so each sex-specific comparison has its own
        # genuinely independent foreground/background color side by side.
        sex_box = ttk.Labelframe(lower, text='Same measured value / two JSON reference ranges', padding=6)
        sex_box.pack(fill='x', pady=(3, 8))
        ttk.Label(sex_box, text='No sex is inferred. Male and female columns are independent project references.',
                  foreground='#526077').grid(row=0, column=0, columnspan=4, sticky='w')
        for column, caption in enumerate(('Lab/ECG measurement', 'Recorded value', 'Male reference', 'Female reference')):
            tk.Label(sex_box, text=caption, anchor='w', bg='#f7fafc', fg='#1e293b',
                     font=('Segoe UI', 9, 'bold')).grid(row=1, column=column, padx=(3, 12), sticky='ew')
        self.sex_rows = {}
        for index, (name, caption) in enumerate((
            ('hemoglobin', 'Hemoglobin'), ('hematocrit', 'Hematocrit'),
            ('rbc', 'RBC'), ('d_dimer', 'D-dimer'), ('qtc_interval', 'QTc interval')
        ), start=2):
            tk.Label(sex_box, text=caption, bg='#f7fafc', fg='#25324b',
                     anchor='w').grid(row=index, column=0, padx=(3, 12), sticky='ew')
            val = tk.Label(sex_box, text='—', bg='#f7fafc', fg='#25324b', anchor='w')
            val.grid(row=index, column=1, padx=(3, 12), sticky='ew')
            male = tk.Label(sex_box, text='NOT RECORDED', bg='#f1f5f9', fg='#64748b',
                            anchor='center', font=('Segoe UI', 9, 'bold'), padx=5)
            male.grid(row=index, column=2, padx=(2, 9), pady=1, sticky='ew')
            female = tk.Label(sex_box, text='NOT RECORDED', bg='#f1f5f9', fg='#64748b',
                              anchor='center', font=('Segoe UI', 9, 'bold'), padx=5)
            female.grid(row=index, column=3, padx=(2, 9), pady=1, sticky='ew')
            self.sex_rows[name] = (val, male, female)
        for column in (0, 1, 2, 3):
            sex_box.grid_columnconfigure(column, weight=1)
        ttk.Label(sex_box, text='Blood-test file: CLI option 10  •  Synthetic panel: CLI option 11',
                  foreground='#526077').grid(row=7, column=0, columnspan=4, sticky='w', pady=(4, 0))
        ttk.Label(lower, text='Radiation history & trend', style='Summary.TLabel').pack(anchor='w')
        self.radiation_text = tk.Text(lower, height=8, wrap='word', font=('Consolas', 10),
                                      bg='#f0f5fa', fg='#223148', borderwidth=0, padx=12, pady=8)
        self.radiation_text.pack(fill='x')
        self.radiation_text.configure(state='disabled')
        self._tests_by_row = {}
        self.refresh()
        if auto_refresh:
            self._schedule_refresh()

    def _show_reference_only(self):
        """Display every JSON reference-only item without generating alerts."""
        from tkinter import scrolledtext
        dialog = tk.Toplevel(self.root)
        dialog.title('Reference-only habitat design information')
        dialog.geometry('790x530')
        ttk.Label(dialog, text='NOT astronaut medical-alert thresholds',
                  style='Summary.TLabel').pack(anchor='w', padx=14, pady=10)
        content = scrolledtext.ScrolledText(dialog, wrap='word', font=('Consolas', 10))
        content.pack(fill='both', expand=True, padx=14, pady=(0, 14))
        items = self.config.get('reference_only', {}).get('items', {})
        for key, entry in items.items():
            content.insert('end', (entry.get('label', key) + '\n') if isinstance(entry, dict) else (key+'\n'))
            if isinstance(entry, dict):
                for prop in ('reference_below', 'unit', 'applies_to', 'value', 'values', 'rbe_multipliers', 'note'):
                    if prop in entry:
                        content.insert('end', f'    {prop}: {entry[prop]}\n')
            content.insert('end', '\n')
        content.configure(state='disabled')

    def _schedule_refresh(self):
        if not self._refresh_scheduled:
            self._refresh_scheduled = True
            self.root.after(5000, self._auto_refresh)

    def _auto_refresh(self):
        self._refresh_scheduled = False
        if not self.root.winfo_exists():
            return
        self.refresh()
        self._schedule_refresh()

    def refresh(self):
        try:
            sessions = self.store.list_sessions()
        except Exception as exc:
            messagebox.showerror('Database unavailable', str(exc))
            return
        existing = self.selected_session
        selected = set(self.sessions_tree.selection())
        existing_items = set(self.sessions_tree.get_children())
        new_items = set()
        for session in sessions:
            iid = str(session.id)
            new_items.add(iid)
            values = (session.status.upper(), session.reading_count)
            if iid in existing_items:
                self.sessions_tree.item(iid, text=f'#{iid}', values=values)
            else:
                self.sessions_tree.insert('', 'end', iid=iid, text=f'#{iid}', values=values)
        for stale in existing_items - new_items:
            self.sessions_tree.delete(stale)
        if existing is not None and str(existing) in new_items:
            self._show_session(existing)
        elif sessions:
            self.selected_session = sessions[0].id
            self.sessions_tree.selection_set(str(self.selected_session))
            self._show_session(self.selected_session)
        else:
            self.title_var.set('No health-check sessions saved yet')
            self.progress_var.set('Use the CLI to record a test, then refresh')

    def _selected(self, _event):
        selected = self.sessions_tree.selection()
        if selected:
            try:
                self._show_session(int(selected[0]))
            except (ValueError, OSError) as exc:
                messagebox.showerror('Cannot load session', str(exc))

    def _show_session(self, session_id: int):
        self.selected_session = session_id
        view = evaluate_session(self.store, session_id, self.config, self.settings)
        label = 'Session closed successfully' if view.session_status == 'completed' else (
            'Session currently active' if view.session_status == 'active' else
            'Session interrupted; saved readings retained')
        self.title_var.set(f'Session {session_id}  |  {label}')
        self.progress_var.set(f'{view.recorded_tests} of {view.total_tests} fixed tests recorded  •  '
                              f'{len(view.warnings)} caution/critical results')
        self.results_tree.delete(*self.results_tree.get_children())
        self._tests_by_row = {}
        for index, result in enumerate(view.tests):
            iid = f't{index}'
            _, _, title = PALETTE[result.status]
            self.results_tree.insert('', 'end', iid=iid,
                values=('YES ✓' if result.recorded else 'NO', result.name, title, result.display_value),
                tags=(result.status,))
            self._tests_by_row[iid] = result
        self.detail_var.set('Click a test to see the project reference or missing context.')
        self._update_sex_references(session_id)
        self._update_radiation(session_id)

    def _test_selected(self, _event):
        selected = self.results_tree.selection()
        if selected:
            result = self._tests_by_row.get(selected[0])
            if result:
                self.detail_var.set(f'{result.name}: {result.explanation}')

    def _update_sex_references(self, session_id: int):
        import json
        from astro_health.json_catalog_simulation import load_simulation
        summary = self.store.summary(session_id)
        synthetic = None
        pointer = self.store.database.database_path.parent / 'simulations' / 'session_reports.json'
        if pointer.exists():
            try:
                filename = json.loads(pointer.read_text(encoding='utf-8')).get(str(session_id))
                if filename:
                    synthetic = load_simulation(filename, self.config)['assessments']
            except (OSError, ValueError, KeyError, TypeError):
                synthetic = None
        for name, (value_label, male_label, female_label) in self.sex_rows.items():
            measurement = summary.get(name) or summary.get(f'{name}_male') or summary.get(f'{name}_female')
            if synthetic and f'{name}_male' in synthetic:
                observed = synthetic[f'{name}_male']
                value, unit = observed['value'], observed['unit']
            elif measurement is None:
                value, unit = None, ''
            else:
                value, unit = measurement.value, measurement.unit
            value_label.configure(text=f'{value:g} {unit}' if value is not None else '—')
            comparisons = assess_sex_references(name, value, unit, self.config)
            for sex, label in (('male', male_label), ('female', female_label)):
                assessment = comparisons.get(sex)
                status = assessment.status if assessment else 'unassessed'
                bg, fg, title = PALETTE.get(status, PALETTE['unassessed'])
                label.configure(text=title, background=bg, foreground=fg)

    def _update_radiation(self, session_id=None):
        import json
        from astro_health.json_catalog_simulation import load_simulation
        if session_id is not None:
            pointer = self.store.database.database_path.parent / 'simulations' / 'session_reports.json'
            if pointer.exists():
                try:
                    paths = json.loads(pointer.read_text(encoding='utf-8'))
                    filename = paths.get(str(session_id))
                    if filename:
                        report = load_simulation(filename, self.config)
                        lines = ['SYNTHETIC report; dated daily increments, NOT instrument readings.']
                        for key, item in report['assessments'].items():
                            if key in self.config['signals'] and self.config['signals'][key].get('category') == 'radiation':
                                lines.append(f"{key}: {item['value']:g} {item['unit']} "
                                             f"({item['window']}) — {item['status'].upper()}")
                        self.radiation_text.configure(state='normal')
                        self.radiation_text.delete('1.0', 'end')
                        self.radiation_text.insert('1.0', '\n'.join(lines))
                        self.radiation_text.configure(state='disabled')
                        return
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    lines = [f'Synthetic history unavailable: {exc}']
                    self.radiation_text.configure(state='normal')
                    self.radiation_text.delete('1.0', 'end')
                    self.radiation_text.insert('1.0', '\n'.join(lines))
                    self.radiation_text.configure(state='disabled')
                    return
        try:
            analyses = radiation_for_store(self.store, self.config, self.settings)
            lines = []
            for field, item in analyses.items():
                if item.latest is None and not item.windows:
                    continue
                latest = (f'latest {item.latest:g} {item.unit}' if item.latest is not None
                          else 'latest counter snapshot unavailable')
                parts = [f'{field}: {latest}']
                if item.windows:
                    parts.extend(f'{key}: {val:g} {item.unit}' for key, val in item.windows.items())
                else:
                    parts.append('30-day/year: unavailable (missing verified coverage)')
                if item.forecast_days_to_limit is not None:
                    parts.append(f'linear trend ~{item.forecast_days_to_limit:.1f} days to '
                                 f'{item.forecast_limit:g} {item.unit} (estimate)')
                if item.notes:
                    parts.append(item.notes[-1])
                lines.append(' | '.join(parts))
            if not lines:
                lines.append('No NASA-aligned personal dose data saved yet.')
            lines.append('Environmental GCR rate is reported separately; never accumulated as personal dose.')
        except (OSError, ValueError, KeyError) as exc:
            lines = [f'Radiation history unavailable: {exc}']
        self.radiation_text.configure(state='normal')
        self.radiation_text.delete('1.0', 'end')
        self.radiation_text.insert('1.0', '\n'.join(lines))
        self.radiation_text.configure(state='disabled')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Read-only astronaut health-check dashboard')
    parser.add_argument('--db', type=Path, default=default_path('data/astro_health.db'))
    parser.add_argument('--rules', type=Path, default=default_path('config/thresholds.json'))
    parser.add_argument('--settings', type=Path, default=default_path('config/monitoring_settings.json'))
    parser.add_argument('--no-auto-refresh', action='store_true')
    args = parser.parse_args(argv)
    if not args.db.is_file():
        parser.error(f'Database not found: {args.db}; open a saved CLI session first')
    if not args.rules.is_file():
        parser.error(f'Threshold rules not found: {args.rules}')
    from astro_health.database import Database
    from astro_health.session_store import SessionStore
    root = tk.Tk()
    try:
        config, settings = load_project_configuration(args.rules, args.settings)
        store = SessionStore(Database(args.db))
        AstronautDashboard(root, store, config, settings, auto_refresh=not args.no_auto_refresh)
        root.mainloop()
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
