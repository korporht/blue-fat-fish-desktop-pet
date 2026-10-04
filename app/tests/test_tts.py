"""Exercise actual Qt WebSockets, increment deduplication, cancellation and PCM buffering."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
from types import SimpleNamespace
import sys,json,tempfile,time,unittest,re,wave,threading
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
APP=Path(__file__).resolve().parents[1];sys.path.insert(0,str(APP))
import msgpack
from PySide6.QtWidgets import QApplication,QMenu
from PySide6.QtCore import QObject,Signal
from PySide6.QtNetwork import QHostAddress
from PySide6.QtWebSockets import QWebSocketServer
from PySide6.QtTest import QTest
from PySide6.QtMultimedia import QMediaDevices
import companion_tts as tts
from voice_archive import VoiceArchive
app=QApplication.instance() or QApplication([])

class Player(QObject):
    problem=Signal(str)
    def __init__(self):super().__init__();self.audio=[];self.finished=0;self.stops=0
    def feed(self,audio):self.audio.append(audio)
    def finish(self):self.finished+=1
    def stop(self):self.stops+=1

class SpeechTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.path=Path(self.folder.name)/'fish-tts.json'
        self.path.write_text(json.dumps({'api_key':'local-test-key','reference_id':'private-voice','enabled':True}))
        self.server=QWebSocketServer('test',QWebSocketServer.NonSecureMode)
        self.assertTrue(self.server.listen(QHostAddress.LocalHost,0))
        self.messages=[];self.peers=[]
        def connect():
            peer=self.server.nextPendingConnection();self.peers.append(peer)
            peer.binaryMessageReceived.connect(lambda data:self.messages.append(msgpack.unpackb(bytes(data),raw=False)))
        self.server.newConnection.connect(connect)
        self.endpoint=patch.object(tts,'ENDPOINT',f'ws://127.0.0.1:{self.server.serverPort()}/v1/tts/live')
        self.endpoint.start()
        self.player=Player();self.voice=tts.FishSpeech(self.folder.name,player=self.player)
    def tearDown(self):
        self.voice.stop();self.voice.deleteLater()
        if self.voice.archive_write is not None:self.voice.archive_write.result(timeout=5)
        for peer in self.peers:peer.abort();peer.deleteLater()
        self.server.close();self.server.deleteLater();app.processEvents()
        self.endpoint.stop();self.folder.cleanup()
    def until(self,condition):
        deadline=time.monotonic()+3
        while not condition() and time.monotonic()<deadline:QTest.qWait(10)
        self.assertTrue(condition())
    def test_text_arrives_before_final_reply_and_final_never_repeats_speech(self):
        self.voice.begin('one');self.voice.update('one','主人，')
        self.until(lambda:len(self.messages)>=2)
        self.assertEqual(self.messages[0]['event'],'start')
        request=self.messages[0]['request']
        self.assertEqual(request['prosody']['speed'],.98)
        self.assertEqual(request['temperature'],.85)
        self.assertEqual(request['top_p'],.9)
        self.assertEqual(request['repetition_penalty'],1.3)
        self.assertEqual((request['chunk_length'],request['min_chunk_length']),(200,50))
        self.assertEqual((request['format'],request['sample_rate'],request['reference_id']),('pcm',44100,'private-voice'))
        self.assertIn('[soft tone',self.messages[1]['text'])
        self.assertTrue(self.messages[1]['text'].endswith('主人，'))
        self.voice.update('one','主人，');self.voice.update('one','主人，我在呢。')
        self.voice.finish('one','主人，我在呢。');self.voice.finish('one','主人，我在呢。')
        self.until(lambda:any(row['event']=='stop' for row in self.messages))
        spoken=''.join(row['text'] for row in self.messages if row['event']=='text')
        self.assertEqual(re.sub(r'\[[^\]]*\]','',spoken),'主人，我在呢。')
        self.assertEqual([row['event'] for row in self.messages].count('stop'),1)
        peer=self.peers[-1]
        peer.sendBinaryMessage(msgpack.packb({'event':'audio','audio':b'\x01\x02\x03'},use_bin_type=True))
        peer.sendBinaryMessage(msgpack.packb({'event':'audio','audio':b'\x04'},use_bin_type=True))
        self.until(lambda:len(self.player.audio)==2)
        self.assertEqual(self.player.finished,0)  # Audio was delivered before finish, not collected first.
        peer.sendBinaryMessage(msgpack.packb({'event':'finish','reason':'stop'},use_bin_type=True))
        self.until(lambda:self.player.finished==1)
        self.assertEqual(b''.join(self.player.audio),b'\x01\x02\x03\x04')
        path=self.voice.archive_write.result(timeout=5)
        with wave.open(str(path)) as stream:
            self.assertEqual((stream.getframerate(),stream.getnchannels(),stream.getsampwidth()),(44100,1,2))
            self.assertEqual(stream.readframes(stream.getnframes()),b'\x01\x02\x03\x04')
        metadata=json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
        self.assertEqual(metadata['reply'],'主人，我在呢。')
        self.assertEqual(metadata['outcome'],'generated')
        self.assertNotIn('api_key',metadata);self.assertNotIn('reference_id',metadata)
    def test_active_includes_audio_drain_after_transport_finishes(self):
        self.voice.begin('one');self.until(lambda:self.voice.started)
        self.assertTrue(self.voice.is_active)
        self.player.sink=object()
        self.voice.receive(self.voice.socket,msgpack.packb({'event':'finish','reason':'stop'},use_bin_type=True))
        self.assertIsNone(self.voice.socket)
        self.assertTrue(self.voice.is_active)
        self.player.sink=None
        self.assertFalse(self.voice.is_active)
    def test_cancelled_turn_and_late_socket_callbacks_cannot_speak_in_next_turn(self):
        self.voice.begin('old');self.until(lambda:self.voice.started)
        old=self.voice.socket;self.voice.begin('new');self.voice.update('old','过期回复。')
        self.voice.receive(old,msgpack.packb({'event':'audio','audio':b'old'},use_bin_type=True))
        self.voice.disconnected(old)
        self.assertEqual(self.player.audio,[]);self.assertEqual(self.voice.turn,'new')
        self.voice.update('new','新回复。');self.until(lambda:self.voice.sent=='新回复。')
    def test_rewritten_reply_stops_without_replaying_or_splicing_stale_words(self):
        self.voice.begin('one');self.until(lambda:self.voice.started)
        errors=[];self.voice.problem.connect(errors.append)
        self.voice.update('one','我在');self.voice.update('one','主人，我在')
        self.assertEqual(self.voice.turn,'');self.assertEqual(len(errors),1)
    def test_missing_clone_and_disabled_voice_do_not_open_default_or_paid_voice(self):
        with patch.object(self.voice,'socket_factory') as factory:
            self.path.write_text(json.dumps({'api_key':'local-test-key','enabled':True,'model':'s2.1-pro'}))
            self.assertFalse(self.voice.begin('one'));factory.assert_not_called()
            self.path.write_text(json.dumps({'api_key':'local-test-key','reference_id':'voice','enabled':False}))
            self.assertFalse(self.voice.begin('two'));factory.assert_not_called()
        self.voice.set_enabled(True)
        self.assertEqual(json.loads(self.path.read_text())['model'],'s2.1-pro-free')
    def test_server_failure_stops_audio_and_does_not_retry(self):
        self.voice.begin('one');self.until(lambda:self.voice.started)
        errors=[];self.voice.problem.connect(errors.append)
        self.voice.receive(self.voice.socket,msgpack.packb({'event':'finish','reason':'error'},use_bin_type=True))
        self.assertEqual(self.voice.turn,'');self.assertEqual(len(errors),1)
        self.assertIsNone(self.voice.socket)

    def test_preset_menu_is_exclusive_and_switch_preserves_voice_credentials(self):
        menu=QMenu();self.voice.add_menu(menu,lambda:None)
        voice_menu=menu.actions()[0].menu()
        presets=next(action.menu() for action in voice_menu.actions() if action.text()=='性格与语音预设')
        maid,brat=presets.actions()
        self.assertTrue(maid.isChecked());self.assertFalse(brat.isChecked())
        brat.trigger()
        config=json.loads(self.path.read_text())
        self.assertEqual(config['preset'],'brat')
        self.assertEqual(config['reference_id'],'private-voice')
        self.assertEqual(config['api_key'],'local-test-key')
        self.assertTrue(brat.isChecked());self.assertFalse(maid.isChecked())
        maid.trigger()
        self.assertEqual(self.voice.selected_preset(),'maid')
        menu.deleteLater()

    def test_brat_uses_same_reference_free_model_and_snapshot_parameters(self):
        self.voice.set_preset('brat')
        self.voice.begin('brat-turn');self.voice.update('brat-turn','杂鱼主人，就这？～')
        self.until(lambda:len(self.messages)>=2)
        request=self.messages[0]['request']
        self.assertEqual(request['reference_id'],'private-voice')
        self.assertEqual((request['temperature'],request['top_p'],request['prosody']['speed']),(.9,.9,1.0))
        self.assertIn('[smug',self.messages[1]['text'])
        self.voice.set_preset('maid')
        self.assertIsNone(self.voice.socket)
        self.assertFalse(self.voice.is_active)
        self.voice.begin('maid-turn')
        self.until(lambda:sum(row['event']=='start' for row in self.messages)==2)
        request=next(row['request'] for row in reversed(self.messages) if row['event']=='start')
        self.assertEqual((request['temperature'],request['prosody']['speed']),(.85,.98))

    def test_short_interjections_stream_but_are_not_forced_into_separate_audio(self):
        self.voice.set_preset('brat');self.voice.begin('one')
        self.until(lambda:self.voice.started)
        self.voice.update('one','诶？')
        self.until(lambda:any(row['event']=='text' for row in self.messages))
        self.assertNotIn('flush',[row['event'] for row in self.messages])
        self.voice.update('one','诶？主人你突然认真起来，我没跟上。')
        self.until(lambda:any(row['event']=='flush' for row in self.messages))
        self.voice.finish('one','诶？主人你突然认真起来，我没跟上。')
        self.until(lambda:any(row['event']=='stop' for row in self.messages))
        self.assertEqual(sum(row['event']=='flush' for row in self.messages),1)
        request=self.messages[0]['request']
        self.assertEqual(request['features'],['quality-guard'])
        spoken=''.join(row['text'] for row in self.messages if row['event']=='text')
        self.assertEqual(re.sub(r'\[[^\]]*\]','',spoken),'诶？主人你突然认真起来，我没跟上。')

    def test_generation_diagnostics_are_bounded_private_and_do_not_duplicate_on_stop(self):
        path=Path(self.folder.name)/'tts-events.jsonl'
        path.write_text('\n'.join(json.dumps({'old':i}) for i in range(105))+'\n',encoding='utf-8')
        self.voice.begin('one');self.until(lambda:self.voice.started)
        self.voice.finish('one','主人，我在呢。')
        socket=self.voice.socket
        self.voice.receive(socket,msgpack.packb({'event':'audio','audio':bytes(8820)},use_bin_type=True))
        self.voice.receive(socket,msgpack.packb({'event':'finish','reason':'stop'},use_bin_type=True))
        self.voice.stop()
        rows=[json.loads(row) for row in path.read_text(encoding='utf-8').splitlines()]
        self.assertEqual(len(rows),100)
        last=rows[-1]
        self.assertEqual((last['outcome'],last['audio_seconds'],last['text_chars']),('generated',.1,5))
        self.assertNotIn('text',last);self.assertNotIn('reference_id',last);self.assertNotIn('api_key',last)
        self.assertNotIn('主人',json.dumps(last,ensure_ascii=False))

    def test_cancelled_or_failed_audio_is_saved_once_and_never_mixed_into_new_turn(self):
        self.voice.begin('one');self.until(lambda:self.voice.started)
        self.voice.update('one','第一句。')
        self.voice.receive(self.voice.socket,msgpack.packb({'event':'audio','audio':b'\x01\x02\x03'},use_bin_type=True))
        self.voice.stop();first=self.voice.archive_write.result(timeout=5)
        with wave.open(str(first)) as stream:self.assertEqual(stream.readframes(10),b'\x01\x02')
        metadata=json.loads(first.with_suffix('.json').read_text(encoding='utf-8'))
        self.assertEqual((metadata['outcome'],metadata['incomplete_sample_bytes']),('cancelled',1))
        self.voice.begin('two');self.until(lambda:self.voice.started)
        self.voice.receive(self.voice.socket,msgpack.packb({'event':'audio','audio':b'\x04\x05'},use_bin_type=True))
        self.voice.fail('test failure');second=self.voice.archive_write.result(timeout=5)
        self.voice.stop()
        with wave.open(str(second)) as stream:self.assertEqual(stream.readframes(10),b'\x04\x05')
        self.assertEqual(json.loads(second.with_suffix('.json').read_text())['outcome'],'error')
        self.assertEqual(len(list(first.parent.glob('*.wav'))),2)

    def test_voice_can_finish_while_archive_disk_writer_is_busy(self):
        entered=threading.Event();release=threading.Event()
        original=self.voice.archive._write
        def slow(*args):
            entered.set();release.wait(3);return original(*args)
        with patch.object(self.voice.archive,'_write',side_effect=slow):
            try:
                self.voice.begin('one');self.until(lambda:self.voice.started)
                self.voice.receive(self.voice.socket,msgpack.packb({'event':'audio','audio':bytes(8820)},use_bin_type=True))
                self.voice.receive(self.voice.socket,msgpack.packb({'event':'finish','reason':'stop'},use_bin_type=True))
                self.assertTrue(entered.wait(1))
                self.assertEqual(self.player.finished,1)
                self.assertIsNone(self.voice.socket)
                self.assertFalse(self.voice.archive_write.done())
            finally:release.set()
            self.assertTrue(self.voice.archive_write.result(timeout=5).exists())

    def test_runaway_audio_is_stopped_archived_and_late_packets_cannot_resume_it(self):
        self.voice.begin('one');self.until(lambda:self.voice.started)
        text='主人今天情绪像坐过山车。'*5
        self.voice.finish('one',text);socket=self.voice.socket
        errors=[];self.voice.problem.connect(errors.append)
        for _ in range(60):
            self.voice.receive(socket,msgpack.packb({'event':'audio','audio':bytes(88200)},use_bin_type=True))
            if errors:break
        self.assertEqual(len(errors),1)
        self.assertIsNone(self.voice.socket)
        self.assertLess(len(self.player.audio),60)
        before=len(self.player.audio)
        self.voice.receive(socket,msgpack.packb({'event':'audio','audio':b'late'},use_bin_type=True))
        self.assertEqual(len(self.player.audio),before)
        path=self.voice.archive_write.result(timeout=5)
        metadata=json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
        self.assertEqual(metadata['stop_reason'],'duration_limit')
        self.assertEqual(metadata['outcome'],'error')
        self.assertEqual(metadata['reply'],text)
        self.assertGreater(metadata['audio_seconds'],metadata['duration_limit_seconds'])
        self.assertIn('speech_text',metadata)

    def test_normal_long_reply_can_play_longer_than_short_reply_ceiling(self):
        self.voice.begin('one');self.until(lambda:self.voice.started)
        self.voice.finish('one','主人我在这里陪着你。'*15)
        socket=self.voice.socket;errors=[];self.voice.problem.connect(errors.append)
        for _ in range(30):
            self.voice.receive(socket,msgpack.packb({'event':'audio','audio':bytes(88200)},use_bin_type=True))
        self.assertEqual(errors,[])
        self.assertEqual(len(self.player.audio),30)
        self.voice.receive(socket,msgpack.packb({'event':'finish','reason':'stop'},use_bin_type=True))
        self.assertEqual(self.player.finished,1)

class ArchiveTests(unittest.TestCase):
    def test_latest_100_actual_recordings_survive_restart_and_prune_matching_sidecars(self):
        with tempfile.TemporaryDirectory() as folder:
            archive=VoiceArchive(folder)
            archive.folder.mkdir()
            unrelated=archive.folder/'keep-me.wav';unrelated.write_bytes(b'user file')
            stamp=datetime(2026,10,2,14,0,tzinfo=timezone.utc)
            paths=[]
            for index in range(103):
                name,future=archive.save(bytes([index,0])*3,
                    {'at':(stamp+timedelta(seconds=index)).isoformat(),'outcome':'generated'},f'回复 {index}')
                paths.append(future.result(timeout=5))
                if index==50:archive=VoiceArchive(folder)
            kept=sorted(archive.folder.glob('speech-*.wav'))
            self.assertEqual(len(kept),100)
            self.assertEqual(len(list(archive.folder.glob('speech-*.json'))),100)
            self.assertFalse(paths[0].exists());self.assertFalse(paths[2].exists())
            self.assertTrue(paths[3].exists());self.assertTrue(paths[-1].exists())
            self.assertTrue(kept[0].name.startswith('speech-20261002-220003'))
            with wave.open(str(paths[-1])) as stream:self.assertEqual(stream.readframes(10),bytes([102,0])*3)
            self.assertEqual(unrelated.read_bytes(),b'user file')

class PcmTests(unittest.TestCase):
    def test_large_server_chunk_is_processed_in_bounded_callbacks_before_finishing(self):
        player=tts.PcmPlayer();received=[];finished=[]
        player.effects=SimpleNamespace(feed=lambda data:(received.append(data) or b''),
            finish=lambda:(finished.append(True) or b''),reset=lambda:None)
        data=bytes(24000)
        player.feed(data)
        self.assertTrue(player.is_active)
        self.assertTrue(player.incoming)
        self.assertEqual(finished,[])
        player.finish()
        self.assertEqual(finished,[])
        self.assertTrue(player.is_active)
        player.pump()
        self.assertEqual(b''.join(received),data)
        self.assertLessEqual(max(map(len,received)),8192)
        self.assertEqual(finished,[True])
        self.assertFalse(player.is_active)
        player.stop();player.deleteLater()

    def test_fragmented_frames_partial_writes_and_backpressure_preserve_audio_bytes(self):
        player=tts.PcmPlayer(effects=False);written=bytearray();free=[0];state=[tts.QtAudio.State.ActiveState]
        class Output:
            def write(self,data):
                data=data[:2];written.extend(data);return len(data)
        player.sink=SimpleNamespace(error=lambda:tts.QtAudio.Error.NoError,bytesFree=lambda:free[0],state=lambda:state[0],reset=lambda:None,deleteLater=lambda:None)
        player.output=Output()
        player.feed(b'\x01');player.feed(b'\x02\x03');player.feed(b'\x04\x05\x06')
        self.assertEqual(written,b'');self.assertEqual(bytes(player.pending),b'\x01\x02\x03\x04\x05\x06')
        free[0]=4
        player.pump();player.pump();player.pump();player.finish()
        self.assertEqual(written,b'\x01\x02\x03\x04\x05\x06')
        self.assertIsNotNone(player.sink)  # Drain the hardware buffer before stopping.
        state[0]=tts.QtAudio.State.IdleState;player.pump();self.assertIsNone(player.sink)
        player.deleteLater()

    def test_native_audio_errors_and_idle_state_use_the_current_qt_namespace(self):
        if QMediaDevices.defaultAudioOutput().isNull():self.skipTest('No audio output device')
        player=tts.PcmPlayer();errors=[];player.problem.connect(errors.append)
        player.feed(bytes(8820));player.finish()
        deadline=time.monotonic()+2
        while player.sink is not None and time.monotonic()<deadline:QTest.qWait(10)
        self.assertEqual(errors,[]);self.assertIsNone(player.sink)
        player.stop();player.deleteLater()

if __name__=='__main__':unittest.main()
