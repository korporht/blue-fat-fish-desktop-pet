"""A small local control surface so other tools can make her talk, move or react.

Loopback only, bearer token, written next to the bridge credentials as
`pet-api.json` so a caller can discover the port the same way the pet does.
"""
import hmac
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from secrets import token_hex

from PySide6.QtCore import QObject, Signal

MAX_BODY = 16 * 1024


class PetApi(QObject):
    """Signals marshal every request onto the GUI thread; the server itself only parses."""

    say_requested = Signal(str, bool)
    play_requested = Signal(str)
    emote_requested = Signal(str)

    def __init__(self, data_dir):
        super().__init__()
        self.path = Path(data_dir) / 'pet-api.json'
        self.state = {'ok': True, 'state': 'unknown'}   # refreshed on the GUI thread only
        self.token = token_hex(32)
        self.server = None
        self.thread = None

    def set_state(self, **fields):
        self.state = {'ok': True, **fields}

    # ---- lifecycle -------------------------------------------------
    def start(self):
        api = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *args):        # keep the console quiet
                pass

            def _deny(self, code, message):
                body = json.dumps({'error': message}, ensure_ascii=False).encode('utf-8')
                self.send_response(code)
                self.send_header('content-type', 'application/json; charset=utf-8')
                self.send_header('content-length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _authorized(self):
                if self.headers.get('Origin'):    # a browser page must never drive her
                    return False
                presented = (self.headers.get('Authorization') or '').removeprefix('Bearer ').strip()
                return hmac.compare_digest(presented, api.token)

            def _body(self):
                try:
                    length = int(self.headers.get('content-length') or 0)
                except ValueError:
                    return None
                if length <= 0 or length > MAX_BODY:
                    return None
                try:
                    value = json.loads(self.rfile.read(length).decode('utf-8'))
                except (ValueError, UnicodeDecodeError):
                    return None
                return value if isinstance(value, dict) else None

            def do_GET(self):
                if not self._authorized():
                    self._deny(401, 'unauthorized'); return
                if self.path.split('?')[0] != '/state':
                    self._deny(404, 'not found'); return
                body = json.dumps(api.state, ensure_ascii=False).encode('utf-8')
                self.send_response(200)
                self.send_header('content-type', 'application/json; charset=utf-8')
                self.send_header('cache-control', 'no-store')
                self.send_header('content-length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                route = self.path.split('?')[0]
                if not self._authorized():
                    self._deny(401, 'unauthorized'); return
                body = self._body()
                if body is None:
                    self._deny(400, 'bad json'); return
                if route == '/say':
                    text = body.get('text')
                    if not isinstance(text, str) or not text.strip() or len(text) > 400:
                        self._deny(400, 'text is required (<=400 chars)'); return
                    api.say_requested.emit(text.strip(), bool(body.get('speak', True)))
                elif route == '/play':
                    action = body.get('action')
                    if not isinstance(action, str) or not action:
                        self._deny(400, 'action is required'); return
                    api.play_requested.emit(action)
                elif route == '/emote':
                    text = body.get('text')
                    if not isinstance(text, str) or not text:
                        self._deny(400, 'text is required'); return
                    api.emote_requested.emit(text)
                else:
                    self._deny(404, 'not found'); return
                body = b'{"ok":true}'
                self.send_response(200)
                self.send_header('content-type', 'application/json')
                self.send_header('content-length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, name='pet-api', daemon=True)
        self.thread.start()
        record = {'apiVersion': 1, 'url': f'http://127.0.0.1:{self.server.server_address[1]}',
                  'token': self.token, 'pid': os.getpid(), 'at': int(time.time())}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
        os.replace(temp, self.path)
        return record

    def stop(self):
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        try:
            self.path.unlink()
        except OSError:
            pass
