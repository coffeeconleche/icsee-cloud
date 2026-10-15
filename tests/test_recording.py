import json
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from icsee_cloud.recorder import Recorder, write_json
from icsee_cloud.viewer import StreamSession
from icsee_cloud.media import ResolutionMismatch


def test_indefinite_stop_is_durable_and_does_not_reset_a_deadline(tmp_path):
    job = {'project':'icsee-cloud', 'camera':'Test camera', 'port':8766, 'quality':'high',
           'audio':False, 'deadline_epoch':None, 'deadline_utc':None,
           'clip_root':str(tmp_path/'clips'), 'segment_seconds':300, 'state':'running'}
    path = tmp_path/'job.json'; write_json(path, job)
    view = Recorder(path, job)
    assert not view.deadline_reached() and view.wait_seconds(60)==60
    assert view.status()['recording']['remaining_seconds'] is None
    view.request_stop()
    assert (tmp_path/'stop.request').exists()
    view.finish('stopped')
    assert json.loads(path.read_text())['state']=='stopped'


@pytest.mark.parametrize('zone, ffmpeg_tz', [
    ('UTC', 'LOC-00:00'), ('Etc/GMT+5', 'LOC+05:00'), ('Asia/Kolkata', 'LOC-05:30')])
def test_configured_date_rollover_and_worker_environment(tmp_path, monkeypatch, zone, ffmpeg_tz):
    from icsee_cloud import recorder
    recording_zone = ZoneInfo(zone)
    monkeypatch.setattr(recorder, 'RECORDING_TIMEZONE', zone)
    monkeypatch.setattr(recorder, 'recording_now', lambda: datetime(2026, 10, 13, 23, 59, 59, tzinfo=recording_zone))
    job = {'camera':'Test', 'port':8766, 'quality':'high', 'audio':False,
           'deadline_epoch':None, 'deadline_utc':None, 'segment_seconds':300,
           'clip_root':str(tmp_path/'clips'), 'state':'running'}
    view = Recorder(tmp_path/'job.json', job)
    command = view.ffmpeg_command(StreamSession(view, 'high'))
    assert (tmp_path/'clips/2026-10-13').is_dir() and (tmp_path/'clips/2026-10-14').is_dir()
    assert view.ffmpeg_environment()['TZ']==ffmpeg_tz
    assert '-strftime' in command and '-segment_atclocktime' in command
    status = view.recording_status()
    assert status['timezone'] == zone
    assert datetime.fromisoformat(status['current_time_local']).utcoffset() == recording_zone.utcoffset(datetime(2026, 10, 13))


def test_actual_dimensions_and_resolution_floor_survive_worker_restart(tmp_path):
    job = {'camera':'Test', 'port':8766, 'quality':'high', 'audio':True,
           'deadline_epoch':None, 'deadline_utc':None, 'segment_seconds':300,
           'clip_root':str(tmp_path/'clips'), 'state':'running', 'minimum_resolution':'1920x1080'}
    path = tmp_path/'job.json'
    write_json(path, job)
    view = Recorder(path, json.loads(path.read_text()))
    session = StreamSession(view, 'high')
    view.session = session
    with pytest.raises(ResolutionMismatch): view.observe_video_format(session, 640, 360)
    status = view.status()
    assert status['resolution'] == '640x360'
    assert status['minimum_resolution'] == '1920x1080'
    assert status['resolution_ok'] is False
    assert status['requested_quality'] == 'high'
    assert status['status'] == 'Restoring requested resolution'
    # A buffered preview from before the downgrade must not clear the rejection.
    view.observe_video_format(session, 1920, 1080)
    assert view.status()['resolution_ok'] is False
    assert view.status()['resolution'] == '640x360'
    # A new connection must be checked again and can deliver a larger size.
    replacement = StreamSession(view, 'high')
    view.session = replacement
    view.observe_video_format(replacement, 2560, 1440)
    assert view.status()['resolution_ok'] is True
    assert view.status()['resolution'] == '2560x1440'
    # Late frames from the retired session cannot overwrite current dimensions.
    view.observe_video_format(session, 320, 240)
    assert view.status()['resolution'] == '2560x1440'


def test_each_dimension_must_meet_the_resolution_floor(tmp_path):
    from icsee_cloud.viewer import LiveView
    view = LiveView(0)
    view.minimum_resolution = (1920, 1080)
    session = StreamSession(view, 'high'); view.session = session
    with pytest.raises(ResolutionMismatch): view.observe_video_format(session, 3840, 720)
    assert view.status()['resolution_ok'] is False


def test_video_only_rejects_low_resolution_before_ffmpeg_receives_video(monkeypatch):
    import io
    from types import SimpleNamespace
    from icsee_cloud import viewer
    view = viewer.LiveView(0); view.minimum_resolution = (1920, 1080)
    session = StreamSession(view, 'high'); view.session = session
    chunks = iter([b'partial-keyframe', b'rest-of-keyframe', b''])
    session.source = SimpleNamespace(recv=lambda _: next(chunks))
    process = SimpleNamespace(stdin=io.BytesIO())
    probes = iter([None, (640, 360)])
    def dimensions(_):
        result = next(probes)
        if result is None: raise ValueError('Incomplete headers')
        return result
    monkeypatch.setattr(viewer, 'video_dimensions', dimensions)
    with pytest.raises(ResolutionMismatch): view.feed_source(session, process)
    assert process.stdin.getvalue() == b''
    assert view.status()['resolution'] == '640x360'
