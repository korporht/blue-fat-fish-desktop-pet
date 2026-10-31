"""Todo items she keeps for the user: plain JSON, no Qt, easy to test."""
import json
import os
import re
import time
import uuid
from pathlib import Path

TIME_ONLY = re.compile(r'^(?:(\d{1,2})[:：](\d{2}))$')
FULL_TIME = re.compile(r'^(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2})[:：](\d{2})$')


def parse(text, now=None):
    """Split 'text @HH:MM' or 'text @YYYY-MM-DD HH:MM' into (text, due_epoch|None)."""
    now = time.localtime(now if now is not None else time.time())
    text = (text or '').strip()
    if '@' not in text:
        return text, None
    body, _, stamp = text.rpartition('@')
    stamp = stamp.strip()
    match = FULL_TIME.match(stamp)
    if match:
        year, month, day, hour, minute = (int(x) for x in match.groups())
        try:
            return body.strip(), time.mktime((year, month, day, hour, minute, 0, 0, 0, -1))
        except (OverflowError, ValueError):
            return text, None
    match = TIME_ONLY.match(stamp)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
        if hour > 23 or minute > 59:
            return text, None
        due = time.mktime((now.tm_year, now.tm_mon, now.tm_mday, hour, minute, 0, 0, 0, -1))
        if due <= time.time():
            due += 86400          # a time already past means tomorrow
        return body.strip() or text, due
    return text, None


def describe(due):
    if not due:
        return ''
    today = time.strftime('%Y-%m-%d', time.localtime())
    stamp = time.strftime('%Y-%m-%d %H:%M', time.localtime(due))
    return stamp[11:] if stamp.startswith(today) else stamp


class TodoList:
    def __init__(self, data_dir):
        self.path = Path(data_dir) / 'todos.json'
        self.items = []
        self.load()

    def load(self):
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            self.items = []
            return
        rows = data.get('items') if isinstance(data, dict) else None
        self.items = [row for row in (rows or []) if isinstance(row, dict) and row.get('text')]

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps({'items': self.items}, ensure_ascii=False, indent=1), encoding='utf-8')
        os.replace(temp, self.path)

    def add(self, text, due=None):
        body, due_at = parse(text) if due is None else (text.strip(), due)
        if not body:
            return None
        item = {'id': uuid.uuid4().hex[:12], 'text': body[:200], 'due': due_at,
                'done': False, 'notified': False, 'created': time.time()}
        self.items.append(item)
        self.save()
        return item

    def open_items(self):
        return [item for item in self.items if not item.get('done')]

    def nearest(self):
        rows = self.open_items()
        rows.sort(key=lambda item: (item.get('due') is None, item.get('due') or 0))
        return rows[0] if rows else None

    def due_now(self, within=0):
        """Open items whose deadline has arrived and that have not been announced yet."""
        now = time.time()
        return [item for item in self.open_items()
                if item.get('due') and not item.get('notified') and item['due'] <= now + within]

    def mark_notified(self, identity):
        for item in self.items:
            if item.get('id') == identity:
                item['notified'] = True
        self.save()

    def complete(self, identity):
        for item in self.items:
            if item.get('id') == identity:
                item['done'] = True
        self.save()

    def remove(self, identity):
        self.items = [item for item in self.items if item.get('id') != identity]
        self.save()

    def clear_done(self):
        self.items = [item for item in self.items if not item.get('done')]
        self.save()

    def describe(self, limit=6):
        rows = self.open_items()
        if not rows:
            return '现在没有待办啦。'
        lines = []
        for item in rows[:limit]:
            when = describe(item.get('due'))
            lines.append(('• ' + (when + ' ' if when else '') + item['text']))
        if len(rows) > limit:
            lines.append(f'…还有 {len(rows) - limit} 件')
        return '\n'.join(lines)
