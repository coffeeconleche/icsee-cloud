"""Watch an authorized camera locally using the recovered account flow and headless vendor SDK."""
import argparse
import hashlib
import io
import json
import os
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote_plus, unquote
from PIL import Image

from .config import ROOT, Settings
from .cloud import CloudClient, ClientIdentity
SETTINGS = Settings.load()
PRIVATE = ROOT / '.research'
PKG = 'local.icsee.probe'
ADB = SETTINGS.adb
EMULATOR = SETTINGS.emulator
FFMPEG = SETTINGS.ffmpeg
RUN = ROOT / 'logs/live-view'
RUN.mkdir(parents=True, exist_ok=True)
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
QUALITIES = {'low': 1, 'high': 0}  # Verified SDKCONST.StreamType.Extra/Main.

class StreamSession:
    """Own one SDK connection and decoder so a quality switch can retire it."""
    def __init__(self, owner, quality):
        self.owner = owner
        self.quality = quality
        self.stop = threading.Event()
        self.source = None
        self.forward_port = None
        self.processes = []
        self.files = []
        self.threads = []
        self.sdk_process = None
        self.media_process = None
        self.video_bytes = 0
        self.audio_frames = 0
        self.last_audio = 0
        self.created_at = time.monotonic()

    def close(self):
        self.stop.set()
        if self.source:
            try: self.source.shutdown(socket.SHUT_RDWR)
            except OSError: pass
            self.source.close()
        # Let the feed thread close stdin and FFmpeg finalize an active clip.
        if self.media_process and self.media_process.poll() is None:
            try: self.media_process.wait(timeout=10)
            except subprocess.TimeoutExpired: pass
        # A consumer disconnect lets the helper close its native media handle.
        if self.sdk_process and self.sdk_process.poll() is None:
            try: self.sdk_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.owner.adb('shell', 'am', 'force-stop', PKG, timeout=10)
        for process in self.processes:
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=5)
        for thread in self.threads: thread.join(timeout=2)
        if self.forward_port:
            self.owner.adb('forward', '--remove', f'tcp:{self.forward_port}')
        for output in self.files: output.close()

class LiveView:
    def __init__(self, port):
        self.port = port
        self.camera_name = SETTINGS.camera_name or 'Camera'
        self.stop = threading.Event()
        self.condition = threading.Condition()
        self.jpeg = None
        self.frames = 0
        self.last_frame = 0
        self.files = []
        self.session = None
        self.lifecycle = threading.Lock()
        self.config = None
        self.helper_installed = False
        self.quality = None
        self.requested_quality = 'low'
        self.switching = False
        self.resolution = None
        self.server = None
        self.started = time.time()
        self.reason = 'Connecting'

    def adb(self, *args, data=None, timeout=90):
        return subprocess.run([str(ADB), *args], input=data, capture_output=True,
                              timeout=timeout, creationflags=NO_WINDOW)

    def ensure_emulator(self):
        result = self.adb('get-state')
        if result.returncode != 0:
            output = (RUN / 'emulator.log').open('ab')
            self.files.append(output)
            avd = SETTINGS.avd
            if not avd:
                listing = subprocess.run([str(EMULATOR), '-list-avds'], capture_output=True, text=True, creationflags=NO_WINDOW)
                names = listing.stdout.splitlines()
                if len(names) != 1: raise RuntimeError('Configure ICSEE_AVD to select an Android virtual device')
                avd = names[0]
            subprocess.Popen([str(EMULATOR), '-avd', avd, '-no-window',
                              '-no-audio', '-no-boot-anim', '-no-snapshot-save'],
                             stdout=output, stderr=output, creationflags=NO_WINDOW)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline and not self.stop.is_set():
            result = self.adb('shell', 'getprop', 'sys.boot_completed', timeout=10)
            if result.stdout.strip() == b'1': return
            self.stop.wait(2)
        raise RuntimeError('Android emulator did not finish booting; see local emulator log')

    def account_config(self):
        identity = ClientIdentity.load(SETTINGS.identity_file)
        cloud = CloudClient(identity, SETTINGS.region, country=SETTINGS.country,
                            cache_path=ROOT / 'account.local.json')
        cloud.login(SETTINGS.username, SETTINGS.password)
        camera = cloud.select_device(SETTINGS.camera_name, SETTINGS.device_id)
        self.camera_name = unquote(camera.get('nickname', '')) or 'Camera'
        return {'username': quote_plus(SETTINGS.username), 'password': SETTINGS.password,
                'serial': camera['uuid'], 'uuid': identity.uuid, 'appKey': identity.app_key,
                'appSecret': identity.app_secret, 'movedCard': identity.moved_card,
                'miServer': cloud.host, 'capsServer': cloud.caps_host,
                'channel': 0, 'stream': 1, 'timeoutSeconds': 86400,
                'mode': 'socket', 'socketPort': 23100}

    def start_sdk(self, cfg, session):
        apk = SETTINGS.helper_apk
        expected = json.loads((apk.parent / 'build-result.json').read_text())['sha256']
        if hashlib.sha256(apk.read_bytes()).hexdigest() != expected:
            raise RuntimeError('Local helper APK no longer matches its build record')
        if not self.helper_installed:
            result = self.adb('install', '-r', str(apk))
            (RUN / 'install.log').write_bytes(result.stdout + result.stderr)
            if result.returncode != 0: raise RuntimeError('Local helper install failed; see logs/live-view/install.log')
            self.helper_installed = True
        self.adb('shell', 'am', 'force-stop', PKG)
        self.adb('shell', f'run-as {PKG} mkdir -p files')
        # Previous diagnostic state must not make an unstarted socket appear ready.
        self.adb('shell', 'run-as', PKG, 'rm', '-f', 'files/status.log')
        result = self.adb('shell', f"run-as {PKG} sh -c 'cat > files/request.json'", data=json.dumps(cfg).encode())
        if result.returncode != 0: raise RuntimeError('Could not write the private SDK request')
        result = self.adb('forward', 'tcp:0', 'tcp:23100')
        if result.returncode != 0: raise RuntimeError('Could not create a loopback SDK connection')
        session.forward_port = int(result.stdout.strip())
        sdk_log = (RUN / 'sdk-process.log').open('wb')
        session.files.append(sdk_log)
        process = subprocess.Popen([str(ADB), 'shell', 'am', 'instrument', '-w', PKG + '/.ProbeInstrumentation'],
                                   stdout=sdk_log, stderr=sdk_log, creationflags=NO_WINDOW)
        session.processes.append(process)
        session.sdk_process = process
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and process.poll() is None and not self.stop.is_set():
            status = self.adb('exec-out', 'run-as', PKG, 'cat', 'files/status.log', timeout=10).stdout
            if b'socket-listening=true' not in status:
                self.stop.wait(.5)
                continue
            try:
                connection = socket.create_connection(('127.0.0.1', session.forward_port), timeout=2)
                connection.settimeout(None)
                session.source = connection
                return
            except OSError:
                self.stop.wait(.5)
        raise RuntimeError('SDK socket did not become ready; see local SDK log')

    def ffmpeg_command(self, session):
        return [str(FFMPEG), '-hide_banner', '-loglevel', 'warning',
                '-probesize', '131072', '-analyzeduration', '1000000',
                '-f', 'hevc', '-i', 'pipe:0', '-an',
                '-vf', 'fps=8', '-c:v', 'mjpeg', '-q:v', '4',
                '-f', 'image2pipe', 'pipe:1']

    def ffmpeg_environment(self):
        return None

    def feed_source(self, session, process):
        while not session.stop.is_set() and not self.stop.is_set():
            chunk = session.source.recv(65536)
            if not chunk: break
            with self.condition: session.video_bytes += len(chunk)
            process.stdin.write(chunk)
            process.stdin.flush()

    def video_pipeline(self, session):
        output = (RUN / 'ffmpeg.log').open('wb')
        session.files.append(output)
        process = subprocess.Popen(self.ffmpeg_command(session), stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=output, creationflags=NO_WINDOW,
                                   env=self.ffmpeg_environment())
        session.media_process = process
        session.processes.append(process)
        def feed():
            try:
                self.feed_source(session, process)
            except (OSError, ValueError): pass
            except Exception as error:
                with self.condition:
                    if self.session is session:
                        self.reason = 'Media input failed'
                print(f'Media input failed: {type(error).__name__}', flush=True)
            finally:
                try: process.stdin.close()
                except (OSError, ValueError): pass
        def frames():
            buffer = bytearray()
            # Drain preview output until FFmpeg exits, even during Stop. Otherwise
            # its full stdout pipe can prevent the final recording clip closing.
            while True:
                chunk = process.stdout.read1(65536)
                if not chunk: break
                if session.stop.is_set() or self.stop.is_set():
                    buffer.clear()
                    continue
                buffer.extend(chunk)
                while True:
                    begin = buffer.find(b'\xff\xd8')
                    end = buffer.find(b'\xff\xd9', begin + 2) if begin >= 0 else -1
                    if end < 0: break
                    jpeg = bytes(buffer[begin:end + 2]); del buffer[:end + 2]
                    with Image.open(io.BytesIO(jpeg)) as image:
                        width, height = image.size
                    with self.condition:
                        if self.session is not session or session.stop.is_set(): break
                        self.jpeg = jpeg; self.frames += 1; self.last_frame = time.time()
                        self.resolution = f'{width}x{height}'
                        self.quality = session.quality
                        self.reason = 'Live'; self.condition.notify_all()
                if len(buffer) > 4 * 1024 * 1024:
                    with self.condition:
                        if self.session is session: self.reason = 'Decoder output exceeded its frame buffer'
                    break
            with self.condition:
                if self.session is session and not session.stop.is_set() and not self.stop.is_set():
                    self.reason = 'Video connection ended'; self.condition.notify_all()
        session.threads = [threading.Thread(target=feed, daemon=True), threading.Thread(target=frames, daemon=True)]
        for thread in session.threads: thread.start()

    def activate_quality(self, quality):
        with self.lifecycle:
            with self.condition:
                self.switching = True
                self.requested_quality = quality
                self.reason = 'Switching quality' if self.quality else 'Connecting'
                self.jpeg = None; self.resolution = None; self.last_frame = 0
                old = self.session; self.session = None
                self.condition.notify_all()
            if old: old.close()
            if self.stop.is_set(): return
            session = StreamSession(self, quality)
            with self.condition: self.session = session
            try:
                cfg = dict(self.config, stream=QUALITIES[quality])
                self.start_sdk(cfg, session)
                self.video_pipeline(session)
                with self.condition:
                    ready = self.condition.wait_for(
                        lambda: self.stop.is_set() or self.jpeg is not None or self.reason == 'Video connection ended',
                        timeout=60)
                    if self.stop.is_set(): return
                    if not ready or self.jpeg is None:
                        raise RuntimeError('The selected camera stream did not produce video')
            except Exception:
                with self.condition:
                    self.session = None; self.quality = None; self.resolution = None
                    self.reason = 'Quality switch failed. Try another quality.'
                session.close()
                raise
            finally:
                with self.condition: self.switching = False; self.condition.notify_all()

    def request_quality(self, quality):
        with self.condition:
            if self.stop.is_set(): return 409, {'error': 'Viewer is stopping'}
            if self.switching: return 409, {'error': 'A quality switch is already in progress'}
            if self.quality == quality and self.jpeg is not None and self.reason == 'Live' and time.time() - self.last_frame < 5:
                return 200, {'quality': quality, 'switching': False}
            self.switching = True; self.requested_quality = quality
            self.reason = 'Switching quality'
        def switch():
            try: self.activate_quality(quality)
            except Exception as error:
                print(f'Quality switch failed: {type(error).__name__}', flush=True)
        threading.Thread(target=switch, daemon=True).start()
        return 202, {'quality': quality, 'switching': True}

    def status(self):
        with self.condition:
            age = round(time.time() - self.last_frame, 2) if self.last_frame else None
            reason = 'Waiting for video' if self.reason == 'Live' and age is not None and age > 5 else self.reason
            return {'camera': self.camera_name, 'status': reason, 'decoded_frames': self.frames,
                    'last_frame_age_seconds': age,
                    'seconds_running': round(time.time() - self.started), 'codec': 'HEVC',
                    'resolution': self.resolution, 'preview_fps': 8,
                    'quality': self.quality, 'requested_quality': self.requested_quality,
                    'switching': self.switching,
                    'received_video_bytes': self.session.video_bytes if self.session else 0}

    def request_stop(self):
        self.stop.set()
        with self.condition: self.condition.notify_all()

    def close(self):
        self.stop.set()
        with self.condition: self.condition.notify_all()
        with self.lifecycle:
            if self.session: self.session.close(); self.session = None
        self.config = None
        for output in self.files: output.close()

PAGE = br'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>iCSee Cloud</title>
<style>body{background:#101318;color:#f4f6fa;font:16px system-ui;margin:0;text-align:center}header{padding:16px;display:flex;justify-content:center;gap:16px;align-items:center;flex-wrap:wrap}h1{font-size:22px;margin:0}img{max-height:82vh;max-width:96vw;background:#191e26}button{background:#263242;border:1px solid transparent;border-radius:8px;padding:8px 14px;color:white;cursor:pointer}button[aria-pressed=true]{background:#1f6547;border-color:#95e6b2}button:disabled{opacity:.55;cursor:wait}#state{color:#95e6b2}#resolution{color:#abb6c6;font-size:14px}.quality{display:flex;gap:6px;align-items:center}</style>
<header><h1 id="camera">Camera</h1><span id="state">Connecting...</span><div class="quality" role="group" aria-label="Camera quality"><span>Quality</span><button id="low" aria-pressed="false" onclick="changeQuality('low')">Low</button><button id="high" aria-pressed="false" onclick="changeQuality('high')">High</button></div><span id="resolution"></span><span id="recording"></span><button id="stop" onclick="stopVideo()">Stop</button></header><img id="video" src="/stream.mjpeg" alt="Camera live stream">
<script>
let stopped=false;
async function refresh(){
 if(stopped)return;
 try{
  const s=await(await fetch('/status',{cache:'no-store'})).json();
  document.getElementById('camera').textContent=s.camera;
  document.getElementById('state').textContent=s.switching?'Switching quality...':s.status;
  document.getElementById('resolution').textContent=s.resolution?s.resolution.replace('x',' \u00d7 '):'';
  for(const q of ['low','high']){const b=document.getElementById(q);b.disabled=s.switching||!!s.recording;b.setAttribute('aria-pressed',s.quality===q&&!s.switching?'true':'false')}
  if(s.recording){
   const r=s.recording;
   const recordingTime=d=>new Date(d).toLocaleString(undefined,{timeZone:r.timezone||'UTC',hour12:false});
   const end=r.indefinite?'Until manually stopped':'Ends '+recordingTime(r.deadline_utc)+' ('+(r.timezone||'UTC')+')';
   const clock=r.current_time_local?' | '+(r.timezone||'UTC')+': '+recordingTime(r.current_time_local):'';
   document.getElementById('recording').textContent='Recording '+(r.audio_enabled?'with audio':'video only')+': '+r.clip_count+' clips, '+(r.saved_bytes/1e6).toFixed(1)+' MB | '+end+clock;
   document.getElementById('stop').textContent='Stop recording';
  }
 }catch(e){document.getElementById('state').textContent='Connection unavailable'}
}
async function changeQuality(quality){for(const q of ['low','high'])document.getElementById(q).disabled=true;document.getElementById('state').textContent='Switching quality...';try{const r=await fetch('/quality',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({quality})});if(!r.ok){const e=await r.json();document.getElementById('state').textContent=e.error}}catch(e){document.getElementById('state').textContent='Could not change quality'}await refresh()}
async function stopVideo(){await fetch('/stop',{method:'POST'});stopped=true;document.getElementById('state').textContent='Stopped';document.getElementById('video').src='';for(const q of ['low','high'])document.getElementById(q).disabled=true}
refresh();setInterval(refresh,1500);
</script></html>'''

def serve(view):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            if self.path == '/':
                self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8'); self.end_headers(); self.wfile.write(PAGE)
            elif self.path == '/status':
                self.send_response(200); self.send_header('Content-Type', 'application/json'); self.send_header('Cache-Control', 'no-store'); self.end_headers(); self.wfile.write(json.dumps(view.status()).encode())
            elif self.path == '/stream.mjpeg':
                self.send_response(200); self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame'); self.send_header('Cache-Control', 'no-store'); self.end_headers()
                seen = -1
                try:
                    while not view.stop.is_set():
                        with view.condition:
                            view.condition.wait_for(lambda: view.stop.is_set() or (view.jpeg and view.frames != seen), timeout=5)
                            if view.stop.is_set(): break
                            if not view.jpeg or seen == view.frames: continue
                            image, seen = view.jpeg, view.frames
                        self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ' + str(len(image)).encode() + b'\r\n\r\n' + image + b'\r\n'); self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError): pass
            else: self.send_error(404)
        def do_POST(self):
            if self.path == '/quality':
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 1024: raise ValueError()
                    data = json.loads(self.rfile.read(length))
                    quality = data.get('quality') if isinstance(data, dict) else None
                    if not isinstance(quality, str) or quality not in QUALITIES: raise ValueError()
                except (ValueError, TypeError):
                    code, result = 400, {'error': 'Choose low or high quality'}
                else: code, result = view.request_quality(quality)
                self.send_response(code); self.send_header('Content-Type', 'application/json'); self.end_headers()
                self.wfile.write(json.dumps(result).encode()); return
            if self.path != '/stop': self.send_error(404); return
            view.request_stop()
            self.send_response(200); self.end_headers(); self.wfile.write(b'Stopping')
            threading.Thread(target=view.server.shutdown, daemon=True).start()
    server = ThreadingHTTPServer(('127.0.0.1', view.port), Handler)
    view.server = server
    return server

def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    view = LiveView(args.port)
    server = serve(view)
    try:
        print('Connecting to the selected camera. Credentials and SDK output stay in local private files.', flush=True)
        view.ensure_emulator()
        view.config = view.account_config()
        view.activate_quality('low')
        print(f'Viewer: http://127.0.0.1:{args.port}/ (Stop button or Ctrl+C ends the connection)', flush=True)
        server.serve_forever(poll_interval=.5)
    except KeyboardInterrupt: pass
    except Exception as error:
        print(f'Live viewer stopped: {type(error).__name__}: {error}', flush=True)
        return 1
    finally:
        server.server_close(); view.close()
    return 0

if __name__ == '__main__': raise SystemExit(main())
