import io
import struct
import pytest
from icsee_cloud.media import HEADER, audio_payload, read_frame, video_payload


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
