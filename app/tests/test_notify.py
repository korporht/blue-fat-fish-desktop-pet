"""Verify the OS notice: only the two moments that need the user, once per cursor, and the toast itself."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys, unittest
from pathlib import Path
from types import SimpleNamespace
APP = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(APP))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QRect
from dsh_companion import PetCompanion
from toast import Toast
app = QApplication.instance() or QApplication([])


def fake(**over):
    sent = []
    base = dict(notifications_enabled=True, mode='dsh', notice_key=None, session_id='s1',
                session_rows={'s1': {'title': '同步 cartest-platform 项目'}}, project='C:/w',
                activity=SimpleNamespace(cursor=7))
    base.update(over)
    holder = SimpleNamespace(**base)
    holder.notify = SimpleNamespace(emit=lambda kind, title, body: sent.append((kind, title, body)))
    return holder, sent


class NotifyTest(unittest.TestCase):
    def test_completion_and_failure_are_announced(self):
        for after, title in (('success', '任务完成'), ('error', '任务出错')):
            holder, sent = fake()
            PetCompanion.announce(holder, 'executing', after)
            self.assertEqual(len(sent), 1, after)
            kind, announced, body = sent[0]
            self.assertEqual(kind, after)
            self.assertEqual(announced, title)
            self.assertIn('同步 cartest-platform 项目', body)

    def test_waiting_is_announced_once(self):
        holder, sent = fake()
        PetCompanion.announce(holder, 'executing', 'waiting')
        self.assertEqual(sent[0][1], '需要你确认')
        PetCompanion.announce(holder, 'waiting', 'waiting')          # still waiting: no repeat
        self.assertEqual(len(sent), 1)

    def test_quiet_states_and_disabled_switch_stay_silent(self):
        for over, before, after in (({}, 'executing', 'executing'), ({}, 'success', 'success'),
                                    ({'notifications_enabled': False}, 'executing', 'success'),
                                    ({'mode': 'standalone'}, 'executing', 'success')):
            holder, sent = fake(**over)
            PetCompanion.announce(holder, before, after)
            self.assertEqual(sent, [], (over, before, after))

    def test_same_cursor_never_repeats(self):
        holder, sent = fake()
        PetCompanion.announce(holder, 'executing', 'success')
        PetCompanion.announce(holder, 'executing', 'success')         # reconnect replay of the same event
        self.assertEqual(len(sent), 1)

    def test_toast_click_runs_the_callback(self):
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        card = Toast()
        hits = []
        card.show_toast('任务完成', '同步 cartest-platform 项目 · 点这里回到会话', on_click=lambda: hits.append(1))
        self.assertTrue(card.isVisible())
        release = QMouseEvent(QEvent.MouseButtonRelease, QPointF(2, 2), QPointF(2, 2),
                              Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        card.mouseReleaseEvent(release)
        self.assertEqual(hits, [1])
        self.assertFalse(card.isVisible())

    def test_toast_stays_inside_the_screen(self):
        card = Toast()
        card.show_toast('任务完成', 'x' * 40)
        area = QRect(app.primaryScreen().availableGeometry())
        self.assertTrue(area.contains(card.geometry()), (card.geometry(), area))
        card.hide()


if __name__ == '__main__':
    unittest.main()
