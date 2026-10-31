"""Always-on-top notice card: a task finished, or she is waiting for an answer in dsh."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QVBoxLayout, QWidget

CARD_QSS = '''
#whale-toast-card { background: #FCFAF5; border: 1px solid #D5E0EE; border-radius: 14px; }
#whale-toast-title { color: #24406B; font-family: "Microsoft YaHei UI"; font-size: 13px; font-weight: 600; }
#whale-toast-body { color: #58718F; font-family: "Microsoft YaHei UI"; font-size: 12px; }
'''


class Toast(QWidget):
    """One reusable card in the bottom-right corner; never takes focus away from the user."""

    def __init__(self, parent=None):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowTitle('蓝色大肥鱼')
        self.setFixedWidth(300)
        card = QFrame(self)
        card.setObjectName('whale-toast-card')
        card.setStyleSheet(CARD_QSS)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)
        inner = QVBoxLayout(card)
        inner.setContentsMargins(14, 11, 14, 12)
        inner.setSpacing(3)
        self.title = QLabel('', card)
        self.title.setObjectName('whale-toast-title')
        self.body = QLabel('', card)
        self.body.setObjectName('whale-toast-body')
        self.body.setWordWrap(True)
        inner.addWidget(self.title)
        inner.addWidget(self.body)
        self._on_click = None
        self._timer = QTimer(self, singleShot=True, timeout=self.hide)

    def show_toast(self, title, body='', on_click=None, msecs=7000):
        self._on_click = on_click
        self.title.setText(title)
        self.body.setText(body)
        self.body.setVisible(bool(body))
        self.adjustSize()
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        self.move(max(area.left(), area.right() + 1 - self.width() - 12),
                  max(area.top(), area.bottom() + 1 - self.height() - 12))
        self.show()
        self.raise_()
        self._timer.start(msecs)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            action, self._on_click = self._on_click, None
            self._timer.stop()
            self.hide()
            if action:
                action()
        super().mouseReleaseEvent(event)

    def enterEvent(self, event):
        self._timer.stop()          # do not vanish while the cursor is on it
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self.isVisible():
            self._timer.start(3000)
        super().leaveEvent(event)
