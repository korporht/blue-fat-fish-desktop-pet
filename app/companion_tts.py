"""Fish Audio bidirectional TTS and nonblocking PCM playback; credentials stay local."""
import json
import uuid
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from voice_delivery import PRESETS, preset_name, SpeechText, reply_style
from runtime_environment import prepare_runtime
prepare_runtime()
from voice_audio import VoiceAudio
from voice_archive import VoiceArchive

import msgpack
from PySide6.QtCore import QObject, Signal, QTimer, QUrl
from PySide6.QtGui import QActionGroup, QDesktopServices
from PySide6.QtNetwork import QNetworkRequest
from PySide6.QtWebSockets import QWebSocket
from PySide6.QtMultimedia import QAudioSink, QAudioFormat, QMediaDevices
try:
    from PySide6.QtMultimedia import QtAudio
except ImportError:  # Qt < 6.7 used the QAudio namespace for these enums.
    from PySide6.QtMultimedia import QAudio as QtAudio

MODEL = 's2.1-pro-free'
ENDPOINT = 'wss://api.fish.audio/v1/tts/live'
SAMPLE_RATE = 44100
MAX_AUDIO_BYTES = SAMPLE_RATE * 2 * 120


class VoiceConfig:
    def __init__(self, folder):
        self.path = Path(folder) / 'fish-tts.json'
        self.reload()

    def reload(self):
        self.data = {}
        try:
            data = json.loads(self.path.read_text(encoding='utf-8-sig'))
            if isinstance(data, dict): self.data = data
        except (OSError, ValueError):
            pass
        self.enabled = self.data.get('enabled', True) is True
        self.preset = preset_name(self.data.get('preset'))
        self.key = str(self.data.get('api_key', '')).strip()
        self.reference = str(self.data.get('reference_id', '')).strip()
        self.volume = self.data.get('volume', .8)
        if type(self.volume) not in (int, float) or not 0 <= self.volume <= 1: self.volume = .8

    @property
    def ready(self):
        return bool(self.key and self.reference)

    def set_enabled(self, enabled):
        self.update(enabled=bool(enabled))

    def update(self, **values):
        self.reload()
        self.data.update(values, model=MODEL)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(self.path)
        self.reload()


class PcmPlayer(QObject):
    """Push PCM to Qt's audio ring buffer as it arrives, including across underruns."""
    problem = Signal(str)

    def __init__(self, parent=None, effects=True):
        super().__init__(parent)
        self.sink = self.output = None
        self.pending = bytearray()
        self.incoming = bytearray()
        self.input_ended = self.effects_finished = False
        self.ended = False
        self.volume = .8
        self.effects = VoiceAudio() if effects else None
        self.timer = QTimer(self, timeout=self.pump)
        self.timer.setInterval(15)

    def feed(self, audio):
        if not audio: return
        if self.effects is None:
            self.enqueue(audio)
        else:
            if len(self.incoming) + len(self.pending) + len(audio) > MAX_AUDIO_BYTES:
                self.stop(); self.problem.emit('语音缓冲过长，已停止朗读。'); return
            self.incoming.extend(audio)
        self.timer.start(); self.pump()

    def enqueue(self, audio):
        if len(self.pending) + len(audio) > MAX_AUDIO_BYTES:
            self.stop(); self.problem.emit('语音缓冲过长，已停止朗读。'); return
        self.pending.extend(audio)
        if self.sink is None:
            fmt = QAudioFormat(); fmt.setSampleRate(SAMPLE_RATE)
            fmt.setChannelCount(1); fmt.setSampleFormat(QAudioFormat.Int16)
            device = QMediaDevices.defaultAudioOutput()
            if device.isNull() or not device.isFormatSupported(fmt):
                self.stop(); self.problem.emit('当前音频设备不能播放语音，请检查系统输出设备。'); return
            self.sink = QAudioSink(device, fmt, self)
            self.sink.setBufferSize(SAMPLE_RATE * 2 // 5)
            self.sink.setVolume(self.volume)
            self.output = self.sink.start()
            if self.output is None:
                self.stop(); self.problem.emit('语音播放设备启动失败。'); return

    @property
    def is_active(self):
        return self.sink is not None or bool(self.incoming) or (self.input_ended and not self.effects_finished)

    def process_audio(self):
        if self.effects is None: return
        if self.incoming:
            # Bound each GUI callback, even if the server delivers several seconds at once.
            raw = bytes(self.incoming[:8192]); del self.incoming[:8192]
            audio = self.effects.feed(raw)
            if audio: self.enqueue(audio)
        if self.input_ended and not self.incoming and not self.effects_finished:
            self.effects_finished = True
            try:
                tail = self.effects.finish()
            except ValueError:
                self.stop(); self.problem.emit('语音数据不完整，已停止朗读。'); return
            if tail: self.enqueue(tail)
            self.ended = True

    def pump(self):
        self.process_audio()
        if self.ended and self.sink is None:
            self.stop(); return
        if self.sink is None or self.output is None: return
        if self.sink.error() not in (QtAudio.Error.NoError, QtAudio.Error.UnderrunError):
            self.stop(); self.problem.emit('音频设备暂不可用，文字回复仍正常显示。'); return
        size = min(len(self.pending), self.sink.bytesFree()) // 2 * 2
        if size:
            written = self.output.write(bytes(self.pending[:size]))
            if written < 0:
                self.stop(); self.problem.emit('语音播放中断，文字回复仍正常显示。'); return
            del self.pending[:written]
        if self.ended and not self.pending and self.sink.state() == QtAudio.State.IdleState:
            self.stop()

    def finish(self):
        if self.effects is not None:
            self.input_ended = True
            self.timer.start(); self.pump(); return
        if len(self.pending) % 2:
            self.stop(); self.problem.emit('语音数据不完整，已停止朗读。'); return
        self.ended = True
        self.pump()

    def stop(self):
        self.timer.stop()
        sink, self.sink = self.sink, None
        self.output = None; self.pending.clear(); self.ended = False
        self.incoming.clear(); self.input_ended = self.effects_finished = False
        if self.effects is not None: self.effects.reset()
        if sink is not None:
            sink.reset(); sink.deleteLater()


class FishSpeech(QObject):
    problem = Signal(str)
    audio_received = Signal(int)

    def __init__(self, folder, parent=None, socket_factory=QWebSocket, player=None):
        super().__init__(parent)
        self.config = VoiceConfig(folder)
        self.socket_factory = socket_factory
        self.player = player or PcmPlayer(self)
        self.owns_player = player is None
        self.player.problem.connect(self.fail)
        self.socket = None
        self.turn = ''; self.text = ''; self.sent = ''
        self.input_done = self.started = self.received_finish = False
        self.status = ''
        self.delivery = SpeechText()
        self.unflushed_chars = 0
        self.metrics = None
        self.capture = bytearray()
        self.spoken_text = ''
        self.archive = VoiceArchive(folder)
        self.archive_write = None
        self.preset = PRESETS[self.config.preset]
        self.deadline = QTimer(self, singleShot=True, timeout=lambda: self.fail('语音服务连接超时，文字回复仍正常显示。'))

    @property
    def is_active(self):
        # The transport can finish before the audio device has drained its buffer.
        return (self.socket is not None or getattr(self.player, 'is_active', False)
                or getattr(self.player, 'sink', None) is not None)

    def begin(self, turn, emotion='none'):
        self.stop(); self.config.reload()
        if not self.config.enabled or not self.config.ready: return False
        self.preset = PRESETS[self.config.preset]
        self.delivery = SpeechText(emotion, self.config.preset)
        if self.owns_player:
            self.player.effects = VoiceAudio(formant_semitones=self.preset.formant, presence_db=self.preset.presence_db)
        self.turn = turn; self.player.volume = self.config.volume
        self.metrics = {'at':datetime.now(timezone.utc).isoformat(), 'preset':self.config.preset,
            'model':MODEL, 'text_chars':0, 'pcm_bytes':0, 'first_audio_seconds':None,
            'flush_count':0, 'cue_count':0, 'temperature':self.preset.temperature,
            'top_p':self.preset.top_p, 'speed':self.preset.speed,
            'repetition_penalty':1.3, 'chunk_length':200, 'min_chunk_length':50,
            '_started':time.monotonic()}
        socket = self.socket_factory()
        socket.setParent(self)
        self.socket = socket
        socket.setMaxAllowedIncomingMessageSize(2 * 1024 * 1024)
        socket.connected.connect(lambda: self.connected(socket))
        socket.binaryMessageReceived.connect(lambda data: self.receive(socket, bytes(data)))
        socket.disconnected.connect(lambda: self.disconnected(socket))
        socket.errorOccurred.connect(lambda _: self.socket_error(socket))
        request = QNetworkRequest(QUrl(ENDPOINT))
        request.setRawHeader(b'Authorization', ('Bearer ' + self.config.key).encode('utf-8'))
        request.setRawHeader(b'model', MODEL.encode('ascii'))
        self.deadline.start(10000)
        socket.open(request)
        return True

    def send(self, event):
        if self.socket is not None:
            self.socket.sendBinaryMessage(msgpack.packb(event, use_bin_type=True))

    def connected(self, socket):
        if socket is not self.socket: return
        self.started = True; self.status = '正在朗读'
        self.deadline.start(90000)
        self.send({'event':'start', 'request':{'text':'', 'reference_id':self.config.reference,
            'format':'pcm', 'sample_rate':SAMPLE_RATE, 'latency':'balanced',
            'chunk_length':200, 'min_chunk_length':50, 'normalize':True,
            'condition_on_previous_chunks':True, 'temperature':self.preset.temperature, 'top_p':self.preset.top_p,
            'features':['quality-guard'],
            'repetition_penalty':1.3,
            'prosody':{'speed':self.preset.speed, 'volume':0}}})
        self.flush_text()

    def update(self, turn, text):
        if turn != self.turn or not self.turn or self.input_done: return
        text = str(text)[:400]
        if not text.startswith(self.text):
            self.fail('回复内容已修订，停止当前朗读。'); return
        self.text = text
        if self.started: self.flush_text()

    def flush_text(self):
        delta = self.text[len(self.sent):]
        spoken = self.delivery.feed(delta, final=self.input_done)
        self.sent = self.text
        if spoken:
            self.spoken_text += spoken
            plain = re.sub(r'\[[^\]]*\]', '', spoken)
            count = sum(char.isalnum() for char in plain)
            self.unflushed_chars += count
            if self.metrics is not None:
                self.metrics['text_chars'] += count
                self.metrics['cue_count'] += spoken.count('[')
            self.send({'event':'text','text':spoken})
            # Never force synthesis of an isolated interjection such as "诶？".
            # Text still streams immediately; stop drains even very short replies.
            if not self.input_done and self.unflushed_chars >= 8 and spoken.endswith(('。','！','？','!','?','\n')):
                self.send({'event':'flush'})
                self.unflushed_chars = 0
                if self.metrics is not None: self.metrics['flush_count'] += 1
        if self.input_done:
            self.send({'event':'stop'})

    def finish(self, turn, text):
        if turn != self.turn or not self.turn or self.input_done: return
        self.update(turn, text)
        if turn != self.turn: return
        self.input_done = True
        if self.started: self.flush_text()

    def speak(self, text):
        if not str(text).strip(): return
        turn = str(uuid.uuid4())
        self.config.reload()
        fallback = 'smug' if self.config.preset == 'brat' else 'soft'
        if self.begin(turn, reply_style(str(text), fallback, self.config.preset)): self.finish(turn, text)

    def receive(self, socket, data):
        if socket is not self.socket: return
        try:
            value = msgpack.unpackb(data, raw=False, max_bin_len=2*1024*1024, max_str_len=4096)
            if not isinstance(value, dict): raise ValueError('Invalid event')
            event = value.get('event')
            if event == 'audio':
                audio = value.get('audio')
                if not isinstance(audio, bytes): raise ValueError('Invalid audio')
                self.capture.extend(audio)
                if self.metrics is not None:
                    self.metrics['pcm_bytes'] += len(audio)
                    if audio and self.metrics['first_audio_seconds'] is None:
                        self.metrics['first_audio_seconds'] = round(time.monotonic()-self.metrics['_started'], 3)
                    # A generous speech-length ceiling stops runaway synthesis and
                    # clears already queued audio, rather than letting it howl on.
                    limit = max(12, 5 + self.metrics['text_chars']*.4/self.preset.speed)
                    if self.metrics['pcm_bytes']/(SAMPLE_RATE*2) > limit:
                        self.metrics['stop_reason'] = 'duration_limit'
                        self.metrics['duration_limit_seconds'] = round(limit,3)
                        self.fail('语音生成时长异常，已停止朗读，文字回复仍正常显示。')
                        return
                self.deadline.start(90000)
                self.player.feed(audio); self.audio_received.emit(len(audio))
            elif event == 'finish':
                if value.get('reason') != 'stop':
                    self.fail('语音生成失败，文字回复仍正常显示。'); return
                self.received_finish = True; self.input_done = True
                self.record('generated')
                self.deadline.stop(); self.player.finish(); self.status = ''
                # Some servers leave the transport open after the terminal frame.
                # Close it here while the already received PCM continues draining.
                self.socket = None; self.turn = ''
                socket.close(); socket.deleteLater()
        except (ValueError, TypeError, msgpack.UnpackException):
            self.fail('语音数据格式异常，文字回复仍正常显示。')

    def socket_error(self, socket):
        if socket is self.socket:
            self.fail('语音服务暂不可用，请检查 Fish Audio 密钥、音色和网络。')

    def disconnected(self, socket):
        if socket is not self.socket: return
        if not self.received_finish:
            self.fail('语音连接提前断开，文字回复仍正常显示。'); return
        self.socket = None; socket.deleteLater()
        self.turn = ''

    def fail(self, message):
        self.record('error')
        self.stop(); self.status = message; self.problem.emit(message)

    def record(self, outcome):
        """Archive the received voice, including partial audio on errors/cancellation."""
        row, self.metrics = self.metrics, None
        audio, self.capture = self.capture, bytearray()
        if row is None: return
        row['elapsed_seconds'] = round(time.monotonic()-row.pop('_started'), 3)
        row['audio_seconds'] = round(row.pop('pcm_bytes')/(SAMPLE_RATE*2), 3)
        row['outcome'] = outcome
        if len(audio) >= 2:
            name, self.archive_write = self.archive.save(bytes(audio),
                dict(row, speech_text=self.spoken_text), self.text)
            row['audio_file'] = 'tts-audio/'+name
        path = self.config.path.parent/'tts-events.jsonl'
        try:
            rows = path.read_text(encoding='utf-8').splitlines()[-99:] if path.exists() else []
            rows.append(json.dumps(row, ensure_ascii=False))
            temp = path.with_suffix('.tmp')
            temp.write_text('\n'.join(rows)+'\n', encoding='utf-8')
            temp.replace(path)
        except (OSError, UnicodeError):
            pass  # Diagnostics must never interrupt the reply or audio playback.

    def stop(self):
        self.record('cancelled')
        self.turn = ''; self.text = self.sent = ''
        self.spoken_text = ''
        self.unflushed_chars = 0
        self.input_done = self.started = self.received_finish = False
        self.deadline.stop(); self.player.stop()
        socket, self.socket = self.socket, None
        if socket is not None:
            socket.abort(); socket.deleteLater()

    def set_enabled(self, enabled):
        self.stop(); self.config.set_enabled(enabled)

    def set_preset(self, name):
        if name not in PRESETS: return
        self.stop(); self.config.update(preset=name)

    def selected_preset(self):
        self.config.reload()
        return self.config.preset

    def open_archive(self):
        try:
            self.archive.folder.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.archive.folder.resolve())))
        except OSError:
            self.problem.emit('暂时无法打开语音记录目录。')

    def description(self):
        self.config.reload()
        if not self.config.key: return '尚未配置 Fish Audio 密钥'
        if not self.config.reference: return '等待参考音频复刻并绑定音色'
        return self.status or ('S2.1 Pro Free · ' + PRESETS[self.config.preset].label if self.config.enabled else '语音已关闭')

    def add_menu(self, menu, replay, preset_changed=None):
        voice = menu.addMenu('语音')
        toggle = voice.addAction('朗读她的回复'); toggle.setCheckable(True)
        self.config.reload(); toggle.setChecked(self.config.enabled)
        toggle.triggered.connect(self.set_enabled)
        presets = voice.addMenu('性格与语音预设')
        group = QActionGroup(presets); group.setExclusive(True)
        for name, preset in PRESETS.items():
            action = presets.addAction(preset.label); action.setCheckable(True)
            action.setChecked(self.config.preset == name); group.addAction(action)
            action.triggered.connect(lambda checked, selected=name: (preset_changed or self.set_preset)(selected) if checked else None)
        voice.addAction(self.description()).setEnabled(False)
        voice.addAction('停止朗读').triggered.connect(self.stop)
        voice.addAction('打开语音记录').triggered.connect(self.open_archive)
        again = voice.addAction('重听她的上一句'); again.setEnabled(self.config.ready and self.config.enabled)
        again.triggered.connect(replay)
