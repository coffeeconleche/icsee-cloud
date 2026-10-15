"""Local configuration. Credentials never form part of a debug representation."""
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path


def workspace_root():
    source_root = Path(__file__).resolve().parents[2]
    default = source_root if (source_root / 'pyproject.toml').exists() else Path.cwd()
    return Path(os.environ.get('ICSEE_HOME', default)).resolve()


ROOT = workspace_root()


def read_env(path):
    values = {}
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line: continue
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def local_values():
    return {**read_env(ROOT / '.env'), **os.environ}


def configured_path(values, name, fallback):
    path = Path(values.get(name) or fallback).expanduser()
    return path if path.is_absolute() else ROOT / path


@dataclass(frozen=True)
class Settings:
    username: str = field(repr=False)
    password: str = field(repr=False)
    camera_name: str = ''
    device_id: str = field(default='', repr=False)
    region: str = 'sa'
    identity_file: Path = ROOT / 'client.local.json'
    helper_apk: Path = ROOT / 'runtime/android-helper/local-icsee-probe.apk'
    adb: Path = Path('adb')
    ffmpeg: Path = Path('ffmpeg')
    emulator: Path = Path('emulator')
    avd: str = ''
    country: str = ''

    @classmethod
    def load(cls):
        values = local_values()
        sdk = Path(values.get('ANDROID_SDK_ROOT') or values.get('ANDROID_HOME') or
                   Path.home() / 'AppData/Local/Android/Sdk')
        executable = '.exe' if os.name == 'nt' else ''
        legacy = ROOT / 'camera.local.json'
        device_id = values.get('ICSEE_DEVICE_ID', '')
        if not device_id and legacy.exists():
            device_id = json.loads(legacy.read_text(encoding='utf8')).get('cloud_id', '')
        identity = ROOT / 'client.local.json'
        if not identity.exists(): identity = ROOT / '.research/icsee-app-identity.local.json'
        helper = ROOT / 'runtime/android-helper/local-icsee-probe.apk'
        if not helper.exists(): helper = ROOT / '.research/android-probe/local-icsee-probe.apk'
        ffmpeg = ROOT / f'runtime/ffmpeg{executable}'
        if not ffmpeg.exists(): ffmpeg = Path(shutil.which('ffmpeg') or f'ffmpeg{executable}')
        return cls(values.get('ICSEE_USERNAME') or values.get('user', ''),
                   values.get('ICSEE_PASSWORD') or values.get('password', ''),
                   values.get('ICSEE_DEVICE_NAME', ''), device_id,
                   values.get('ICSEE_REGION', 'sa'),
                   configured_path(values, 'ICSEE_CLIENT_IDENTITY_FILE', identity),
                   configured_path(values, 'ICSEE_HELPER_APK', helper),
                   configured_path(values, 'ICSEE_ADB', sdk / f'platform-tools/adb{executable}'),
                   configured_path(values, 'ICSEE_FFMPEG', ffmpeg),
                   configured_path(values, 'ICSEE_EMULATOR', sdk / f'emulator/emulator{executable}'),
                   values.get('ICSEE_AVD', ''),
                   country=values.get('ICSEE_COUNTRY', '').strip().upper())
