"""Persist a manual stop, retire only this workspace's tasks, finalize the clip."""
import argparse
import json
import subprocess
import time
import urllib.request
from pathlib import Path
from .recorder import ROOT, write_json, utc_now


def tasks(action, names):
    for name in names:
        if not name.startswith('iCSee-Cloud-') or not all(c.isalnum() or c=='-' for c in name):
            continue
        command = (f"$t = Get-ScheduledTask -TaskName '{name}' -ErrorAction SilentlyContinue; "
                   f"if ($t) {{ {action}-ScheduledTask -TaskName '{name}'" +
                   (' -Confirm:$false' if action=='Unregister' else '') + ' | Out-Null }')
        subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],
                       capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)


def main():
    parser = argparse.ArgumentParser(description='Stop local iCSee recording jobs and preserve their clips')
    parser.parse_args()
    jobs=[]; names=[]
    for path in (ROOT/'recordings').rglob('job.json'):
        try: job=json.loads(path.read_text(encoding='utf8'))
        except (OSError,ValueError): continue
        if job.get('project') != 'icsee-cloud': continue
        task=path.parent/'scheduled-task.txt'
        if task.exists(): names.append(task.read_text(encoding='utf-8-sig').strip())
        if job.get('state')=='running':
            (path.parent/'stop.request').touch()
            jobs.append((path,job))
    # Prevent a scheduled restart while the worker finalizes its current clip.
    tasks('Disable',names)
    try:
        with urllib.request.urlopen('http://127.0.0.1:8766/status',timeout=3) as response:
            current=json.load(response)
        if current.get('recording') or current.get('camera'):
            request=urllib.request.Request('http://127.0.0.1:8766/stop',method='POST')
            urllib.request.urlopen(request,timeout=5).close()
    except (OSError,ValueError): pass
    # A worker also observes stop.request without the web page or this terminal.
    for path,job in jobs:
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            try: state=json.loads(path.read_text()).get('state')
            except (OSError,ValueError): state=None
            if state!='running': break
            # Stale jobs with no worker can be marked stopped immediately.
            target=str(path).replace("'","''")
            script=str(ROOT/'record_24h.py').replace("'","''")
            query=("$p = Get-CimInstance Win32_Process | Where-Object { "
                   "$_.Name -in @('python.exe','pythonw.exe') -and "
                   f"($_.CommandLine -like '*{script}*' -or $_.CommandLine -like '*-m icsee_cloud record*') -and $_.CommandLine -like '*{target}*' }}; "
                   "$p.ProcessId | ConvertTo-Json -Compress")
            result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',query],
                                  capture_output=True,text=True,timeout=15,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode==0 and not result.stdout.strip(): break
            time.sleep(1)
        else:
            # Only exact recorder workers for this local job may be forced to stop.
            force=query.rsplit('$p.ProcessId',1)[0]+'$p | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }'
            subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',force],
                           capture_output=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
            print('Recorder did not finish within 90 seconds; stopped its worker. Last clip may be partial.')
        latest=json.loads(path.read_text())
        if latest.get('state')=='running':
            latest.update(state='stopped',finished_utc=utc_now())
            write_json(path,latest)
    tasks('Unregister',names)
    print('Camera recording stopped. Existing clips have been kept.')
    return 0


if __name__=='__main__': raise SystemExit(main())
