"""Todo storage and the reminder window: plain data, no Qt."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys, tempfile, time, unittest
from pathlib import Path
APP = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(APP))
from todos import TodoList, parse, describe

NOON = time.mktime((2026, 10, 31, 12, 0, 0, 0, 0, -1))


class ParseTests(unittest.TestCase):
    def test_plain_text_has_no_deadline(self):
        self.assertEqual(parse('买牛奶', now=NOON), ('买牛奶', None))

    def test_today_time_and_rollover(self):
        body, due = parse('开会 @18:30', now=NOON)
        self.assertEqual(body, '开会')
        self.assertEqual(time.strftime('%H:%M', time.localtime(due)), '18:30')
        self.assertEqual(time.strftime('%d', time.localtime(due)), '31')
        body, due = parse('晨跑 @07:00', now=NOON)          # already past -> tomorrow
        self.assertEqual(time.strftime('%d', time.localtime(due)), '01')

    def test_full_date_and_garbage(self):
        _, due = parse('交报告 @2026-11-02 09:00', now=NOON)
        self.assertEqual(time.strftime('%Y-%m-%d %H:%M', time.localtime(due)), '2026-11-02 09:00')
        self.assertEqual(parse('给 @ 你', now=NOON), ('给 @ 你', None))
        self.assertEqual(parse('坏时间 @25:99', now=NOON), ('坏时间 @25:99', None))


class TodoListTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.todos = TodoList(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_add_persists_and_survives_reload(self):
        item = self.todos.add('买牛奶')
        self.assertEqual(item['text'], '买牛奶')
        again = TodoList(self.temp.name)
        self.assertEqual(len(again.open_items()), 1)
        self.assertEqual(again.open_items()[0]['id'], item['id'])

    def test_complete_remove_and_clear(self):
        first = self.todos.add('A'); second = self.todos.add('B')
        self.todos.complete(first['id'])
        self.assertEqual([i['text'] for i in self.todos.open_items()], ['B'])
        self.todos.remove(second['id'])
        self.assertEqual(self.todos.open_items(), [])
        self.todos.clear_done()
        self.assertEqual(self.todos.items, [])

    def test_nearest_sorts_by_deadline_then_undated(self):
        later = self.todos.add('later', due=NOON + 7200)
        sooner = self.todos.add('sooner', due=NOON + 600)
        self.todos.add('nodate')
        self.assertEqual(self.todos.nearest()['id'], sooner['id'])
        self.todos.complete(sooner['id'])
        self.assertEqual(self.todos.nearest()['id'], later['id'])

    def test_due_now_fires_once(self):
        item = self.todos.add('到点', due=NOON)
        self.assertEqual([i['id'] for i in self.todos.due_now()], [item['id']])
        self.todos.mark_notified(item['id'])
        self.assertEqual(self.todos.due_now(), [])
        self.assertEqual(TodoList(self.temp.name).due_now(), [])   # the flag is persisted

    def test_describe_lists_open_items(self):
        self.todos.add('买牛奶', due=NOON)
        text = self.todos.describe()
        self.assertIn('买牛奶', text)
        self.assertIn('12:00', text)
        self.todos.complete(self.todos.open_items()[0]['id'])
        self.assertEqual(self.todos.describe(), '现在没有待办啦。')


if __name__ == '__main__':
    unittest.main()
