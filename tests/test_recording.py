import json
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from icsee_cloud.recorder import Recorder, write_json
from icsee_cloud.viewer import StreamSession


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
