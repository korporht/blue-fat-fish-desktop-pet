"""A small badge above her head: the nearest todo, or how many are open."""
from PySide6.QtCore import Qt, QPoint, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

QSS = '''
#whale-todo { background: #FCFAF5; border: 1px solid #D5E0EE; border-radius: 11px; }
#whale-todo QLabel { color: #315576; font-family: "Microsoft YaHei UI"; font-size: 12px; }
'''


class TodoBadge(QWidget):
    """Read-only, follows the pet, hidden when nothing is open."""

    def __init__(self, companion):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.WindowDoesNotAcceptFocus | Qt.NoDropShadowWindowHint)
        self.companion = companion
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowTitle('蓝色大肥鱼 · 待办')
        self.card = QFrame(self)
        self.card.setObjectName('whale-todo')
        self.card.setStyleSheet(QSS)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.card)
        row = QHBoxLayout(self.card)
        row.setContentsMargins(10, 4, 11, 5)
        self.label = QLabel('', self.card)
        row.addWidget(self.label)
        self.timer = QTimer(self, timeout=self.tick)
        self.timer.setInterval(250)

    def refresh(self):
        todos = getattr(self.companion, 'todos', None)
        if todos is None:
            self.hide()
            return
        items = todos.open_items()
        if not items:
            self.hide()
            return
        nearest = todos.nearest()
        when = ''
        if nearest and nearest.get('due'):
            from todos import describe
            when = describe(nearest['due']) + ' '
        text = (when + nearest['text']) if len(items) == 1 else f'{len(items)} 件待办 · {when}{nearest["text"]}'
        self.label.setText(text[:34] + ('…' if len(text) > 34 else ''))
        self.card.adjustSize()
        self.adjustSize()
        if self.companion.pet.isVisible():
            self.anchor()
            self.show()
            self.raise_()
            self.timer.start()
        else:
            self.hide()

    def anchor(self):
        pet = self.companion.pet
        area = pet._screen_rect()
        self.setFixedWidth(min(320, max(120, self.sizeHint().width())))
        reference = pet.reply_anchor_rect()
        x = max(area.left(), min(reference.center().x() - self.width() // 2, area.right() + 1 - self.width()))
        y = reference.top() - self.height() - 6
        if y < area.top():
            y = min(area.bottom() + 1 - self.height(), reference.bottom() + 6)
        point = QPoint(x, max(area.top(), min(y, area.bottom() + 1 - self.height())))
        if point != self.pos():
            self.move(point)

    def tick(self):
        if not self.companion.pet.isVisible():
            self.hide()
            return
        self.anchor()

    def showEvent(self, event):
        self.anchor()
        self.timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            todos = getattr(self.companion, 'todos', None)
            if todos is not None:
                self.companion.report(todos.describe())
        super().mouseReleaseEvent(event)
