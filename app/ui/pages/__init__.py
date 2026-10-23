from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget


class Page(QScrollArea):
    """Сторінка з прокруткою. render(snap, expert) показує знімок стану; дії — через сигнал action(id)."""
    action = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("Page")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.inner = QWidget()
        self.inner.setObjectName("Page")
        self.lay = QVBoxLayout(self.inner)
        self.lay.setContentsMargins(24, 20, 24, 24)
        self.lay.setSpacing(16)
        self.setWidget(self.inner)

    def render(self, snap: dict, expert: bool) -> None:  # pragma: no cover — перевизначають сторінки
        raise NotImplementedError
