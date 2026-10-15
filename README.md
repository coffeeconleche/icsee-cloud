# icsee-cloud

An unofficial, reverse-engineered toolkit for authenticated iCSee cloud access.
The project is organized to support camera controls and other capabilities in
addition to its current streaming and recording features.

## What works

- Automatic or optional country-based server discovery, account sign-in, and
  authorized camera selection.
- Remote HEVC live video through a headless Android helper using the vendor SDK.
- Main/substream quality selection in a browser viewer at `127.0.0.1:8766`.
- Original video with optional audio in approximately five-minute MKV clips.
- Continuous or fixed-duration recording, automatic reconnection, durable manual
  stop, and Windows Task Scheduler recovery after a process failure or user login.
- Daily recording folders and filenames in a configurable timezone (UTC by default).

Streaming has been verified with one generic, token-based RPS camera and a South
America account. Compatibility with other firmware and cloud regions requires
testing. The transport still uses the proprietary native SDK inside Android; this
is not yet a standalone Python implementation of the camera's RPS/P2P protocol.

## Repository layout

```text
src/icsee_cloud/       Python package, cloud protocol, streaming and recording
android/helper/       Our headless Java helper source and manifest
scripts/              Windows launchers and recording recovery
tools/                Local helper build and public-source checks
examples/             Placeholder configuration without live secrets
tests/                Offline tests; no account or camera required
docs/                 Setup, architecture, protocol findings and recording guide
```

Accounts, client identities, APKs, extracted SDK libraries, evidence, logs,
recordings, and downloaded runtimes are local files excluded from Git. The
external REA research tool is not part of this repository or a runtime dependency.

## Setup

Windows 11 and Python 3.12+ are the validated host environment. Install FFmpeg,
Android SDK platform/build tools, a JDK, and an ARM-compatible Android device or
emulator. No Android Studio window is needed during recording.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Edit `.env` locally with your credentials and camera name or serial. Country
selection is automatic: use the last successful country saved for this account,
or the vendor's default on a fresh setup. Successful logins save only a country
and hashed account/client identifier in the ignored `account.local.json`.
Provide a client identity in the ignored `client.local.json`, following
`examples/client.example.json`. The client identity is separate from the account
email/password. No working identity or account secret is distributed here.

If a fresh setup selects the wrong region for an account created elsewhere, set
the optional `ICSEE_COUNTRY` override to its two-letter country. A successful login
remembers it, so you can then leave the override empty again. Explicit legacy
`ICSEE_REGION=sa` or `global` settings are also supported. The client does not
sweep other regions on login failure. See [setup](docs/setup.md) for details.

Build the helper from your own locally verified APK copies, or point
`ICSEE_HELPER_APK` at your existing locally built helper. See
[setup](docs/setup.md) for the complete prerequisites and build command.

## Use

```powershell
# Live view
.\scripts\Watch.ps1

# Continuous High-quality recording with audio
.\scripts\Start-Recording.ps1

# Record for 24 hours, or select Low/video-only for another run
.\scripts\Start-Recording.ps1 -Hours 24
.\scripts\Start-Recording.ps1 -Quality low -VideoOnly

# Stop permanently while preserving clips
.\scripts\Stop-Recording.ps1
```

The viewer's **Stop recording** button also stops the job. Closing the browser or
this terminal does not stop a scheduled recording. Keep the PC powered on;
recovery after a reboot requires signing into Windows.

Clips are kept in `recordings/<camera-name>/YYYY-MM-DD/`, named by capture start
time. The browser's MJPEG preview is silent; saved clips include audio when
enabled. There is no automatic deletion. The recorder pauses below 2 GB free disk
space, and connection outages leave gaps. See [recording](docs/recording.md).

## Development

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe tools/check_public_files.py
.\.venv\Scripts\python.exe -m build
```

Offline tests and CI never log in or contact a camera. Read
[architecture](docs/architecture.md), [protocol findings](docs/protocol.md),
[contributing](CONTRIBUTING.md), and [security](SECURITY.md) before extending the
project. Use only cameras and accounts you are authorized to access.
