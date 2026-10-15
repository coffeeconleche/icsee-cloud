"""Local framing and timestamped remux of the verified camera's HEVC/G.711 stream."""
import io
import re
import struct
from fractions import Fraction
import av

HEADER = struct.Struct('>4sB3xIQ')
SAMPLE_RATE = 8000
TIME_BASE = Fraction(1, SAMPLE_RATE)


class ResolutionMismatch(ValueError):
    """The received video is smaller than the recording's resolution floor."""


def parse_resolution(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,5}x[0-9]{1,5}', value):
        raise ValueError('Resolution must use WIDTHxHEIGHT, for example 1920x1080')
    dimensions = tuple(int(part) for part in value.split('x'))
    if not all(0 < part <= 65535 for part in dimensions):
        raise ValueError('Resolution dimensions must be between 1 and 65535')
    return dimensions


def video_dimensions(payload):
    with av.open(io.BytesIO(payload), format='hevc') as video:
        context = video.streams.video[0].codec_context
        if not context.width or not context.height:
            raise ValueError('Video dimensions are not available yet')
        return context.width, context.height


def read_exact(source, size):
    result = bytearray()
    while len(result) < size:
        part = source.recv(size-len(result)) if hasattr(source, 'recv') else source.read(size-len(result))
        if not part:
            if result: raise ValueError('Truncated SDK frame')
            raise EOFError()
        result.extend(part)
    return bytes(result)


def read_frame(source):
    magic, kind, size, arrival_ms = HEADER.unpack(read_exact(source, HEADER.size))
    if magic != b'ICAV' or kind not in (1, 2) or not 0 < size <= 4*1024*1024:
        raise ValueError('Invalid SDK frame envelope')
    return kind, read_exact(source, size), arrival_ms


def video_payload(raw):
    if raw.startswith(b'\x00\x00\x01\xfc') and len(raw) >= 16:
        size = struct.unpack_from('<I', raw, 12)[0]
        if size != len(raw)-16: raise ValueError('Invalid video keyframe length')
        return raw[16:], True
    if raw.startswith(b'\x00\x00\x01\xfd') and len(raw) >= 8:
        size = struct.unpack_from('<I', raw, 4)[0]
        if size != len(raw)-8: raise ValueError('Invalid video frame length')
        return raw[8:], False
    raise ValueError('Unsupported video frame header')


def audio_payload(raw):
    # Verified native NewAudioFrameHead layout and this camera's actual packets:
    # marker FA, codec 0E (G.711 A-law), rate code 02 (8 kHz), LE payload size.
    if len(raw) < 8 or raw[:6] != b'\x00\x00\x01\xfa\x0e\x02':
        raise ValueError('Unsupported camera audio format')
    size = struct.unpack_from('<H', raw, 6)[0]
    if size != len(raw)-8: raise ValueError('Invalid audio frame length')
    return raw[8:]


class AudioVideoMux:
    """Emit one timestamped NUT stream; audio samples provide the common clock.

    Verified camera delivery order is video, two 320-sample audio packets, video.
    Using its sample clock avoids cumulative drift from the rounded video FPS
    field (12) versus the observed audio/video cadence (12.5 frames/second).
    """
    def __init__(self, output, on_video_format=None):
        self.output = output
        self.on_video_format = on_video_format
        self.container = None
        self.templates = []
        self.buffer = []
        self.buffer_bytes = 0
        self.first_video = None
        self.first_audio = None
        self.audio_samples = 0
        self.last_video_pts = -1

    def ingest(self, kind, raw):
        if kind == 1:
            payload, keyframe = video_payload(raw)
            # Check every keyframe before muxing, including resolution changes
            # within an existing connection. Never resize or upscale the source.
            if keyframe and self.on_video_format:
                self.on_video_format(*video_dimensions(payload))
            if keyframe and self.first_video is None: self.first_video = payload
        else:
            payload = audio_payload(raw)
            if self.first_audio is None: self.first_audio = payload
        if self.container is None:
            self.buffer.append((kind, raw)); self.buffer_bytes += len(raw)
            if self.buffer_bytes > 8*1024*1024: raise ValueError('Audio/video initialization buffer exceeded')
            if self.first_video is None or self.first_audio is None: return
            video = av.open(io.BytesIO(self.first_video), format='hevc')
            audio = av.open(io.BytesIO(self.first_audio), format='alaw',
                            options={'sample_rate': str(SAMPLE_RATE), 'ch_layout': 'mono'})
            self.templates = [video, audio]
            self.container = av.open(self.output, mode='w', format='nut',
                                     options={'flush_packets': '1'})
            self.video = self.container.add_stream_from_template(video.streams.video[0], opaque=True)
            self.audio = self.container.add_stream_from_template(audio.streams.audio[0], opaque=True)
            self.video.time_base = self.audio.time_base = TIME_BASE
            for buffered_kind, buffered_raw in self.buffer: self.mux(buffered_kind, buffered_raw)
            self.buffer.clear(); self.buffer_bytes = 0
        else:
            self.mux(kind, raw)

    def mux(self, kind, raw):
        if kind == 1:
            payload, keyframe = video_payload(raw)
            pts = max(self.audio_samples, self.last_video_pts+1)
            packet = av.Packet(payload)
            packet.stream = self.video
            packet.is_keyframe = keyframe
            packet.pts = packet.dts = pts
            packet.duration = 640  # Observed two 320-sample audio packets per video frame.
            self.last_video_pts = pts
        else:
            payload = audio_payload(raw)
            packet = av.Packet(payload)
            packet.stream = self.audio
            packet.pts = packet.dts = self.audio_samples
            packet.duration = len(payload)
            self.audio_samples += len(payload)
        packet.time_base = TIME_BASE
        self.container.mux(packet)

    def close(self):
        if self.container: self.container.close()
        for template in self.templates: template.close()
