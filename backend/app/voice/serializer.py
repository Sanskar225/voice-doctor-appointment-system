"""Custom Pipecat FrameSerializer for raw 16kHz 16-bit mono PCM over FastAPI WebSockets."""

from __future__ import annotations

from pipecat.frames.frames import (
    AudioRawFrame,
    Frame,
    InputAudioRawFrame,
    InterruptionFrame,
)
from pipecat.serializers.base_serializer import FrameSerializer


class RawPCMFrameSerializer(FrameSerializer):
    """Bidirectional raw 16-bit signed little-endian PCM serializer with stream resampling."""

    def __init__(self, sample_rate: int = 16000, num_channels: int = 1) -> None:
        super().__init__(
            params=FrameSerializer.InputParams(
                audio_in_sample_rate=sample_rate,
                audio_out_sample_rate=sample_rate,
            )
        )
        self._wire_sample_rate = sample_rate
        self._num_channels = num_channels

    async def serialize(self, frame: Frame) -> str | bytes | None:
        if isinstance(frame, InterruptionFrame):
            await self._reset_audio_out()
            return None
        if isinstance(frame, AudioRawFrame):
            return await self._resample_audio_out(frame)
        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        if isinstance(data, (bytes, bytearray)) and len(data) > 0:
            pcm = await self._resample_audio_in(bytes(data))
            return InputAudioRawFrame(
                audio=pcm,
                sample_rate=self._sample_rate or self._wire_sample_rate,
                num_channels=self._num_channels,
            )
        return None
