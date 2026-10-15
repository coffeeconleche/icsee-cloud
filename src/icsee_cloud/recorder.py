"""Record the selected camera until its deadline or a durable stop request."""
import argparse
import ctypes
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .viewer import FFMPEG, ROOT, SETTINGS, LiveView, serve
from .media import parse_resolution

from .config import local_values
RECORDING_TIMEZONE = local_values().get('ICSEE_RECORDING_TIMEZONE', 'UTC')
RECORDING_ZONE = ZoneInfo(RECORDING_TIMEZONE)


def recording_now():
    return datetime.now(RECORDING_ZONE)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2), encoding='utf8')
    os.replace(temporary, path)


class Recorder(LiveView):
    def __init__(self, job_path, job):
        super().__init__(job['port'])
        self.job_path = job_path
        self.job = job
        self.destination = job_path.parent
        self.clips_destination = Path(job.get('clip_root', str(self.destination)))
        self.clips_destination.mkdir(parents=True, exist_ok=True)
        self.deadline = job['deadline_epoch']
        self.segment_seconds = job['segment_seconds']
        self.recording_quality = job['quality']
        self.requested_quality = self.recording_quality
        self.events = self.destination / 'events.jsonl'
        self.finished = False
        self.reconnects = 0
        self.disk_ok = True
        self.audio_enabled = bool(job.get('audio', False))
        if job.get('minimum_resolution'):
            self.minimum_resolution = parse_resolution(job['minimum_resolution'])

    def deadline_reached(self):
        return self.deadline is not None and time.time() >= self.deadline

    def wait_seconds(self, requested):
        return requested if self.deadline is None else min(requested, max(0, self.deadline-time.time()))

    def request_stop(self):
        # Persist intent before acknowledging Stop, including across a process crash.
        (self.destination / 'stop.request').touch()
        super().request_stop()

    def feed_source(self, session, process):
        if not self.audio_enabled:
            return super().feed_source(session, process)
        from .media import AudioVideoMux, read_frame
        mux = AudioVideoMux(process.stdin,
                            on_video_format=lambda width, height: self.observe_video_format(session, width, height))
        session.audio_started = time.time()
        try:
            while not session.stop.is_set() and not self.stop.is_set():
                try: kind, raw, arrival_ms = read_frame(session.source)
                except EOFError: break
                mux.ingest(kind, raw)
                with self.condition:
                    if kind == 1: session.video_bytes += max(0, len(raw)-8)
                    else:
                        session.audio_frames += 1
                        session.last_audio = time.time()
        finally:
            mux.close()

    def event(self, name, **details):
        # Deliberately exclude exception text and SDK/account payloads.
        entry = {'at_utc': utc_now(), 'at_local': recording_now().isoformat(), 'event': name, **details}
        with self.events.open('a', encoding='utf8') as output:
            output.write(json.dumps(entry) + '\n')
        print(json.dumps(entry), flush=True)

    def ffmpeg_command(self, session):
        self.prepare_day_folders()
        stamp = recording_now().strftime('%Y%m%dT%H%M%S')
        tag = re.sub(r'[^a-zA-Z0-9_-]', '', recording_now().tzname())
        identity = uuid.uuid4().hex[:12]
        session.recording_prefix = f'camera-{session.quality}-{stamp}-{identity}'
        clips = self.clips_destination / '%Y-%m-%d' / f'camera-{session.quality}-%Y-%m-%d_%H-%M-%S-{tag}-{identity}.mkv'
        session.timezone_offset = recording_now().utcoffset()
        manifest = self.destination / (session.recording_prefix + '-clips.csv')
        command = [str(FFMPEG), '-hide_banner', '-loglevel', 'warning', '-nostdin',
                '-fflags', '+genpts', '-probesize', '131072', '-analyzeduration', '1000000',
                '-f', 'nut' if self.audio_enabled else 'hevc', '-i', 'pipe:0',
                # Copy original HEVC into independent, recoverable Matroska clips.
                '-map', '0:v:0', '-c:v', 'copy']
        command += (['-map', '0:a:0', '-c:a', 'aac', '-b:a', '32k']
                    if self.audio_enabled else ['-an'])
        command += ['-f', 'segment',
                '-segment_time', str(self.segment_seconds), '-segment_atclocktime', '1',
                '-strftime', '1', '-reset_timestamps', '1',
                '-segment_format', 'matroska', '-segment_list', str(manifest),
                '-segment_list_type', 'csv', str(clips),
                # The browser gets a separate decoded preview of the same source.
                '-map', '0:v:0', '-an', '-vf', 'fps=8', '-c:v', 'mjpeg', '-q:v', '4',
                '-f', 'image2pipe', 'pipe:1']
        return command

    def ffmpeg_environment(self):
        # The Windows C runtime needs a numeric POSIX offset, not an IANA name.
        # Apply it only to FFmpeg; the PC's display timezone is unchanged.
        seconds = int(recording_now().utcoffset().total_seconds())
        sign = '-' if seconds >= 0 else '+'
        hours, remainder = divmod(abs(seconds), 3600)
        minutes = remainder // 60
        return dict(os.environ, TZ=f'LOC{sign}{hours:02d}:{minutes:02d}')

    def prepare_day_folders(self):
        today = recording_now().date()
        for offset in (0, 1):
            (self.clips_destination / (today+timedelta(days=offset)).isoformat()).mkdir(parents=True, exist_ok=True)

    def request_quality(self, quality):
        return 409, {'error': 'Recording quality is fixed for this job'}

    def recording_status(self):
        clips = list(self.clips_destination.rglob('*.mkv'))
        sizes = []
        for clip in clips:
            try: sizes.append(clip.stat().st_size)
            except OSError: pass
        return {'active': not self.finished and not self.stop.is_set(),
                'audio_enabled': self.audio_enabled,
                'audio_codec': 'AAC' if self.audio_enabled else None,
                'audio_frames_received': self.session.audio_frames if self.session else 0,
                'last_audio_age_seconds': (round(time.time()-self.session.last_audio, 2)
                                           if self.session and self.session.last_audio else None),
                'quality': self.recording_quality, 'segment_seconds': self.segment_seconds,
                'deadline_utc': self.job['deadline_utc'],
                'indefinite': self.deadline is None,
                'remaining_seconds': (None if self.deadline is None else max(0, round(self.deadline-time.time()))),
                'folder': str(self.clips_destination), 'job_folder': str(self.destination),
                'timezone': RECORDING_TIMEZONE, 'current_time_local': recording_now().isoformat(),
                'current_day_folder': str(self.clips_destination/recording_now().date().isoformat()),
                'clip_count': len(sizes),
                'saved_bytes': sum(sizes), 'reconnects': self.reconnects,
                'disk_ok': self.disk_ok}

    def status(self):
        result = super().status()
        result['recording'] = self.recording_status()
        return result

    def checkpoint(self):
        self.prepare_day_folders()
        write_json(self.destination / 'status.json', {'updated_utc': utc_now(), **self.status()})

    def finish(self, state):
        self.stop.set()
        with self.condition: self.condition.notify_all()
        # Close the source and finalize the last partial clip before marking done.
        self.close()
        self.finished = True
        self.job['state'] = state
        self.job['finished_utc'] = utc_now()
        write_json(self.job_path, self.job)
        self.reason = state.capitalize()
        self.checkpoint()
        self.event(state, **self.recording_status())
        task_file = self.destination / 'scheduled-task.txt'
        if os.name == 'nt' and task_file.exists():
            name = task_file.read_text(encoding='utf-8-sig').strip()
            # Task names created by our launcher are safe literal arguments.
            if name.startswith('iCSee-Cloud-') and all(c.isalnum() or c == '-' for c in name):
                result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive',
                                         '-Command', f"Unregister-ScheduledTask -TaskName '{name}' -Confirm:$false"],
                                        capture_output=True, timeout=30,
                                        creationflags=subprocess.CREATE_NO_WINDOW)
                self.event('scheduled_task_removed', success=result.returncode == 0)
        if self.server: self.server.shutdown()

    def supervise(self):
        failures = 0
        outage_started = None
        last_checkpoint = 0
        self.event('process_started', deadline_utc=self.job['deadline_utc'],
                   quality=self.recording_quality, segment_seconds=self.segment_seconds)
        try:
            while not self.stop.is_set() and not self.deadline_reached():
                self.disk_ok = shutil.disk_usage(self.clips_destination).free >= 2 * 1024**3
                with self.condition:
                    current = self.session
                    healthy = (current is not None and current.media_process is not None
                               and not current.failure and current.media_process.poll() is None and self.last_frame
                               and time.time() - self.last_frame < 30)
                    if healthy and self.audio_enabled:
                        healthy = bool(current.last_audio and time.time()-current.last_audio < 30)
                    # Renew the SDK's bounded 24-hour media session proactively.
                    if healthy and time.monotonic()-current.created_at >= 23*3600:
                        healthy = False
                    if healthy and current.timezone_offset != recording_now().utcoffset():
                        healthy = False
                if not healthy or not self.disk_ok:
                    if outage_started is None:
                        outage_started = utc_now()
                        self.event('connection_gap_started', disk_ok=self.disk_ok)
                    # Retire the old connection before obtaining new authorization.
                    with self.lifecycle:
                        with self.condition:
                            current = self.session; self.session = None
                            self.jpeg = None; self.last_frame = 0
                            self.reason = ('Restoring requested resolution' if self.resolution_ok is False
                                           else 'Reconnecting') if self.disk_ok else 'Low disk space: recording paused'
                        if current: current.close()
                    if self.stop.is_set() or self.deadline_reached(): break
                    try:
                        if not self.disk_ok: raise RuntimeError('Low disk space')
                        self.ensure_emulator()
                        # Refresh login/device tokens on every new connection.
                        self.config = self.account_config()
                        if self.audio_enabled: self.config['includeAudio'] = True
                        self.activate_quality(self.recording_quality)
                        # Keep the first successful main-stream dimensions as a
                        # floor across reconnects and worker restarts. An explicit
                        # minimum is preferable when the camera's size is known.
                        if self.recording_quality == 'high' and not self.minimum_resolution:
                            with self.condition:
                                self.minimum_resolution = parse_resolution(self.resolution)
                                self.resolution_ok = True
                                self.job['minimum_resolution'] = self.resolution
                            write_json(self.job_path, self.job)
                        failures = 0
                        self.reconnects += 1
                        self.event('recording_connected', gap_started_utc=outage_started,
                                   resolution=self.resolution)
                        outage_started = None
                    except Exception as error:
                        failures += 1
                        self.reason = ('Restoring requested resolution' if self.resolution_ok is False
                                       else 'Reconnecting') if self.disk_ok else 'Low disk space: recording paused'
                        delay = min(60, 5 * 2**min(failures - 1, 4))
                        self.event('retry', error_type=type(error).__name__, retry_seconds=delay)
                        self.checkpoint()
                        self.stop.wait(self.wait_seconds(delay))
                        continue
                if time.monotonic() - last_checkpoint >= 5:
                    self.checkpoint(); last_checkpoint = time.monotonic()
                self.stop.wait(self.wait_seconds(2))
        except Exception as error:
            # Leave the job runnable so Task Scheduler can resume after a process failure.
            self.event('process_failure', error_type=type(error).__name__)
            self.close()
            if self.server: self.server.shutdown()
            return
        self.finish('completed' if self.deadline_reached() else 'stopped')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--job', type=Path, required=True)
    parser.add_argument('--create', action='store_true')
    parser.add_argument('--prepare', action='store_true', help='Create the job without starting its worker')
    parser.add_argument('--hours', type=float, default=24)
    parser.add_argument('--indefinite', action='store_true', help='Record until manually stopped')
    parser.add_argument('--segment-seconds', type=int, default=300)
    parser.add_argument('--quality', choices=['low', 'high'], default='high')
    parser.add_argument('--minimum-resolution', type=parse_resolution,
                        help='Reject smaller video and reconnect, for example 1920x1080')
    parser.add_argument('--audio', action='store_true', help='Include camera audio in the clips')
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--clips-dir', type=Path, default=ROOT/'recordings'/re.sub(r'[^a-z0-9_-]+', '-', (SETTINGS.camera_name or 'camera').lower()))
    args = parser.parse_args()
    args.job = args.job.resolve()
    if args.create:
        if args.job.exists(): raise SystemExit('Job already exists; omit --create to resume it')
        if (not args.indefinite and not 0 < args.hours <= 24) or not 5 <= args.segment_seconds <= 300:
            raise SystemExit('Choose up to 24 hours and clips between 5 and 300 seconds')
        now = time.time()
        args.job.parent.mkdir(parents=True, exist_ok=True)
        write_json(args.job, {'project': 'icsee-cloud', 'camera': SETTINGS.camera_name or 'Camera', 'created_utc': utc_now(),
                             'deadline_epoch': None if args.indefinite else now + args.hours * 3600,
                             'deadline_utc': (None if args.indefinite else datetime.fromtimestamp(now + args.hours * 3600, timezone.utc).isoformat()),
                             'quality': args.quality, 'port': args.port, 'audio': args.audio,
                             'clip_root': str(args.clips_dir.resolve()), 'recording_timezone': RECORDING_TIMEZONE,
                             'segment_seconds': args.segment_seconds, 'state': 'running',
                             'minimum_resolution': ('%dx%d' % args.minimum_resolution
                                                    if args.minimum_resolution else None)})
    if args.prepare:
        if not args.create: raise SystemExit('--prepare requires --create')
        return 0
    job = json.loads(args.job.read_text(encoding='utf8'))
    if job.get('state') != 'running': return 0
    # Lock survives in the filesystem, but Windows releases ownership on process death.
    lock = (args.job.parent / 'process.lock').open('a+b')
    if os.name == 'nt':
        import msvcrt
        try:
            lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            lock.close(); return 0
    view = None
    try:
        view = Recorder(args.job, job)
        if (args.job.parent / 'stop.request').exists() or view.deadline_reached():
            view.finish('stopped' if (args.job.parent / 'stop.request').exists() else 'completed'); return 0
        if os.name == 'nt':
            # Keep Windows awake; the monitor may turn off normally.
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
        server = serve(view)
        def monitor_stop():
            while not view.stop.wait(1):
                if (view.destination / 'stop.request').exists():
                    view.request_stop(); server.shutdown(); break
        threading.Thread(target=monitor_stop, daemon=True).start()
        supervisor = threading.Thread(target=view.supervise, daemon=True)
        supervisor.start()
        try: server.serve_forever(poll_interval=.5)
        except KeyboardInterrupt:
            view.stop.set()
            with view.condition: view.condition.notify_all()
        finally:
            view.stop.set(); supervisor.join(timeout=120)
            server.server_close(); view.close()
        return 0 if view.finished else 1
    finally:
        if os.name == 'nt': ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
        lock.close()


if __name__ == '__main__': raise SystemExit(main())
