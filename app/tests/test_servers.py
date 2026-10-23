"""Вибір сервера пулу: не перемикатися через разові коливання, але перейти на стабільно швидший; ліг — одразу інший."""
from app.core import servers as sv

DE, FI, US = "de.pearl.herominers.com:1200", "fi.pearl.herominers.com:1200", "us.pearl.herominers.com:1200"
URLS = [DE, FI, US]


def feed(sel, rows):
    for r in rows:
        sel.add(dict(zip(URLS, r)))


def test_single_better_check_does_not_switch():
    s = sv.Selector()
    feed(s, [(None, 45, 140)] * 5 + [(28, 45, 140)])       # de щойно піднявся: один вимір
    assert s.decide(URLS, FI, started_at=0, now=10_000) is None


def test_sustained_better_switches_back_to_de():
    s = sv.Selector()
    feed(s, [(28, 45, 140)] * 6)
    d = s.decide(URLS, "stratum+tcp://fi.pearl.herominers.com:1200", started_at=0, now=10_000)
    assert d and d["url"] == DE


def test_real_numbers_de_returns():
    # Виміряно 21.10: de 36 мс, fi 46 мс — після 30 хв стабільної різниці повертаємось на de
    s = sv.Selector()
    feed(s, [(36, 46, 172), (37, 45, 170), (35, 47, 171), (36, 46, 175), (38, 46, 172), (36, 45, 173)])
    assert s.decide(URLS, FI, started_at=0, now=10_000)["url"] == DE


def test_small_gain_ignored():
    s = sv.Selector()
    feed(s, [(40, 45, 140)] * 6)                          # лише на 5 мс краще
    assert s.decide(URLS, FI, started_at=0, now=10_000) is None


def test_flaky_server_ignored():
    s = sv.Selector()
    feed(s, [(28, 45, 140), (None, 45, 140)] * 3)         # 50 % втрат
    assert s.decide(URLS, FI, started_at=0, now=10_000) is None


def test_rate_limit_and_grace():
    s = sv.Selector()
    feed(s, [(28, 45, 140)] * 6)
    assert s.decide(URLS, FI, started_at=9_800, now=10_000) is None      # щойно стартував
    s.switched(now=9_000)
    assert s.decide(URLS, FI, started_at=0, now=10_000) is None          # недавно перемикались
    assert s.decide(URLS, FI, started_at=0, now=9_000 + sv.MIN_SWITCH_S + 1)


def test_order_when_server_down():
    s = sv.Selector()
    feed(s, [(28, 45, 140)] * 3 + [(None, 46, 140)])
    assert s.order(URLS, now=0)[0] == FI                  # de не відповідає — першим швидший живий
    s2 = sv.Selector()
    feed(s2, [(28, 45, 140)] * 3)
    s2.mark_bad(DE, now=0)
    assert s2.order(URLS, now=10)[0] == DE                # два вдалі виміри поспіль після «поганий» — знову живий
    s3 = sv.Selector()
    feed(s3, [(None, 45, 140), (28, 45, 140)])
    s3.mark_bad(DE, now=0)
    assert s3.order(URLS, now=10)[0] == FI


def test_real_probe_runs():
    r = sv.probe(["127.0.0.1:9"])                         # закритий порт — не падає, повертає None
    assert r["127.0.0.1:9"] is None
