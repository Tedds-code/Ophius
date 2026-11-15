> **Development acknowledgement:** Ophius was developed in cooperation with ChatGPT, an AI assistant created by OpenAI.

# Ophius

Ophius is a desktop astronaut-health monitoring prototype. It compares incoming measurements with configured safety thresholds and personal baselines, displays warnings, and connects findings to medical reference information.

The application includes laboratory and radiation-dose assessment, allergy-aware medication checks, conditional radiation forecasts, and persistent session history.

**This is a theoretical research prototype, not a clinically validated medical device.**

## Features

- Continuous assessment of incoming vital measurements.
- Current readings displayed alongside personal baselines.
- Configurable diagnostic thresholds and treatment references.
- Exact-name and configured drug-family allergy checks.
- Radiation-dose projections using verified history or an entered future rate.
- SQLite storage for profiles, laboratory reports, daily statistics and abnormal events.
- Separate testing mode with simulated vital, laboratory and dose values.
- Desktop interface with no separately opened browser window.

## Requirements

- Python 3.10 or newer, including pip and venv.
- A graphical Windows, Linux or macOS desktop.
- Internet access during initial dependency installation.
- The complete application folder.

The desktop dependency is:

```text
PySide6>=6.7,<7
```

Serial-connected sensors additionally require:

```text
pyserial>=3.5,<4
```

SQLite is included with standard Python installations. Qt and the embedded rendering engine install through PySide6.

Linux may require additional graphical system libraries supplied by the distribution.

## Download

1. Open this project's GitHub repository.
2. Select **Code → Download ZIP**.
3. Extract the complete archive to a permanent folder.
4. Locate the `Ophius` folder containing `app.py` and the launchers.

You can alternatively clone the repository using its GitHub clone URL.

The desktop icon is created locally by the installer.

## Install the desktop shortcut

Run the installer for your operating system:

| System | Installer |
|---|---|
| Windows | Double-click `install_desktop_windows.bat` |
| Linux | Run `sh install_desktop_linux.sh` |
| macOS | Double-click `install_desktop_macos.command` |

The installer creates the `.desktop-runtime` environment, downloads the desktop dependencies and creates an **Ophius** desktop shortcut.

After installation, double-click that shortcut to run the application.

Keep the application folder in place. Re-run installation after moving it.

## Run from Windows Command Prompt

Open Command Prompt and navigate to the application folder:

```bat
cd "C:\path\to\Ophius"
```

Install the desktop runtime if needed and launch the program:

```bat
py -3 bootstrap_desktop.py --launch
```

After setup, you can run the application directly:

```bat
.desktop-runtime\Scripts\python.exe launch_desktop.py
```

To install all application dependencies, including optional serial support:

```bat
.desktop-runtime\Scripts\python.exe -m pip install -r requirements.txt
```

For a service-only session without a desktop window:

```bat
py -3 app.py --headless
```

Use Ctrl+C to stop a headless session cleanly.

## Run on Linux or macOS

From the application folder:

```sh
python3 bootstrap_desktop.py --launch
```

After installation:

```sh
.desktop-runtime/bin/python launch_desktop.py
```

## Run automated tests

From the application folder, run:

**Windows:**

```bat
py -3 -m unittest discover -s tests -v
```

**Linux/macOS:**

```sh
python3 -m unittest discover -s tests -v
```

The tests use temporary databases and check validation, thresholds, diagnostic rules, storage, forecasts, allergies and restart behavior.

Some legacy graphical checks require Tkinter and an available display; those checks are skipped when a display is unavailable.

Automated tests do not run when the desktop application starts. They verify software behavior, not clinical accuracy.

## Test simulated measurements

Simulation controls are available only in explicit testing mode.

| System | Testing launcher |
|---|---|
| Windows | `run_testing_windows.bat` |
| Linux | `sh run_testing_linux.sh` |
| macOS | `run_testing_macos.command` |

From Windows Command Prompt:

```bat
py -3 bootstrap_desktop.py --testing-mode --launch
```

Testing mode provides vital scenarios, all 12 supported laboratory measurements and all 19 configured dose quantities.

These simulations test numerical values, thresholds, warnings and medical-rule connections. They are not physiological predictions.

Testing data is stored separately from normal monitoring.

## Using the application

- Import an astronaut profile containing baseline and mission information.
- Supply sensor packets through the supported gateway or JSON import.
- Import laboratory reports manually.
- Inspect **Findings & treatments** and **Why / linked rules** for assessment details.
- Use **Session history** for retained results.
- Use **Forecasts** for conditional radiation-dose estimates.

Normal mode waits for supplied measurements; it does not automatically generate readings or perform blood tests.

## Stored data

| Mode | Database | Default local port |
|---|---|---|
| Normal monitoring | `data/astrohealth.sqlite3` | 8765 |
| Testing | `data/testing/astrohealth.sqlite3` | 8766 |

The older database filename is retained for compatibility.

Normal raw sensor samples expire after 60 seconds. Long-term history retains daily statistics, dose aggregates, laboratory reports and abnormal events.

Normal daily summaries save at UTC rollover and clean shutdown. Laboratory reports, mission anchors and abnormal events save immediately. Force-closing can lose the unfinished day's normal summary.

Mission day one begins with the first valid measurement. Reopening the same database preserves the mission start date.

## Stop the program

Choose **Quit & save** to stop monitoring and save the current summaries.

Closing the window with **X** only hides it. Monitoring continues in the background.

## Upgrade without losing history

1. Stop the old application with **Quit & save**.
2. Back up its entire `data` folder.
3. Replace the application files or extract the new version.
4. Preserve or transfer the existing `data` folder.
5. Re-run the desktop installer.

Opening a newly extracted folder without transferring its data starts with a separate, empty database.

## Project structure

```text
Ophius/
├── app.py
├── launch_desktop.py
├── bootstrap_desktop.py
├── setup_desktop.py
├── ophius/                 Python backend and desktop implementation
├── static/                 HTML, CSS and JavaScript interface
├── config/                 Thresholds, rules, treatments and medication catalog
├── profiles/               Supplied baseline profiles
├── assets/                 Application icon
├── examples/               Example input documents
├── tests/                  Automated software checks
├── requirements-desktop.txt
├── requirements.txt
├── requirements-dev.txt
├── FULL_STACK.txt
└── data/                   Local runtime history; excluded from Git
```

## Technical stack

- Python 3.10+
- PySide6 / Qt 6
- Qt WebEngine
- HTML, CSS and vanilla JavaScript
- Python standard-library HTTP server
- SQLite
- JSON and JSON Lines
- Optional pySerial

See `FULL_STACK.txt` for the detailed architecture and dependency information.

## Troubleshooting

**Another version is running:** Open the previous application and choose **Quit & save**, then launch the current version.

**History appears missing:** Check that you opened the correct mode and preserved the existing `data` folder.

**Desktop shortcut fails:** Re-run the installer from the current application folder.

**Current vital readings are empty after restarting:** Live readings require fresh input. Saved summaries remain available in Session history.

## Platform verification

Desktop operation has been checked on Linux. Windows and macOS launchers are included, but actual runtime execution on those systems has not been verified.

## License

No license is required to use the present code