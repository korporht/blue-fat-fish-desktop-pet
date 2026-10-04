"""Keep the latest 100 generated utterances locally, with asynchronous WAV writes."""
import json
import uuid
import wave
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

_WRITER = ThreadPoolExecutor(max_workers=1, thread_name_prefix='voice-archive')
ARCHIVE_LIMIT = 100
SAMPLE_RATE = 44100


class VoiceArchive:
    def __init__(self, folder):
        self.folder = Path(folder)/'tts-audio'

    def save(self, audio, metadata, reply):
        stamp = datetime.fromisoformat(metadata['at']).astimezone(timezone(timedelta(hours=8)))
        name = f'speech-{stamp:%Y%m%d-%H%M%S-%f}-{uuid.uuid4().hex[:8]}.wav'
        row = dict(metadata, reply=reply, audio_file=name, sample_rate=SAMPLE_RATE,
                   channels=1, sample_width=2, audio_stage='fish-original',
                   incomplete_sample_bytes=len(audio)%2)
        # Complete samples remain playable even when cancellation interrupts a frame.
        return name, _WRITER.submit(self._write, name, audio[:len(audio)//2*2], row)

    def _write(self, name, audio, metadata):
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder/name
        temp = path.with_suffix('.wav.tmp')
        sidecar = path.with_suffix('.json')
        meta_temp = sidecar.with_suffix('.json.tmp')
        try:
            with wave.open(str(temp), 'wb') as stream:
                stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(SAMPLE_RATE)
                stream.writeframes(audio)
            temp.replace(path)
            meta_temp.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
            meta_temp.replace(sidecar)
            # The sortable filename reflects the utterance's start time. Only delete
            # files belonging to this recorder, together with their matching metadata.
            recordings = sorted(self.folder.glob('speech-*.wav'), key=lambda item:item.name)
            for old in recordings[:-ARCHIVE_LIMIT]:
                old.unlink(missing_ok=True)
                old.with_suffix('.json').unlink(missing_ok=True)
            return path
        finally:
            temp.unlink(missing_ok=True)
            meta_temp.unlink(missing_ok=True)
