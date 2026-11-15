"""One-time, per-app desktop runtime setup. No administrator privileges required."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import venv

ROOT=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--launch',action='store_true')
    parser.add_argument('--desktop-dir',type=Path)
    args=parser.parse_args()
    if sys.version_info<(3,10):parser.exit(1,'Python 3.10 or newer is required.\n')
    environment=ROOT/'.desktop-runtime'
    python=environment/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    if not python.exists():
        print('Creating the local desktop runtime…',flush=True)
        venv.EnvBuilder(with_pip=True).create(environment)
    check=subprocess.run([str(python),'-c','from PySide6.QtWebEngineWidgets import QWebEngineView'],capture_output=True)
    if check.returncode:
        print('Installing the embedded desktop engine. This first-time download may take several minutes.',flush=True)
        subprocess.run([str(python),'-m','pip','install','-r',str(ROOT/'requirements-desktop.txt')],check=True)
    command=[str(python),str(ROOT/'setup_desktop.py')]
    if args.desktop_dir:command+=['--desktop-dir',str(args.desktop_dir)]
    subprocess.run(command,check=True)
    if args.launch:
        target=python.with_name('pythonw.exe') if os.name=='nt' and python.with_name('pythonw.exe').exists() else python
        subprocess.Popen([str(target),str(ROOT/'launch_desktop.py')],cwd=ROOT)
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,subprocess.CalledProcessError) as exc:
        print('Desktop setup failed: '+str(exc),file=sys.stderr);raise SystemExit(1)
