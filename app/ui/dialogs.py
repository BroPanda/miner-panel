"""Діалоги: гаманець, видача монет, власник воркера, код контрольної точки, підтвердження."""
from __future__ import annotations

from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QGridLayout, QLineEdit, QMessageBox,
                               QPlainTextEdit, QVBoxLayout, QWidget)

from .widgets import button, label
from ..i18n import num, tr


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
    bb.addButton(tr('Скасувати'), QDialogButtonBox.RejectRole)
    bb.rejected.connect(d.reject)
    v.addWidget(bb)
    return bb


def confirm(parent, title: str, text: str, ok: str = tr('Так')) -> bool:
    m = QMessageBox(parent)
    m.setWindowTitle(title)
    m.setText(text)
    m.setIcon(QMessageBox.Question)
    y = m.addButton(ok, QMessageBox.AcceptRole)
    m.addButton(tr('Скасувати'), QMessageBox.RejectRole)
    m.exec()
    return m.clickedButton() is y


def info(parent, title: str, text: str, error: bool = False) -> None:
    (QMessageBox.warning if error else QMessageBox.information)(parent, title, text)


def wallet(parent, ticker: str, lab: str = tr('Мій гаманець'), address: str = "", edit: bool = False) -> dict | None:
    d, v = _dialog(parent, tr('{0} гаманець {1}').format('Змінити' if edit else 'Новий', ticker))
    g = QGridLayout()
    g.addWidget(label(tr('Назва (напр. «Pearl Wallet», «SafeTrade»)')), 0, 0)
    name = QLineEdit(lab)
    g.addWidget(name, 1, 0)
    g.addWidget(label(tr('Адреса {0}').format(ticker)), 2, 0)
    addr = QLineEdit(address)
    g.addWidget(addr, 3, 0)
    v.addLayout(g)
    v.addWidget(label(tr('Адресу візьми в гаманці або на біржі (розділ «Депозит» для цієї монети).'), "Muted", wrap=True))
    bb = _buttons(d, v, tr('Зберегти') if edit else tr('Додати'))

    def ok():
        a = addr.text().strip()
        if len(a) < 20 or any(ch.isspace() for ch in a):
            info(d, tr('Гаманець'), tr('Схоже, це не адреса гаманця: має бути без пробілів і не коротша за 20 символів.'), True)
            return
        d.accept()
    bb.accepted.connect(ok)
    if d.exec() != QDialog.Accepted:
        return None
    return {"label": name.text().strip() or tr('Гаманець'), "address": addr.text().strip()}


def _own_show(o: str) -> str:
    """Власники «Я» / «без власника» зберігаються українською — у списку показуємо перекладом."""
    from ..core.ledger import OWNER_ME, OWNER_NONE
    return tr(o) if o in (OWNER_ME, OWNER_NONE) else o


def _own_raw(text: str) -> str:
    from ..core.ledger import OWNER_ME, OWNER_NONE
    return next((o for o in (OWNER_ME, OWNER_NONE) if text == tr(o)), text)


def owner(parent, worker: str, owners: list[str], current: str) -> str | None:
    d, v = _dialog(parent, tr('Власник воркера {0}').format(worker))
    v.addWidget(label(tr("Хто отримує монети цього воркера (вибери або впиши ім'я):")))
    c = QComboBox()
    c.setEditable(True)
    c.addItems([_own_show(o) for o in owners])
    c.setCurrentText(_own_show(current))
    v.addWidget(c)
    bb = _buttons(d, v, tr('Зберегти'))
    bb.accepted.connect(d.accept)
    if d.exec() != QDialog.Accepted:
        return None
    return _own_raw(c.currentText().strip())


def payout(parent, owners: list[str], tickers: list[str], left: dict) -> dict | None:
    """left: {(власник, тікер): залишок} — показується під полем."""
    d, v = _dialog(parent, tr('Записати видачу монет'))
    g = QGridLayout()
    g.setHorizontalSpacing(12)
    who = QComboBox()
    who.setEditable(True)
    who.addItems([_own_show(o) for o in owners])
    tk = QComboBox()
    tk.addItems(tickers)
    amt = QDoubleSpinBox()
    amt.setDecimals(6)
    amt.setRange(0, 1e9)
    note = QLineEdit()
    hint = label("", "Muted")
    for i, (k, w) in enumerate(((tr('Кому'), who), (tr('Монета'), tk), (tr('Скільки монет'), amt), (tr('Примітка'), note))):
        g.addWidget(label(k, "Secondary"), i, 0)
        g.addWidget(w, i, 1)
    g.addWidget(hint, 2, 2)
    v.addLayout(g)

    def upd():
        x = left.get((_own_raw(who.currentText().strip()), tk.currentText()))
        hint.setText(tr('залишок {0}').format(num(f"{x:.6f}")) if x is not None else "")
    who.currentTextChanged.connect(upd)
    tk.currentTextChanged.connect(upd)
    upd()
    bb = _buttons(d, v, tr('Записати'))

    def ok():
        if not who.currentText().strip() or amt.value() <= 0:
            info(d, tr('Видача'), tr('Вкажи, кому, і додатну кількість монет.'), True)
            return
        d.accept()
    bb.accepted.connect(ok)
    if d.exec() != QDialog.Accepted:
        return None
    return {"owner": _own_raw(who.currentText().strip()), "ticker": tk.currentText(), "coins": amt.value(), "note": note.text().strip()}


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
        cp = button(tr('Копіювати'), "Primary")
        cp.clicked.connect(lambda: (QGuiApplication.clipboard().setText(t.toPlainText()), cp.setText(tr('Скопійовано ✓'))))
        bb.addButton(cp, QDialogButtonBox.ActionRole)
        bb.addButton(tr('Закрити'), QDialogButtonBox.RejectRole)
    else:
        ok = bb.addButton(tr('Імпорт'), QDialogButtonBox.AcceptRole)
        ok.setObjectName("Primary")
        bb.addButton(tr('Скасувати'), QDialogButtonBox.RejectRole)
        bb.accepted.connect(d.accept)
    bb.rejected.connect(d.reject)
    v.addWidget(bb)
    if d.exec() != QDialog.Accepted:
        return None
    return t.toPlainText().strip()
