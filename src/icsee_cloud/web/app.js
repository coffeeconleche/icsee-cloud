'use strict';

const $ = id => document.getElementById(id);
const state = {snapshot: null, available: false, stopped: false, refreshing: false,
  qualityPending: false, imageFailed: false, pollTimer: null, receivedAt: Date.now(), serverTime: Date.now()};
const number = value => new Intl.NumberFormat('en-US').format(value || 0);
let toastTimer;

function text(id, value) { $(id).textContent = value; }
function pill(id, value, kind = '') { text(id, value); $(id).className = `pill ${kind}`; }
function dot(id, kind) { $(id).className = `status-dot ${kind}`; }
function toast(message) {
  clearTimeout(toastTimer);
  $('toast').querySelector('span').textContent = message;
  $('toast').hidden = false;
  toastTimer = setTimeout(() => { $('toast').hidden = true; }, 4500);
}
function formatSize(bytes) {
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = Math.max(0, Number(bytes) || 0), index = 0;
  while (value >= 1000 && index < units.length - 1) { value /= 1000; index++; }
  return {value: value.toLocaleString('en-US', {maximumFractionDigits: index ? 1 : 0}), unit: units[index]};
}
function timezone() { return state.snapshot?.recording?.timezone || 'UTC'; }
function clockDate() { return new Date(state.serverTime + Date.now() - state.receivedAt); }
function formatDate(date, options) {
  try { return new Intl.DateTimeFormat('en-GB', {timeZone: timezone(), ...options}).format(date); }
  catch { return new Intl.DateTimeFormat('en-GB', {timeZone: 'UTC', ...options}).format(date); }
}
function updateClocks() {
  const date = clockDate();
  text('workspace-date', formatDate(date, {weekday: 'short', day: 'numeric', month: 'short', year: 'numeric'}));
  $('workspace-time').replaceChildren(document.createTextNode(formatDate(date, {hour: '2-digit', minute: '2-digit', hourCycle: 'h23'})));
  const label = document.createElement('small');
  label.textContent = timezone();
  $('workspace-time').append(label);
  text('video-clock', formatDate(date, {day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23'}));
  const r = state.snapshot?.recording;
  if (r && !$('clip-progress').hidden) {
    const length = Number(r.segment_seconds) || 300;
    const elapsed = Math.floor(date.getTime() / 1000) % length;
    const remaining = length - elapsed;
    $('clip-bar').max = length;
    $('clip-bar').value = elapsed;
    text('next-clip', `≈ ${Math.floor(remaining / 60)}:${String(remaining % 60).padStart(2, '0')}`);
  }
}
function render() {
  const s = state.snapshot || {};
  const r = s.recording;
  const usable = state.available && !state.stopped;
  const live = usable && s.status === 'Live' && typeof s.last_frame_age_seconds === 'number' && s.last_frame_age_seconds < 5;
  const saving = live && r?.active && r.disk_ok !== false;
  const phase = state.stopped ? 'Stopped' : !state.available ? 'Unavailable' : s.switching ? 'Switching quality' : live ? 'Connected' : s.status || 'Connecting';
  const shortPhase = state.stopped ? 'Stopped' : !state.available ? 'Connecting' : live ? 'Online' : 'Connecting';
  const camera = s.camera || 'Camera';
  document.querySelectorAll('[data-camera-name]').forEach(element => { element.textContent = camera; });
  document.title = `${state.stopped ? 'Stopped' : 'Live view'} · iCSee Cloud`;
  text('sidebar-state', shortPhase);
  dot('sidebar-dot', live ? 'online' : state.stopped ? '' : 'waiting');
  text('summary-connection', shortPhase);
  pill('summary-state-pill', live ? 'LIVE' : state.stopped ? 'ENDED' : 'WAITING', live ? 'good' : '');
  text('summary-connection-note', state.stopped ? 'Your connection has ended' : live ? 'Your camera is connected' : phase);
  const quality = s.quality === 'high' ? 'High' : s.quality === 'low' ? 'Low' : '—';
  const resolution = s.resolution ? String(s.resolution).replace(/x/i, ' × ') : '—';
  text('summary-quality', quality);
  text('summary-resolution', resolution);
  text('summary-quality-note', r ? 'Original video, saved without re-encoding' : 'Original camera stream');
  text('camera-subtitle', r ? 'Camera stream · recording session' : 'Camera stream · live view');
  text('video-quality', quality === '—' ? 'CONNECTING' : `${quality.toUpperCase()} · ${s.resolution || s.codec || 'Video'}`);
  $('live-indicator').className = `live-indicator ${live ? 'online' : ''}`;
  $('live-indicator').querySelector('span').textContent = live ? 'Live stream' : shortPhase;
  $('video-live-badge').hidden = !live;
  $('video-recording').hidden = !saving;
  $('video-placeholder').hidden = !!(live && !state.imageFailed && $('video').naturalWidth);
  $('video-placeholder').classList.toggle('error-message', state.stopped);
  text('placeholder-title', state.stopped ? 'Your session has ended' : !state.available ? 'Waiting for your connection' : s.switching ? 'Switching the camera stream' : live ? 'Loading your live preview' : 'Bringing your camera into view');
  text('placeholder-note', state.stopped ? 'Your saved recordings are kept on this computer.' : !state.available ? 'We will check again automatically. The recorder may still be running.' : 'The preview will appear as soon as video arrives.');
  $('snapshot-button').disabled = !live || !$('video').naturalWidth || state.imageFailed;
  for (const q of ['low', 'high']) {
    const button = $(`quality-${q}`);
    button.disabled = !usable || !!r || !!s.switching || state.qualityPending;
    button.setAttribute('aria-pressed', s.quality === q ? 'true' : 'false');
  }
  text('quality-hint', r ? 'Quality is fixed while this recording runs.' : s.switching ? 'The new stream is connecting…' : 'Choose the stream that works for you.');

  $('stop-button').disabled = !usable;
  $('stop-button').querySelector('span').textContent = state.stopped ? 'Stopped' : r ? 'Stop recording' : 'Stop live view';
  $('clip-progress').hidden = !saving;
  $('copy-path').disabled = !r?.folder;
  if (r) {
    const size = formatSize(r.saved_bytes);
    text('saved-value', size.value);
    text('saved-unit', size.unit);
    text('saved-note', `${number(r.clip_count)} clips · across all recording days`);
    const active = usable && r.active;
    pill('recording-state', state.stopped ? 'STOP REQUESTED' : !state.available ? 'UNKNOWN' : !r.active ? 'INACTIVE' : r.disk_ok === false ? 'PAUSED' : saving ? 'RECORDING' : 'RECONNECTING', saving ? 'good' : active ? 'warning' : '');
    text('recording-mode', state.stopped ? 'Ending this session' : r.indefinite ? 'Continuous capture' : 'Scheduled capture');
    text('recording-description', state.stopped ? 'The last clip will be finalized.' : r.disk_ok === false ? 'Paused until more disk space is available.' : r.indefinite ? 'Saving until you choose to stop.' : r.deadline_utc ? `Until ${formatDate(new Date(r.deadline_utc), {day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23'})}` : 'A fixed-duration recording.');
    const seconds = Number(r.segment_seconds) || 300;
    text('clip-length', seconds % 60 === 0 ? `${seconds / 60} minutes` : `${seconds} seconds`);
    text('audio-status', r.audio_enabled ? `Included · ${r.audio_codec || 'Audio'}` : 'Video only');
    text('folder-grouping', 'By day');
    text('recording-reassurance', state.stopped ? 'Saved clips stay on this computer.' : 'Closing this tab does not stop recording.');
    text('recording-folder', r.current_day_folder || r.folder || '—');
    text('archive-note', `Daily folders and filenames follow ${timezone()} time.`);
    text('recovery-state', active ? 'Enabled' : state.stopped ? 'Stopped' : 'Inactive');
    $('recovery-state').className = active ? 'positive' : '';
    text('details-reconnects', number(r.reconnects));
  } else {
    text('saved-value', '—'); text('saved-unit', ''); text('saved-note', 'Live view only · no recording job');
    pill('recording-state', 'VIEW ONLY');
    text('recording-mode', 'Just the live view');
    text('recording-description', 'This session is not saving clips.');
    text('clip-length', 'Not recording'); text('audio-status', 'Not recording'); text('folder-grouping', '—');
    text('recording-reassurance', 'Stop ends this camera connection.');
    text('recording-folder', 'No active recording folder');
    text('archive-note', 'Start a recording with your local recording launcher to save clips here.');
    text('recovery-state', 'Not recording'); text('details-reconnects', '—');
  }
  text('connection-state', phase);
  $('connection-state').className = live ? 'positive' : '';
  text('frame-age', usable && typeof s.last_frame_age_seconds === 'number' ? s.last_frame_age_seconds < 1 ? 'Just now' : `${s.last_frame_age_seconds.toFixed(1)}s ago` : '—');
  dot('connection-dot', live ? 'online' : 'waiting');
  text('connection-note', state.stopped ? 'Stop request acknowledged' : !state.available ? 'Checking the local connection again' : r?.disk_ok === false ? 'Recording paused · low disk space' : live ? 'Receiving your camera stream' : 'Waiting for fresh video');
  text('details-camera', camera);
  text('details-codec', `${s.codec || '—'}${s.resolution ? ` · ${s.resolution}` : ''}`);
  text('details-preview', s.preview_fps ? `${s.preview_fps} fps · silent` : 'Silent browser preview');
  text('details-timezone', timezone());
  text('timezone-note', `Times shown in ${timezone()}`);
  if ($('connection-announcement').textContent !== phase) text('connection-announcement', phase);
  updateClocks();
}

async function refresh() {
  if (state.stopped || state.refreshing) return;
  clearTimeout(state.pollTimer);
  state.refreshing = true;
  try {
    const response = await fetch('/status', {cache: 'no-store', signal: AbortSignal.timeout(6000)});
    if (!response.ok) throw new Error('Status unavailable');
    state.snapshot = await response.json();
    state.available = true;
    state.receivedAt = Date.now();
    state.serverTime = Date.parse(state.snapshot.recording?.current_time_local || '') || state.receivedAt;
    if (state.imageFailed && state.snapshot.status === 'Live') {
      state.imageFailed = false;
      $('video').src = `/stream.mjpeg?refresh=${Date.now()}`;
    }
  } catch { state.available = false; }
  finally {
    state.refreshing = false;
    render();
    if (!state.stopped) state.pollTimer = setTimeout(refresh, 1500);
  }
}

async function changeQuality(quality) {
  state.qualityPending = true; render();
  try {
    const response = await fetch('/quality', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({quality}), signal: AbortSignal.timeout(10000)});
    if (!response.ok) { const data = await response.json(); throw new Error(data.error || 'Quality could not be changed.'); }
  } catch (error) { toast(error.message || 'Could not change video quality.'); }
  finally { state.qualityPending = false; await refresh(); }
}
async function copyPath() {
  const path = state.snapshot?.recording?.current_day_folder || state.snapshot?.recording?.folder;
  if (!path) return;
  try {
    if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(path);
    else {
      const field = document.createElement('textarea'); field.className = 'sr-only'; field.value = path;
      document.body.append(field); field.select();
      const copied = document.execCommand('copy'); field.remove(); $('copy-path').focus();
      if (!copied) throw new Error('Clipboard unavailable');
    }
    toast('Recording folder path copied.');
  } catch { toast('Could not access the clipboard. The folder path is shown below the live view.'); }
}
async function snapshot() {
  const image = $('video');
  if (!image.naturalWidth) return;
  try {
    const canvas = document.createElement('canvas');
    canvas.width = image.naturalWidth; canvas.height = image.naturalHeight;
    canvas.getContext('2d').drawImage(image, 0, 0);
    const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
    if (!blob) throw new Error('Snapshot unavailable');
    const url = URL.createObjectURL(blob), link = document.createElement('a');
    link.href = url; link.download = `camera-${new Date().toISOString().replace(/[:.]/g, '-')}.png`;
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast('Snapshot saved to your browser downloads.');
  } catch { toast('Could not save this frame. Wait for fresh video and try again.'); }
}
function setNavigation(open) {
  $('sidebar').classList.toggle('open', open);
  $('nav-backdrop').hidden = !open;
  $('menu-toggle').setAttribute('aria-expanded', String(open));
  const mobile = window.matchMedia('(max-width: 720px)').matches;
  $('sidebar').inert = mobile && !open;
  $('sidebar').setAttribute('aria-hidden', String(mobile && !open));
  document.body.classList.toggle('navigation-open', mobile && open);
  if (mobile && !open && $('sidebar').contains(document.activeElement)) $('menu-toggle').focus({preventScroll: true});
}
function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  try { localStorage.setItem('icsee-cloud-theme', theme); } catch { /* Storage is optional. */ }
  $('theme-icon').setAttribute('href', `/static/icons.svg#${theme === 'dark' ? 'sun' : 'moon'}`);
  $('theme-toggle').setAttribute('aria-label', `Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`);
}
function openStopDialog() {
  const recording = !!state.snapshot?.recording;
  text('stop-dialog-title', recording ? 'Stop recording?' : 'Stop the live view?');
  text('stop-dialog-description', recording ? 'The current clip will be finalized and your saved clips will be kept. Recording will stay stopped until you start a new recording.' : 'This ends the camera connection. You can start another live view with your local launcher.');
  text('cancel-stop', recording ? 'Keep recording' : 'Keep watching');
  text('confirm-stop', recording ? 'Stop recording' : 'Stop live view');
  $('stop-dialog').showModal(); $('cancel-stop').focus();
}
async function stopSession() {
  $('confirm-stop').disabled = true;
  try {
    const response = await fetch('/stop', {method: 'POST', signal: AbortSignal.timeout(15000)});
    if (!response.ok) throw new Error('Stop was not acknowledged');
    state.stopped = true; clearTimeout(state.pollTimer);
    $('video').removeAttribute('src'); $('stop-dialog').close(); render();
    toast('Stop requested. Existing recordings are kept.');
  } catch { toast('Could not stop the session. Try again, or use the local stop launcher.'); }
  finally { $('confirm-stop').disabled = false; }
}

$('quality-low').addEventListener('click', () => changeQuality('low'));
$('quality-high').addEventListener('click', () => changeQuality('high'));
$('copy-path').addEventListener('click', copyPath);
$('snapshot-button').addEventListener('click', snapshot);
$('stop-button').addEventListener('click', openStopDialog);
$('cancel-stop').addEventListener('click', () => $('stop-dialog').close());
$('confirm-stop').addEventListener('click', stopSession);
$('audio-info').addEventListener('click', () => toast(state.snapshot?.recording?.audio_enabled ? 'The preview is silent. Your saved clips include camera audio.' : 'The browser preview is silent. Audio is not being recorded in this session.'));
$('details-button').addEventListener('click', () => $('details-dialog').showModal());
$('close-details').addEventListener('click', () => $('details-dialog').close());
$('theme-toggle').addEventListener('click', () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));
$('menu-toggle').addEventListener('click', () => setNavigation(!$('sidebar').classList.contains('open')));
$('nav-backdrop').addEventListener('click', () => setNavigation(false));
document.addEventListener('keydown', event => { if (event.key === 'Escape') setNavigation(false); });
window.addEventListener('resize', () => setNavigation(window.innerWidth <= 720 && $('sidebar').classList.contains('open')));
document.querySelector('.brand').addEventListener('click', () => setNavigation(false));
document.querySelectorAll('.nav-link').forEach(link => link.addEventListener('click', () => {
  document.querySelectorAll('.nav-link').forEach(item => { item.classList.remove('active'); item.removeAttribute('aria-current'); });
  link.classList.add('active'); link.setAttribute('aria-current', 'location'); setNavigation(false);
}));
$('fullscreen-button').addEventListener('click', async () => {
  try { if (document.fullscreenElement) await document.exitFullscreen(); else await $('video-stage').requestFullscreen(); }
  catch { toast('Fullscreen is unavailable in this browser window.'); }
});
document.addEventListener('fullscreenchange', () => $('fullscreen-button').setAttribute('aria-label', document.fullscreenElement ? 'Exit fullscreen' : 'Expand live view'));
$('exit-fullscreen').addEventListener('click', async () => {
  try { if (document.fullscreenElement) await document.exitFullscreen(); }
  catch { toast('Use Escape or your browser fullscreen control to exit.'); }
});
$('video').addEventListener('load', () => { state.imageFailed = false; render(); });
$('video').addEventListener('error', () => { state.imageFailed = true; render(); });
let theme = 'light';
try { if (localStorage.getItem('icsee-cloud-theme') === 'dark') theme = 'dark'; } catch { /* Storage is optional. */ }
setTheme(theme); setNavigation(false); render(); refresh(); setInterval(updateClocks, 1000);
