"""Значки бічного меню, намальовані лініями: не залежать від шрифту (символи на кшталт ▦ ◈ у Segoe UI крихітні)."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from . import theme


def _draw(key: str, p: QPainter, s: float) -> None:
    """Малюнок у квадраті s×s (лінія ~1/12 розміру)."""
    m = s * 0.12
    r = QRectF(m, m, s - 2 * m, s - 2 * m)
    if key == "overview":                       # чотири плитки
        g = r.width() * 0.14
        w = (r.width() - g) / 2
        for i in range(2):
            for j in range(2):
                p.drawRoundedRect(QRectF(r.left() + i * (w + g), r.top() + j * (w + g), w, w), s * 0.06, s * 0.06)
    elif key == "devices":                      # відеокарта: плата з вентилятором
        body = QRectF(r.left(), r.top() + r.height() * 0.2, r.width(), r.height() * 0.6)
        p.drawRoundedRect(body, s * 0.08, s * 0.08)
        c = QPointF(body.left() + body.width() * 0.38, body.center().y())
        p.drawEllipse(c, body.height() * 0.3, body.height() * 0.3)
        p.drawLine(QPointF(body.right() - body.width() * 0.22, body.top() + body.height() * 0.3),
                   QPointF(body.right() - body.width() * 0.22, body.bottom() - body.height() * 0.3))
    elif key == "money":                        # гаманець
        body = QRectF(r.left(), r.top() + r.height() * 0.15, r.width(), r.height() * 0.75)
        p.drawRoundedRect(body, s * 0.1, s * 0.1)
        tab = QRectF(body.right() - body.width() * 0.38, body.center().y() - body.height() * 0.17,
                     body.width() * 0.38, body.height() * 0.34)
        p.drawRoundedRect(tab, s * 0.05, s * 0.05)
    elif key == "coins":                        # стос монет
        w, h = r.width(), r.height() * 0.28
        for k in range(3):
            p.drawEllipse(QRectF(r.left(), r.bottom() - h - k * r.height() * 0.3, w, h))
    elif key == "settings":                     # шестерня
        c = r.center()
        ro, ri = r.width() * 0.5, r.width() * 0.36
        path = QPainterPath()
        n = 8
        for i in range(n * 2):
            a0 = math.pi * 2 * i / (n * 2)
            a1 = math.pi * 2 * (i + 1) / (n * 2)
            rad = ro if i % 2 == 0 else ri
            pt0 = QPointF(c.x() + rad * math.cos(a0), c.y() + rad * math.sin(a0))
            pt1 = QPointF(c.x() + rad * math.cos(a1), c.y() + rad * math.sin(a1))
            if i == 0:
                path.moveTo(pt0)
            else:
                path.lineTo(pt0)
            path.lineTo(pt1)
        path.closeSubpath()
        p.drawPath(path)
        p.drawEllipse(c, r.width() * 0.14, r.width() * 0.14)
    elif key == "journal":                      # список
        for k in range(3):
            y = r.top() + r.height() * (0.2 + 0.3 * k)
            p.drawEllipse(QPointF(r.left() + s * 0.05, y), s * 0.03, s * 0.03)
            p.drawLine(QPointF(r.left() + r.width() * 0.25, y), QPointF(r.right(), y))


def nav_icon(key: str, size: int) -> QIcon:
    """Значок розділу: звичайний — другорядним кольором, вибраний (checked) — основним."""
    t = theme.current()
    icon = QIcon()
    for color, state in ((t.ink2, QIcon.Off), (t.ink, QIcon.On)):
        dpr = 2
        pm = QPixmap(size * dpr, size * dpr)
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(color), max(1.5, size / 12))
        pen.setJoinStyle(Qt.RoundJoin)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        _draw(key, p, size)
        p.end()
        icon.addPixmap(pm, QIcon.Normal, state)
        icon.addPixmap(pm, QIcon.Active, state)
    return icon


