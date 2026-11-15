#!/usr/bin/env python3
"""Start or restore the native desktop; never opens a browser."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.error import URLError
from urllib.request import Request, urlopen


def show_error(message):
    message = str(message)
    try:
        if sys.platform == 'win32':
            import ctypes
            ctypes.windll.user32.MessageBoxW(0,message,'AstroHealth could not start',0x10)
        elif sys.platform == 'darwin':
            subprocess.run(['osascript','-e','on run argv\ndisplay alert "AstroHealth could not start" message (item 1 of argv)\nend run',message],check=False)
        else:
            if shutil.which('zenity'):subprocess.run(['zenity','--error','--text='+message],check=False)
            elif sys.stderr is not None:print(message,file=sys.stderr)
    except Exception:
        if sys.stderr is not None:print(message,file=sys.stderr)


def main():
    if sys.version_info < (3,10):raise RuntimeError('AstroHealth requires Python 3.10 or newer.')
    from astrohealth import __version__
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument('--testing-mode',action='store_true')
    parser.add_argument('--port',type=int)
    options,_=parser.parse_known_args()
    port=options.port if options.port is not None else (8766 if options.testing_mode else 8765)
    if '--headless' not in sys.argv[1:]:
        url=f'http://127.0.0.1:{port}'
        try:
            with urlopen(url+'/api/meta',timeout=1) as response:metadata=json.load(response)
        except (OSError,URLError,ValueError):metadata=None
        if metadata and 'rules' in metadata and 'readings' in metadata:
            if metadata.get('app_version') != __version__ or not metadata.get('native_desktop') or bool(metadata.get('testing_mode'))!=options.testing_mode:
                raise RuntimeError(f'Another AstroHealth version or mode is running on port {port}. Use Quit & save in that app, then launch this version.')
            request=Request(url+'/api/window/show',data=b'{}',headers={'Content-Type':'application/json'},method='POST')
            with urlopen(request,timeout=3) as response:response.read()
            return 0
    from app import main as start_monitor
    return start_monitor(sys.argv[1:])


if __name__ == '__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        show_error(exc)
        raise SystemExit(1)
