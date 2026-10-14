"""Check publishable worktree sources and Git tracking without printing secrets."""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLIC_DIRS = ['src', 'tests', 'docs', 'examples', 'scripts', 'tools', 'android', '.github']
PUBLIC_ROOT = ['README.md', 'pyproject.toml', 'LICENSE', 'SECURITY.md', 'CONTRIBUTING.md',
               'THIRD_PARTY_NOTICES.md', 'MANIFEST.in', '.gitignore', '.gitattributes', '.env.example']
PRIVATE_PREFIXES = ['.research/', 'runtime/', 'recordings/', 'logs/', 'apk/', '.venv/', 'private/']
PRIVATE_SUFFIXES = ('.apk', '.apks', '.so', '.dll', '.exe', '.keystore', '.pcap', '.pcapng', '.mkv', '.mp4', '.local.json')


def matches_private_label(text, label):
    """Match a configured camera label without flagging placeholder names."""
    label = label.strip()
    if len(label) < 3 or label.casefold() in {'camera', 'your camera name', 'test camera'}:
        return False
    # Underscores delimit names in legacy launchers and recording filenames.
    return re.search(r'(?<![a-z0-9])' + re.escape(label) + r'(?![a-z0-9])', text, re.IGNORECASE) is not None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, help='Optional private report output')
    args = parser.parse_args()
    files = [ROOT/name for name in PUBLIC_ROOT if (ROOT/name).is_file()]
    for directory in PUBLIC_DIRS:
        files += [p for p in (ROOT/directory).rglob('*') if p.is_file()
                  and '__pycache__' not in p.parts and p.suffix != '.pyc'
                  and not any(part.endswith('.egg-info') for part in p.parts)]
    failures = []
    sensitive = set()
    private_labels = set()
    env = ROOT/'.env'
    if env.exists():
        for line in env.read_text(encoding='utf-8-sig').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=',1); value=value.strip().strip('"').strip("'")
                if key.strip().lower() in ('user','password','icsee_username','icsee_password','icsee_device_id') and len(value)>=8:
                    sensitive.add(value)
                if key.strip().lower() == 'icsee_device_name':
                    private_labels.add(value)
    for name in ['client.local.json','camera.local.json','.research/icsee-app-identity.local.json']:
        path=ROOT/name
        if path.exists():
            data=json.loads(path.read_text(encoding='utf8'))
            for key in ['uuid','app_key','app_secret','cloud_id']:
                value=data.get(key)
                if isinstance(value,str) and len(value)>=8:sensitive.add(value)
    for path in files:
        relative=path.relative_to(ROOT).as_posix()
        if path.suffix.lower() in PRIVATE_SUFFIXES:
            failures.append({'file':relative,'reason':'Binary/private artifact in public source tree'})
        try:text=path.read_text(encoding='utf8')
        except (UnicodeError,OSError):
            failures.append({'file':relative,'reason':'Non-text artifact in public source tree'});continue
        if any(value in text for value in sensitive):
            failures.append({'file':relative,'reason':'Matches a local credential, identity, or device identifier'})
        if any(matches_private_label(text + '\n' + relative, value) for value in private_labels):
            failures.append({'file':relative,'reason':'Matches a locally configured camera name'})
    result=subprocess.run(['git','ls-files','-z'],cwd=ROOT,capture_output=True)
    if result.returncode==0:
        for relative in result.stdout.decode('utf8').split('\0'):
            if not relative:continue
            if relative=='.env' or relative.startswith(tuple(PRIVATE_PREFIXES)) or relative.endswith(PRIVATE_SUFFIXES):
                failures.append({'file':relative,'reason':'Private/runtime artifact is tracked by Git'})
    report={'public_text_files_checked':len(files),'failures':failures,
            'scope':'Current public worktree and tracked paths; Git history is not rewritten or scanned'}
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report,indent=2))
    return 1 if failures else 0


if __name__=='__main__':raise SystemExit(main())
