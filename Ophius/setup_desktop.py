#!/usr/bin/env python3
"""Create per-user desktop shortcuts on the computer where this script is run."""
import argparse
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import plistlib
import shlex

ROOT = Path(__file__).resolve().parent


def desktop_exec(arguments):
    """Quote literal .desktop Exec arguments; Exec is not a shell command."""
    def quote(argument):
        value = str(argument).replace('%', '%%')
        for char in ('\\', '"', '`', '$'):
            value = value.replace(char, '\\' + char)
        return '"' + value + '"'
    return ' '.join(quote(argument) for argument in arguments)


def linux_desktop_directory():
    command = shutil.which('xdg-user-dir')
    if command:
        result = subprocess.run([command, 'DESKTOP'], capture_output=True, text=True)
        value = result.stdout.strip()
        if result.returncode == 0 and value and Path(value).is_absolute():
            return Path(value)
    return Path.home() / 'Desktop'


def linux_entry(root=ROOT, executable=None):
    root = Path(root).resolve()
    if any(c in str(root) for c in '\n\r'):
        raise ValueError('The app folder path must not contain newlines')
    # Escape string-field backslashes independently from Exec quoting.
    field = lambda value: str(value).replace('\\', '\\\\')
    return ('[Desktop Entry]\nType=Application\nVersion=1.0\nName=Ophius\n'
            'Comment=Open the local astronaut health monitor\n'
            f'Exec={desktop_exec([executable or sys.executable, root / "launch_desktop.py"])}\n'
            f'Path={field(root)}\nIcon={field(root / "assets" / "ophius.svg")}\n'
            'Terminal=false\nCategories=Science;Education;\nStartupNotify=false\n')


def install_linux(desktop=None):
    desktop = Path(desktop) if desktop else linux_desktop_directory()
    application_dir = Path(os.environ.get('XDG_DATA_HOME', Path.home()/'.local'/'share')) / 'applications'
    targets = [desktop / 'Ophius.desktop', application_dir / 'ophius.desktop']
    content = linux_entry()
    for target in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')
        target.chmod(0o755)
    gio = shutil.which('gio')
    if gio:
        subprocess.run([gio, 'set', str(targets[0]), 'metadata::trusted', 'true'], capture_output=True)
    return targets


def install_windows(desktop=None):
    # Native known-folder discovery supports redirected/OneDrive desktops.
    script = '''$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new()
$desktop = if ($env:OPHIUS_DESKTOP) { $env:OPHIUS_DESKTOP } else { [Environment]::GetFolderPath('DesktopDirectory') }
if (-not $desktop) { throw 'Could not locate the Windows desktop folder' }
[void][IO.Directory]::CreateDirectory($desktop)
$path = Join-Path $desktop 'Ophius.lnk'
$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($path)
$shortcut.TargetPath = $env:OPHIUS_PYTHON
$shortcut.Arguments = $env:OPHIUS_ARGUMENTS
$shortcut.WorkingDirectory = $env:OPHIUS_ROOT
$shortcut.IconLocation = $env:OPHIUS_PYTHON + ',0'
$shortcut.Description = 'Open the local Ophius monitor'
$shortcut.WindowStyle = 1
$shortcut.Save()
Write-Output $path
'''
    environment = os.environ.copy()
    pythonw = Path(sys.executable).with_name('pythonw.exe')
    interpreter = str(pythonw) if pythonw.is_file() else sys.executable
    environment.update(OPHIUS_PYTHON=interpreter, OPHIUS_ROOT=str(ROOT),
                       OPHIUS_ARGUMENTS=subprocess.list2cmdline([str(ROOT/'launch_desktop.py')]),
                       OPHIUS_DESKTOP=str(desktop) if desktop else '')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                            env=environment, capture_output=True, text=True, encoding='utf-8')
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'Windows shortcut creation failed')
    return [Path(result.stdout.strip())]


def install_macos(desktop=None):
    desktop = Path(desktop) if desktop else Path.home()/'Desktop'
    application = desktop/'Ophius.app'
    executable = application/'Contents'/'MacOS'/'Ophius'
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text('#!/bin/sh\nexec '+shlex.quote(sys.executable)+' '+shlex.quote(str(ROOT/'launch_desktop.py'))+'\n',encoding='utf-8')
    executable.chmod(0o755)
    information = {'CFBundleName':'Ophius', 'CFBundleDisplayName':'Ophius',
                   'CFBundleIdentifier':'local.ophius.desktop', 'CFBundleVersion':'2.3.0',
                   'CFBundleExecutable':'Ophius', 'CFBundlePackageType':'APPL', 'NSHighResolutionCapable':True}
    with (application/'Contents'/'Info.plist').open('wb') as output:plistlib.dump(information,output)
    return [application]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--desktop-dir', type=Path, help='Optional desktop folder override')
    args = parser.parse_args()
    if sys.version_info < (3, 10):
        parser.exit(1, 'Python 3.10 or newer is required.\n')
    import importlib.util
    if importlib.util.find_spec('PySide6') is None:
        parser.exit(1, 'Run the included desktop installer to set up the embedded desktop runtime first.\n')
    try:
        system = platform.system()
        if system == 'Windows':
            paths = install_windows(args.desktop_dir)
        elif system == 'Linux':
            paths = install_linux(args.desktop_dir)
        elif system == 'Darwin':
            paths = install_macos(args.desktop_dir)
        else:
            parser.exit(1, 'Desktop shortcuts are supported on Windows, Linux and macOS.\n')
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f'Could not create desktop shortcut: {exc}\n')
    for path in paths:
        print(f'Created: {path}')
    print('Double-click Ophius to start. Keep this app folder in place.')
    if system == 'Linux':
        print('If your desktop asks, choose Allow Launching / Trust and Launch.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
