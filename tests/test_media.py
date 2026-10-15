import io
import struct
import pytest
from icsee_cloud.media import HEADER, AudioVideoMux, ResolutionMismatch, audio_payload, parse_resolution, read_frame, video_payload


def test_audio_headers_are_validated_before_mixing_into_video():
    payload = b'\xd5'*320
    frame = b'\x00\x00\x01\xfa\x0e\x02' + struct.pack('<H', 320) + payload
    assert audio_payload(frame) == payload
    with pytest.raises(ValueError): audio_payload(frame[:-1])
    with pytest.raises(ValueError): audio_payload(frame[:4] + b'\xff' + frame[5:])


def test_video_header_length_and_keyframe_type():
    payload = b'\x00\x00\x00\x01\x26\x01'
    key = b'\x00\x00\x01\xfc' + bytes(8) + struct.pack('<I', len(payload)) + payload
    assert video_payload(key) == (payload, True)
    with pytest.raises(ValueError): video_payload(key[:-1])


def test_transport_truncation_and_untrusted_lengths():
    assert read_frame(io.BytesIO(HEADER.pack(b'ICAV', 2, 2, 1000) + b'ab')) == (2, b'ab', 1000)
    with pytest.raises(ValueError): read_frame(io.BytesIO(HEADER.pack(b'ICAV', 1, 99, 1000) + b'a'))
    with pytest.raises(ValueError): read_frame(io.BytesIO(HEADER.pack(b'ICAV', 1, 5*1024*1024, 1000)))


@pytest.mark.parametrize('value', ['0x720', '1920x0', '65536x720', '1920X1080', '1920', '-1x720', None])
def test_resolution_floor_rejects_invalid_dimensions(value):
    with pytest.raises(ValueError): parse_resolution(value)


def test_resolution_floor_accepts_dimensions_without_assuming_camera_model():
    assert parse_resolution('1920x1080') == (1920, 1080)
    assert parse_resolution('3840x2160') == (3840, 2160)


def test_downgraded_keyframe_is_rejected_before_any_bytes_are_muxed(monkeypatch):
    from icsee_cloud import media
    output = io.BytesIO()
    observed = []
    monkeypatch.setattr(media, 'video_dimensions', lambda _: (320, 240))
    def check(width, height):
        observed.append((width, height))
        raise ResolutionMismatch('Below target')
    mux = AudioVideoMux(output, on_video_format=check)
    payload = b'test-keyframe'
    raw = b'\x00\x00\x01\xfc' + bytes(8) + struct.pack('<I', len(payload)) + payload
    with pytest.raises(ResolutionMismatch): mux.ingest(1, raw)
    assert observed == [(320, 240)]
    assert output.getvalue() == b'' and mux.container is None
    # The same check runs after initialization, before a mid-session downgrade
    # can reach the existing muxer.
    mux.container = object()
    monkeypatch.setattr(mux, 'mux', lambda *_: pytest.fail('Rejected video was muxed'))
    with pytest.raises(ResolutionMismatch): mux.ingest(1, raw)
