"""Зсув частоти відеопам'яті через NVAPI (nvapi64.dll) — порт lib\\NvApi.ps1 на ctypes.
GetPstates20 / SetPstates20: зсув для P0 (основного режиму) у МГц, тих самих, що показує nvidia-smi.
Формат структури перевірено на реальній RTX 3060 (P0, domain 4 = пам'ять). Встановлення — лише з правами адміністратора."""
from __future__ import annotations

import ctypes
import struct
from ...i18n import tr

SIZE = 0x1CF8          # NV_GPU_PERF_PSTATES20_INFO_V2
VERSION = 0x21CF8
HEADER, PSTATE_SIZE, CLOCK_SIZE = 20, 456, 44
MEM_DOMAIN = 4         # NVAPI_GPU_PUBLIC_CLOCK_MEMORY

_dll = None


def _fn(fid: int, restype, *argtypes):
    global _dll
    if _dll is None:
        _dll = ctypes.CDLL("nvapi64.dll")
        _dll.nvapi_QueryInterface.restype = ctypes.c_void_p
        _dll.nvapi_QueryInterface.argtypes = [ctypes.c_uint]
    p = _dll.nvapi_QueryInterface(fid)
    if not p:
        raise OSError("NVAPI function not found")
    return ctypes.CFUNCTYPE(restype, *argtypes)(p)


def _gpu(index: int = 0) -> ctypes.c_void_p:
    r = _fn(0x0150E828, ctypes.c_int)()
    if r != 0:
        raise OSError(f"NvAPI_Initialize: {r}")
    handles = (ctypes.c_void_p * 64)()
    n = ctypes.c_int(0)
    r = _fn(0xE5AC921F, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p * 64), ctypes.POINTER(ctypes.c_int))(ctypes.byref(handles), ctypes.byref(n))
    if r != 0 or index >= n.value:
        raise OSError(f"NVIDIA GPU {index} not found")
    return handles[index]


def _buf() -> ctypes.Array:
    b = ctypes.create_string_buffer(SIZE)
    struct.pack_into("<I", b, 0, VERSION)
    return b


def read(index: int = 0) -> dict | None:
    """Поточний зсув пам'яті в P0 і межі драйвера, МГц: {offset, min, max, base} або None."""
    try:
        b = _buf()
        r = _fn(0x6FF81213, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)(_gpu(index), ctypes.addressof(b))
        if r != 0:
            return None
        np_, nc = struct.unpack_from("<ii", b, 8)
        for p in range(np_):
            po = HEADER + p * PSTATE_SIZE
            if struct.unpack_from("<i", b, po)[0] != 0:
                continue
            for c in range(nc):
                co = po + 8 + c * CLOCK_SIZE
                if struct.unpack_from("<i", b, co)[0] != MEM_DOMAIN:
                    continue
                off, mn, mx = struct.unpack_from("<iii", b, co + 12)
                base = struct.unpack_from("<i", b, co + 28)[0]
                # Ділення з відкиданням дробової частини до нуля — як у C#-версії (зсув буває від'ємним)
                return {"offset": int(off / 1000), "min": int(mn / 1000), "max": int(mx / 1000), "base": int(base / 1000)}
    except OSError:
        return None
    return None


def set_offset(mhz: int, index: int = 0) -> str | None:
    """Встановлює зсув пам'яті в P0; None — успіх, інакше текст помилки."""
    try:
        b = _buf()
        struct.pack_into("<iii", b, 8, 1, 1, 0)       # numPstates, numClocks, numBaseVoltages
        po = HEADER
        struct.pack_into("<i", b, po, 0)              # P0
        co = po + 8
        struct.pack_into("<i", b, co, MEM_DOMAIN)     # domainId
        struct.pack_into("<i", b, co + 12, int(mhz) * 1000)   # freqDelta_kHz.value
        r = _fn(0x0F4DAE6B, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)(_gpu(index), ctypes.addressof(b))
    except OSError as e:
        return str(e)
    if r == 0:
        return None
    if r == -137:
        return tr('NVAPI: потрібні права адміністратора')
    return tr('NVAPI: код {0}').format(r)
