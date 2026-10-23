import asyncio
import sys
import pyaudio
from config import (
    AUDIO_INPUT_SAMPLE_RATE,
    AUDIO_OUTPUT_SAMPLE_RATE,
    AUDIO_CHANNELS,
    AUDIO_CHUNK_SIZE,
)


class AudioManager:
    """
    Handles real-time microphone input and speaker output using PyAudio.
    - Input: 16kHz, 16-bit PCM Mono
    - Output: 24kHz, 16-bit PCM Mono
    """

    def __init__(self):
        self.p = pyaudio.PyAudio()
        self.input_stream = None
        self.output_stream = None
        self.is_running = False
        self.output_queue = asyncio.Queue()

    def start_streams(self):
        # Open Microphone Input Stream (16kHz)
        try:
            self.input_stream = self.p.open(
                format=pyaudio.paInt16,
                channels=AUDIO_CHANNELS,
                rate=AUDIO_INPUT_SAMPLE_RATE,
                input=True,
                frames_per_buffer=AUDIO_CHUNK_SIZE,
            )
        except Exception as e:
            print(f"[오디오 오류] 마이크를 초기화할 수 없습니다: {e}", file=sys.stderr)
            raise

        # Open Speaker Output Stream (24kHz)
        try:
            self.output_stream = self.p.open(
                format=pyaudio.paInt16,
                channels=AUDIO_CHANNELS,
                rate=AUDIO_OUTPUT_SAMPLE_RATE,
                output=True,
                frames_per_buffer=AUDIO_CHUNK_SIZE,
            )
        except Exception as e:
            print(f"[오디오 오류] 스피커를 초기화할 수 없습니다: {e}", file=sys.stderr)
            raise

        self.is_running = True
        print("🎤 [오디오] 마이크(16kHz) 및 스피커(24kHz) 스트림 준비 완료!")

    async def read_microphone_chunk(self) -> bytes:
        """Reads a chunk of raw PCM bytes from the microphone without blocking asyncio."""
        if not self.input_stream or not self.is_running:
            return b""
        try:
            data = await asyncio.to_thread(
                self.input_stream.read,
                AUDIO_CHUNK_SIZE,
                exception_on_overflow=False,
            )
            return data
        except Exception:
            return b""

    async def play_audio_loop(self):
        """Asynchronous worker that continuously plays audio chunks from output_queue."""
        while self.is_running:
            try:
                chunk = await self.output_queue.get()
                if chunk is None:
                    break
                if self.output_stream and self.is_running:
                    await asyncio.to_thread(self.output_stream.write, chunk)
                self.output_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[재생 오류] {e}", file=sys.stderr)

    def queue_audio_for_playback(self, audio_data: bytes):
        """Pushes incoming raw PCM bytes from Gemini to the playback queue."""
        if self.is_running:
            self.output_queue.put_nowait(audio_data)

    def clear_playback_queue(self):
        """Clears pending playback (useful when user interrupts AI)."""
        while not self.output_queue.empty():
            try:
                self.output_queue.get_nowait()
                self.output_queue.task_done()
            except Exception:
                break

    def close(self):
        self.is_running = False
        self.clear_playback_queue()

        if self.input_stream:
            try:
                self.input_stream.stop_stream()
                self.input_stream.close()
            except Exception:
                pass

        if self.output_stream:
            try:
                self.output_stream.stop_stream()
                self.output_stream.close()
            except Exception:
                pass

        self.p.terminate()
        print("🛑 [오디오] 오디오 스트림이 안전하게 종료되었습니다.")
