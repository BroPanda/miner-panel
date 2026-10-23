"""Діалоги: гаманець, видача монет, власник воркера, код контрольної точки, підтвердження."""
from __future__ import annotations

from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QGridLayout, QLineEdit, QMessageBox,
                               QPlainTextEdit, QVBoxLayout, QWidget)

from .widgets import button, label


def _dialog(parent, title: str) -> tuple[QDialog, QVBoxLayout]:
    d = QDialog(parent)
    d.setWindowTitle(title)
    d.setMinimumWidth(460)
    v = QVBoxLayout(d)
    v.setContentsMargins(20, 18, 20, 16)
    v.setSpacing(12)
    return d, v


def _buttons(d: QDialog, v: QVBoxLayout, ok_text: str) -> QDialogButtonBox:
    bb = QDialogButtonBox()
    ok = bb.addButton(ok_text, QDialogButtonBox.AcceptRole)
    ok.setObjectName("Primary")
    bb.addButton("Скасувати", QDialogButtonBox.RejectRole)
    bb.rejected.connect(d.reject)
    v.addWidget(bb)
    return bb


def confirm(parent, title: str, text: str, ok: str = "Так") -> bool:
    m = QMessageBox(parent)
    m.setWindowTitle(title)
    m.setText(text)
    m.setIcon(QMessageBox.Question)
    y = m.addButton(ok, QMessageBox.AcceptRole)
    m.addButton("Скасувати", QMessageBox.RejectRole)
    m.exec()
    return m.clickedButton() is y


def info(parent, title: str, text: str, error: bool = False) -> None:
    (QMessageBox.warning if error else QMessageBox.information)(parent, title, text)


def wallet(parent, ticker: str, lab: str = "Мій гаманець", address: str = "", edit: bool = False) -> dict | None:
    d, v = _dialog(parent, f"{'Змінити' if edit else 'Новий'} гаманець {ticker}")
    g = QGridLayout()
    g.addWidget(label("Назва (напр. «Pearl Wallet», «SafeTrade»)"), 0, 0)
    name = QLineEdit(lab)
    g.addWidget(name, 1, 0)
    g.addWidget(label(f"Адреса {ticker}"), 2, 0)
    addr = QLineEdit(address)
    g.addWidget(addr, 3, 0)
    v.addLayout(g)
    v.addWidget(label("Адресу візьми в гаманці або на біржі (розділ «Депозит» для цієї монети).", "Muted", wrap=True))
    bb = _buttons(d, v, "Зберегти" if edit else "Додати")

    def ok():
        a = addr.text().strip()
        if len(a) < 20 or any(ch.isspace() for ch in a):
            info(d, "Гаманець", "Схоже, це не адреса гаманця: має бути без пробілів і не коротша за 20 символів.", True)
            return
        d.accept()
    bb.accepted.connect(ok)
    if d.exec() != QDialog.Accepted:
        return None
    return {"label": name.text().strip() or "Гаманець", "address": addr.text().strip()}


def owner(parent, worker: str, owners: list[str], current: str) -> str | None:
    d, v = _dialog(parent, f"Власник воркера {worker}")
    v.addWidget(label("Хто отримує монети цього воркера (вибери або впиши ім'я):"))
    c = QComboBox()
    c.setEditable(True)
    c.addItems(owners)
    c.setCurrentText(current)
    v.addWidget(c)
    bb = _buttons(d, v, "Зберегти")
    bb.accepted.connect(d.accept)
    if d.exec() != QDialog.Accepted:
        return None
    return c.currentText().strip()


def payout(parent, owners: list[str], tickers: list[str], left: dict) -> dict | None:
    """left: {(власник, тікер): залишок} — показується під полем."""
    d, v = _dialog(parent, "Записати видачу монет")
    g = QGridLayout()
    g.setHorizontalSpacing(12)
    who = QComboBox()
    who.setEditable(True)
    who.addItems(owners)
    tk = QComboBox()
    tk.addItems(tickers)
    amt = QDoubleSpinBox()
    amt.setDecimals(6)
    amt.setRange(0, 1e9)
    note = QLineEdit()
    hint = label("", "Muted")
    for i, (k, w) in enumerate((("Кому", who), ("Монета", tk), ("Скільки монет", amt), ("Примітка", note))):
        g.addWidget(label(k, "Secondary"), i, 0)
        g.addWidget(w, i, 1)
    g.addWidget(hint, 2, 2)
    v.addLayout(g)

    def upd():
        x = left.get((who.currentText().strip(), tk.currentText()))
        hint.setText(f"залишок {x:.6f}".replace(".", ",") if x is not None else "")
    who.currentTextChanged.connect(upd)
    tk.currentTextChanged.connect(upd)
    upd()
    bb = _buttons(d, v, "Записати")

    def ok():
        if not who.currentText().strip() or amt.value() <= 0:
            info(d, "Видача", "Вкажи, кому, і додатну кількість монет.", True)
            return
        d.accept()
    bb.accepted.connect(ok)
    if d.exec() != QDialog.Accepted:
        return None
    return {"owner": who.currentText().strip(), "ticker": tk.currentText(), "coins": amt.value(), "note": note.text().strip()}


def code(parent, title: str, caption: str, text: str = "", readonly: bool = True) -> str | None:
    d, v = _dialog(parent, title)
    d.setMinimumWidth(560)
    v.addWidget(label(caption, wrap=True))
    t = QPlainTextEdit(text)
    t.setReadOnly(readonly)
    t.setFont(QFont("Consolas", 9))
    t.setMinimumHeight(150)
    v.addWidget(t)
    bb = QDialogButtonBox()
    if readonly:
        cp = button("Копіювати", "Primary")
        cp.clicked.connect(lambda: (QGuiApplication.clipboard().setText(t.toPlainText()), cp.setText("Скопійовано ✓")))
        bb.addButton(cp, QDialogButtonBox.ActionRole)
        bb.addButton("Закрити", QDialogButtonBox.RejectRole)
    else:
        ok = bb.addButton("Імпорт", QDialogButtonBox.AcceptRole)
        ok.setObjectName("Primary")
        bb.addButton("Скасувати", QDialogButtonBox.RejectRole)
        bb.accepted.connect(d.accept)
    bb.rejected.connect(d.reject)
    v.addWidget(bb)
    if d.exec() != QDialog.Accepted:
        return None
    return t.toPlainText().strip()
