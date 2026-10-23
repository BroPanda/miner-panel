"""Автопідбір на змодельованій карті: хешрейт насичується з частотою, споживання росте — має знайти найкращу точку."""
from app.core.tuner import MEASURE, SETTLE, Phase, Tuner


def card(core):
    """Ефективність має чіткий пік біля 1600 МГц (різниця між сусідніми точками більша за шум 0,5 %)."""
    hr = 48e12 * (1 - ((core - 1600) / 600) ** 2)
    draw = 100 + 0.02 * (core - 1600)
    return hr, draw


def run(tuner, temp_of=lambda c: 60):
    applied = []
    tuner.apply = lambda pl, c, m, mo: applied.append(c)
    t = 0.0
    tuner.start(now=t)
    while not tuner.done and t < 50000:
        t += 2
        hr, draw = card(tuner.current)
        tuner.step(temp_of(tuner.current), 75, hr, draw, now=t)
    return applied


def test_efficiency_finds_peak():
    tu = Tuner([Phase(["eff", "effNight"], None, "ЕКОНОМНИЙ")], 1500, 1900, 150, 0, 0, lambda hr: 0, lambda *a: None)
    applied = run(tu)
    assert tu.done and tu.result
    ph, best, pl = tu.result[0]
    # Знайдена точка не гірша за найкращу виміряну більш ніж на шум вимірювань (0,5 %), і пік поруч
    scores = {c: card(c)[0] / card(c)[1] for c in set(applied)}
    assert scores[best["core"]] >= max(scores.values()) * 0.995
    assert abs(best["core"] - 1575) <= 50
    assert pl == int(-(-card(best["core"])[1] * 1.15 // 1))


def test_profit_two_phases_and_cache():
    price = 101.45 / 1e12 * 0.0157   # ₴ за H/s на годину (умовно)
    tu = Tuner([Phase(["profitDay"], 4.32, "ДЕНЬ"), Phase(["profitNight"], 2.16, "НІЧ")], 1500, 1900, 150, 0, 0,
               lambda hr: hr * price, lambda *a: None)
    run(tu)
    assert tu.done and len(tu.result) == 2
    day, night = tu.result[0][1]["core"], tu.result[1][1]["core"]
    assert night >= day                       # дешевше світло — вигідніше швидше
    assert any("з попереднього виміру" in x for x in tu.log)


def test_overheat_caps_search():
    tu = Tuner([Phase(["eff"], None, "ЕКОНОМНИЙ")], 1700, 1900, 150, 0, 0, lambda hr: 0, lambda *a: None)
    run(tu, temp_of=lambda c: 80 if c >= 1700 else 60)
    assert tu.hot_cap == 1700 and all(r[1]["core"] < 1700 for r in tu.result)
