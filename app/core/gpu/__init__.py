"""Відеокарта NVIDIA: стан, розгін (лише вниз від заводських: ліміт потужності, обмеження частот ядра і
пам'яті, зсув пам'яті в безпечних межах) і скидання до заводських. Напругу панель не чіпає ніколи.

Windows: nvidia-smi + NVAPI (зсув пам'яті), потрібні права адміністратора.
Linux: читання — nvidia-smi від користувача; зміни — через помічник з білим списком дій
(/usr/local/bin/minerpanel-gpu, запускається `sudo -n`; встановлюється командою --install).
У тестовому режимі зміни не виконуються ніколи."""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass

from ..platform import IS_WIN, run_quiet

HELPER = "/usr/local/bin/minerpanel-gpu"

# Безпечні межі зсуву пам'яті (МГц, як показує nvidia-smi) для моделей карт; GDDR6X гріється сильніше
MEM_OFFSET_LIMITS = [("RTX 3060 Ti", 1200), ("RTX 3060", 1000), ("RTX 3050", 1000), ("RTX 3070 Ti", 800), ("RTX 3070", 1200),
                     (r"RTX 30(80|90)", 800), (r"RTX 40(50|60)", 1500), ("RTX 4070", 1200), (r"RTX 40(80|90)", 1000),
                     ("RTX 50", 1000), (r"RTX 20|GTX 16", 800)]


@dataclass
class GpuInfo:
    draw: float
    limit: float
    default: float
    min: float
    max: float
    temp: int
    core: int
    mem: int
    fan: int
    name: str


def _smi(*args: str, timeout: float = 15):
    exe = shutil.which("nvidia-smi") or "nvidia-smi"
    try:
        return run_quiet([exe, "-i", "0", *args], timeout)
    except (OSError, Exception):  # noqa: BLE001
        return None


def _num(s: str) -> float:
    try:
        return float(s)
    except ValueError:
        return 0.0


class Gpu:
    def __init__(self, test: bool = False):
        self.test = test
        self.mem_lock_error: str | None = None
        self.mem_off_error: str | None = None
        self._nvapi = None
        if IS_WIN:
            from . import nvapi_win
            self._nvapi = nvapi_win
        self.limits = self.read_limits()
        self.mem_clocks = self.read_mem_clocks()

    # ---- читання ----
    def info(self) -> GpuInfo | None:
        r = _smi("--query-gpu=power.draw,power.limit,power.default_limit,power.min_limit,power.max_limit,"
                 "temperature.gpu,clocks.gr,clocks.mem,fan.speed,name", "--format=csv,noheader,nounits", timeout=5)
        if not r or r.returncode != 0 or not r.stdout.strip():
            return None
        v = [x.strip() for x in r.stdout.strip().splitlines()[0].split(",")]
        name = re.sub(r"^NVIDIA\s+", "", v[9])
        name = re.sub(r"^GeForce\s+", "", name)
        return GpuInfo(_num(v[0]), _num(v[1]), _num(v[2]), _num(v[3]), _num(v[4]), int(_num(v[5])), int(_num(v[6])),
                       int(_num(v[7])), int(_num(v[8])), name)

    def read_limits(self) -> dict:
        lim = {"core_min": 210, "core_max": 2100, "temp_max": 83}
        r = _smi("--query-supported-clocks=graphics", "--format=csv,noheader,nounits")
        if r and r.returncode == 0:
            clk = sorted({int(x) for x in re.findall(r"\d+", r.stdout) if int(x) > 0})
            if clk:
                lim["core_min"], lim["core_max"] = clk[0], clk[-1]
        r = _smi("-q", "-d", "TEMPERATURE")
        if r and r.returncode == 0:
            t = [int(m) for m in re.findall(r"(?:Target Temperature|Max Operating Temp)[^:]*:\s*(\d+)\s*C", r.stdout)]
            if t:
                lim["temp_max"] = min(t)
        return lim

    def read_mem_clocks(self) -> list[int]:
        """Фіксовані частоти пам'яті, які підтримує карта (напр. 7501, 7301, 5001, 810, 405)."""
        r = _smi("--query-supported-clocks=memory", "--format=csv,noheader,nounits")
        if not r or r.returncode != 0:
            return []
        return sorted({int(x) for x in re.findall(r"\d+", r.stdout) if int(x) > 0}, reverse=True)

    def mem_offset_info(self) -> dict | None:
        """Поточний зсув і межі драйвера: {offset, min, max, base} або None."""
        if self._nvapi:
            return self._nvapi.read()
        return None

    def mem_offset_limits(self, gpu_name: str) -> dict:
        mx, known = 500, False
        for pat, m in MEM_OFFSET_LIMITS:
            if re.search(pat, gpu_name or ""):
                mx, known = m, True
                break
        info = self.mem_offset_info()
        if not info:
            return {"min": 0, "max": 0, "known": known, "available": False}
        return {"min": max(-500, info["min"]), "max": min(mx, info["max"]), "known": known, "available": True}

    # ---- зміни ----
    def _apply(self, *args: str) -> str:
        """Одна дія nvidia-smi: у Windows — напряму, у Linux — через помічника. Повертає вивід."""
        if IS_WIN:
            r = _smi(*args)
        else:
            try:
                r = run_quiet(["sudo", "-n", HELPER, *args], 20)
            except OSError as e:
                return str(e)
        if not r:
            return "nvidia-smi недоступний"
        return (r.stdout or "") + (r.stderr or "") if r.returncode != 0 else ""

    def set_tuning(self, pl: int, core: int, mem: int = 0, mem_off: int = 0) -> None:
        """mem = 0 — пам'ять заводська, інакше обмеження зверху; mem_off — зсув пам'яті (МГц)."""
        if self.test:
            return
        self.mem_off_error = self.set_mem_offset(mem_off)
        self._apply("-pl", str(int(pl)))
        self._apply("-lgc", f"210,{int(core)}") if core > 0 else self._apply("-rgc")
        if mem > 0:
            out = self._apply("-lmc", f"405,{int(mem)}")
            self.mem_lock_error = out.strip() if re.search(r"(?i)not supported|insufficient|failed|error", out) else None
        else:
            self._apply("-rmc")

    def set_mem_offset(self, mhz: int) -> str | None:
        if self.test:
            return None
        if self._nvapi:
            return self._nvapi.set_offset(int(mhz))
        return None if mhz == 0 else "зсув пам'яті в Linux поки не підтримується — решта розгону працює"

    def reset(self) -> None:
        if self.test:
            return
        g = self.info()
        self._apply("-pl", str(int(g.default if g else 170)))
        self._apply("-rgc")
        self._apply("-rmc")
        self.set_mem_offset(0)

    @staticmethod
    def helper_installed() -> bool:
        if IS_WIN:
            return True
        try:
            return run_quiet(["sudo", "-n", HELPER, "check"], 10).returncode == 0
        except OSError:
            return False
