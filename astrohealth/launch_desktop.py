#!/usr/bin/env python3
"""Desktop entry: open an existing monitor, or start it and open the dashboard."""
import json
import sys
import webbrowser
from urllib.error import URLError
from urllib.request import urlopen

if sys.version_info < (3, 10):
    raise SystemExit('AstroHealth requires Python 3.10 or newer: https://www.python.org/downloads/')


def main():
    from astrohealth import __version__
    if sys.argv[1:]:
        from app import main as start_monitor
        return start_monitor(['--desktop', '--open', *sys.argv[1:]])
    url = 'http://127.0.0.1:8765'
    try:
        with urlopen(url + '/api/meta', timeout=1) as response:
            metadata = json.load(response)
    except (OSError, URLError, ValueError):
        metadata = None
    if metadata and 'rules' in metadata and 'readings' in metadata:
        if metadata.get('app_version') != __version__:
            print('An older AstroHealth monitor is already running. Stop its terminal with Ctrl+C, then launch again.')
            return 1
        webbrowser.open(url)
        return 0
    from app import main as start_monitor
    return start_monitor(['--desktop', '--open'])


if __name__ == '__main__':
    raise SystemExit(main())
