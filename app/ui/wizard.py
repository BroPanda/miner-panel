"""Майстер першого запуску: крок за кроком від відеокарти до «Почати майнінг».
data — реальні дані від контролера (або sample.wizard_data() для --demo); вибір віддається сигналом finished_ok."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLineEdit,
                               QProgressBar, QStackedWidget, QVBoxLayout, QWidget)

from .widgets import Card, button, label, with_help

STEPS = ["Відеокарта", "Тариф", "Монета і пул", "Гаманець", "Ферма HiveOS", "Готово"]


class Wizard(QDialog):
    finished_ok = Signal(dict)

    def __init__(self, parent=None, data: dict | None = None):
        super().__init__(parent)
        if data is None:
            from .sample import wizard_data
            data = wizard_data()
        self.d = data
        self.setWindowTitle("Налаштування Miner Panel")
        self.setMinimumSize(720, 520)
        v = QVBoxLayout(self)
        v.setContentsMargins(28, 24, 28, 20)
        v.setSpacing(14)
        self.step_label = label("", "Muted")
        v.addWidget(self.step_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, len(STEPS) - 1)
        self.progress.setFixedHeight(6)
        v.addWidget(self.progress)
        self.stack = QStackedWidget()
        v.addWidget(self.stack, 1)

        # 1. Відеокарта
        gpu = data.get("gpu")
        self.stack.addWidget(self._page(
            "Знайшли твою відеокарту" if gpu else "Відеокарту NVIDIA не знайдено",
            "Панель керує нею через драйвер NVIDIA: лише знижує частоти й потужність (ніколи не підвищує напругу) "
            "і повертає заводські налаштування, коли майнінг зупиняється.",
            [label(f"✓  {gpu}", "CardTitle"), label("Керування частотами і потужністю доступне", "Secondary")] if gpu else
            [label("Перевір, що встановлено драйвер NVIDIA і карта видна в «Диспетчері пристроїв». "
                   "Налаштувати решту можна й зараз.", "Secondary", wrap=True)]))
        # 2. Тариф
        self.two = QCheckBox("Двозонний лічильник (вночі світло дешевше)")
        self.two.setChecked(bool(data.get("two", True)))
        self.day, self.night = QDoubleSpinBox(), QDoubleSpinBox()
        for s, val in ((self.day, data.get("day", 4.32)), (self.night, data.get("night", 2.16))):
            s.setRange(0, 50)
            s.setDecimals(2)
            s.setSingleStep(0.01)
            s.setValue(float(val))
        night_lab = label(f"Нічний тариф ({data.get('night_hours', '23:00–07:00')})")
        self.two.toggled.connect(lambda on: (self.night.setEnabled(on), night_lab.setEnabled(on)))
        g = QGridLayout()
        g.addWidget(self.two, 0, 0, 1, 2)
        g.addWidget(label("Денний тариф, ₴ за кВт·год"), 1, 0)
        g.addWidget(self.day, 1, 1)
        g.addWidget(night_lab, 2, 0)
        g.addWidget(self.night, 2, 1)
        self.stack.addWidget(self._page("Скільки коштує світло?", "Від цього залежить, скільки ти реально заробляєш після оплати електрики.", [g]))
        # 3. Монета, пул, майнер
        self.coin, self.pool, self.miner = QComboBox(), QComboBox(), QComboBox()
        for tk, text in data.get("coins", []):
            self.coin.addItem(text, tk)
        self.coin.currentIndexChanged.connect(self._coin_changed)
        self.pool.currentIndexChanged.connect(self._pool_changed)
        g = QGridLayout()
        g.addWidget(label("Монета"), 0, 0)
        g.addWidget(self.coin, 0, 1)
        g.addWidget(with_help("Пул", "pool"), 1, 0)
        g.addWidget(self.pool, 1, 1)
        g.addWidget(label("Майнер"), 2, 0)
        g.addWidget(self.miner, 2, 1)
        g.setColumnStretch(1, 1)
        self.stack.addWidget(self._page("Що майнити", "Монети — від найвигіднішої для твоєї карти з твоїм тарифом. "
                                        "Майнер завантажиться з офіційного GitHub і буде перевірений за SHA256.",
                                        [g] + ([label(data["coins_note"], "Muted", wrap=True)] if data.get("coins_note") else [])))
        # 4. Гаманець
        self.addr, self.worker = QLineEdit(), QLineEdit(str(data.get("worker", "")))
        self.worker.setMaxLength(32)
        self.addr_lab = label("Адреса гаманця")
        g = QGridLayout()
        g.addWidget(self.addr_lab, 0, 0)
        g.addWidget(self.addr, 0, 1)
        g.addWidget(with_help("Ім'я цього ПК на пулі", "worker"), 1, 0)
        g.addWidget(self.worker, 1, 1)
        g.setColumnStretch(1, 1)
        self.stack.addWidget(self._page("Куди надходитимуть монети", "Пул збирає монети і переказує на цей гаманець, коли набереться поріг виплати. "
                                        "Адресу візьми в гаманці або на біржі (розділ «Депозит» для цієї монети).", [g]))
        # 5. HiveOS
        self.tok = QLineEdit()
        self.tok.setEchoMode(QLineEdit.Password)
        self.tok.setPlaceholderText("необов'язково")
        self.stack.addWidget(self._page("Є ферма на HiveOS?", "Встав персональний токен (HiveOS → Account → API tokens) — "
                                        "і риги з'являться поруч із цим ПК. Можна пропустити й додати пізніше в «Налаштуваннях».", [self.tok]))
        # 6. Готово
        self.summary = label("", "Secondary", wrap=True)
        self.stack.addWidget(self._page("Усе готово", "Панель стежитиме за пулом і температурою та повідомить, якщо щось піде не так.",
                                        [self.summary,
                                         label("Після старту панель можна згорнути — вона працюватиме біля годинника.", "Secondary", wrap=True)]))

        nav = QHBoxLayout()
        self.back = button("← Назад", None, self.prev)
        self.skip = button("Пропустити майстер", "Link", self.reject)
        self.next = button("Далі →", "Primary", self.forward)
        nav.addWidget(self.skip)
        nav.addStretch(1)
        nav.addWidget(self.back)
        nav.addWidget(self.next)
        v.addLayout(nav)
        i = self.coin.findData(data.get("ticker"))
        self.coin.setCurrentIndex(i if i >= 0 else 0)
        self._coin_changed()
        self.go(0)

    def _page(self, title: str, text: str, widgets: list) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 8, 0, 0)
        v.setSpacing(12)
        v.addWidget(label(title, "Big"))
        v.addWidget(label(text, "Secondary", wrap=True))
        c = Card()
        for x in widgets:
            (c.body.addLayout if hasattr(x, "addWidget") and not isinstance(x, QWidget) else c.body.addWidget)(x)
        v.addWidget(c)
        v.addStretch(1)
        return w

    @staticmethod
    def _fill(cb: QComboBox, items: list, value=None) -> None:
        cb.blockSignals(True)
        cb.clear()
        for key, text in items:
            cb.addItem(text, key)
        i = cb.findData(value)
        cb.setCurrentIndex(i if i >= 0 else 0)
        cb.blockSignals(False)

    def _coin_changed(self, *_):
        tk = self.coin.currentData()
        self._fill(self.pool, self.d.get("pools", {}).get(tk, []), self.d.get("coin_default", {}).get(tk))
        self._pool_changed()
        self.addr_lab.setText(f"Адреса гаманця {tk or ''}".strip())
        self.addr.setText(self.d.get("wallets", {}).get(tk, ""))

    def _pool_changed(self, *_):
        cid = self.pool.currentData()
        self._fill(self.miner, self.d.get("miners", {}).get(cid, []), self.d.get("miner_default", {}).get(cid))

    def result_data(self) -> dict:
        return {"two": self.two.isChecked(), "day": self.day.value(), "night": self.night.value(),
                "coin": self.pool.currentData(), "miner": self.miner.currentData(), "address": self.addr.text().strip(),
                "worker": self.worker.text().strip(), "hive": self.tok.text().strip()}

    def go(self, i: int) -> None:
        self.stack.setCurrentIndex(i)
        self.progress.setValue(i)
        self.step_label.setText(f"Крок {i + 1} з {len(STEPS)} · {STEPS[i]}")
        self.back.setEnabled(i > 0)
        last = i == len(STEPS) - 1
        if last:
            r = self.result_data()
            text = f"{self.coin.currentText().split(' — ')[0]} · {self.pool.currentText()} · {self.miner.currentText()}."
            text += f"\nГаманець: {r['address'][:10]}…{r['address'][-6:]}" if len(r["address"]) > 20 else \
                f"\nГаманець: {r['address']}" if r["address"] else \
                "\nГаманець не вказано — майнінг почнеться, коли додаси його на сторінці «Монети»."
            self.summary.setText(text)
        self.next.setText(("Почати майнінг" if self.addr.text().strip() else "Готово") if last else "Далі →")

    def prev(self):
        self.go(max(0, self.stack.currentIndex() - 1))

    def forward(self):
        i = self.stack.currentIndex()
        if i == len(STEPS) - 1:
            self.finished_ok.emit(self.result_data())
            self.accept()
        else:
            self.go(i + 1)
