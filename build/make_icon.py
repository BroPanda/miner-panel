"""Значок програми: темний квадрат із заокругленням, синє коло і кирка. Пише build/icon.png та build/icon.ico."""
import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPainterPath

out = Path(__file__).parent
app = QGuiApplication(sys.argv[:1])
for size in (256,):
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(8, 8, size - 16, size - 16), size * 0.2, size * 0.2)
    p.fillPath(path, QColor("#1a1a19"))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#3987e5"))
    p.drawEllipse(QRectF(size * 0.18, size * 0.18, size * 0.64, size * 0.64))
    p.setPen(QColor("#ffffff"))
    f = QFont("Segoe UI Emoji" if sys.platform == "win32" else "Noto Color Emoji")
    f.setPixelSize(int(size * 0.38))
    p.setFont(f)
    p.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, "⛏")
    p.end()
    img.save(str(out / "icon.png"))
    img.save(str(out / "icon.ico"))
print(out / "icon.ico")
