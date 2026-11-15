#!/bin/sh
cd "$(dirname "$0")" || exit 1
exec python3 bootstrap_desktop.py --testing-mode --launch "$@"
