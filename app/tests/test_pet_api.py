"""The local control surface: loopback only, token required, browser origins refused."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json, sys, tempfile, threading, unittest, urllib.error, urllib.request
from pathlib import Path
APP = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(APP))
from PySide6.QtWidgets import QApplication
from pet_api import PetApi
app = QApplication.instance() or QApplication([])


class PetApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.api = PetApi(self.temp.name)
        self.record = self.api.start()
        self.said, self.played, self.emoted = [], [], []
        self.api.say_requested.connect(lambda text, speak: self.said.append((text, speak)))
        self.api.play_requested.connect(self.played.append)
        self.api.emote_requested.connect(self.emoted.append)
        self.api.set_state(state='idle', anim='idle', mode='dsh', busy=False, connected=True, visible=True)

    def tearDown(self):
        self.api.stop()
        self.temp.cleanup()

    def call(self, path, payload=None, token=True, origin=None):
        data = None if payload is None else json.dumps(payload).encode('utf-8')
        request = urllib.request.Request(self.record['url'] + path, data=data,
                                         method='GET' if data is None else 'POST')
        if token:
            request.add_header('Authorization', 'Bearer ' + self.record['token'])
        if origin:
            request.add_header('Origin', origin)
        if data is not None:
            request.add_header('Content-Type', 'application/json')
        try:
            with urllib.request.urlopen(request, timeout=5) as reply:
                status, body = reply.status, json.loads(reply.read().decode('utf-8'))
        except urllib.error.HTTPError as error:
            status, body = error.code, json.loads(error.read().decode('utf-8') or '{}')
        app.processEvents()      # the signals are queued from the server thread onto the GUI thread
        return status, body

    def test_state_needs_the_token_and_browser_origins_are_refused(self):
        status, body = self.call('/state', token=False)
        self.assertEqual(status, 401)
        status, _ = self.call('/state', origin='https://example.com')
        self.assertEqual(status, 401)
        status, body = self.call('/state')
        self.assertEqual(status, 200)
        self.assertEqual(body['state'], 'idle')
        self.assertTrue(body['connected'])

    def test_say_play_and_emote_reach_the_pet(self):
        self.assertEqual(self.call('/say', {'text': '  该喝水啦  '})[0], 200)
        self.assertEqual(self.said, [('该喝水啦', True)])
        self.assertEqual(self.call('/say', {'text': '安静地说', 'speak': False})[0], 200)
        self.assertEqual(self.said[-1], ('安静地说', False))
        self.assertEqual(self.call('/play', {'action': 'ds_lion_dance'})[0], 200)
        self.assertEqual(self.played, ['ds_lion_dance'])
        self.assertEqual(self.call('/emote', {'text': '摸尾巴'})[0], 200)
        self.assertEqual(self.emoted, ['摸尾巴'])

    def test_bad_requests_are_rejected(self):
        self.assertEqual(self.call('/say', {'text': '   '})[0], 400)
        self.assertEqual(self.call('/say', {'text': 'x' * 401})[0], 400)
        self.assertEqual(self.call('/play', {})[0], 400)
        self.assertEqual(self.call('/nope', {})[0], 404)
        self.assertEqual(self.call('/nope', token=False)[0], 401)

    def test_discovery_file_matches_the_live_server(self):
        record = json.loads((Path(self.temp.name) / 'pet-api.json').read_text(encoding='utf-8'))
        self.assertEqual(record['url'], self.record['url'])
        self.assertEqual(record['pid'], os.getpid())
        self.assertGreaterEqual(len(record['token']), 32)
        self.api.stop()
        self.assertFalse((Path(self.temp.name) / 'pet-api.json').exists())


if __name__ == '__main__':
    unittest.main()
