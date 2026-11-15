"""Optional Windows/Linux Tk warning window; monitor continues with dashboard closed."""
from __future__ import annotations

import queue
import webbrowser


def desktop_loop(notifications, url, stop):
    try:
        import tkinter as tk
        from tkinter import ttk
        root = tk.Tk()
    except Exception:
        return False
    root.withdraw()
    root.title('AstroHealth background monitor')

    def show(message):
        window = tk.Toplevel(root)
        window.title('AstroHealth warning')
        window.geometry('490x270')
        window.configure(bg='#101c2c')
        label = tk.Label(window, text='ASTROHEALTH · WARNING', fg='#ffb96b', bg='#101c2c',
                         font=('TkDefaultFont', 15, 'bold'), anchor='w')
        label.pack(fill='x', padx=24, pady=(22, 12))
        tk.Label(window, text=message, fg='#edf4ff', bg='#101c2c', justify='left',
                 wraplength=430).pack(fill='x', padx=24, pady=8)
        buttons = ttk.Frame(window)
        buttons.pack(fill='x', padx=24, pady=18)
        ttk.Button(buttons, text='Open dashboard', command=lambda: webbrowser.open(url)).pack(side='left')
        ttk.Button(buttons, text='Dismiss window', command=window.destroy).pack(side='right')
        # Dismiss is deliberately not clinical acknowledgment; that remains in dashboard.
        window.lift()
        window.attributes('-topmost', True)
        window.after(1200, lambda: window.winfo_exists() and window.attributes('-topmost', False))
        window.bell()

    def poll():
        if stop.is_set():
            root.destroy()
            return
        messages = []
        while True:
            try:
                messages.append(notifications.get_nowait())
            except queue.Empty:
                break
        if messages:
            show('\n\n'.join(messages[-4:]))
        root.after(500, poll)

    root.after(500, poll)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        stop.set()
    return True
