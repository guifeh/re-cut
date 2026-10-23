import datetime as dt
from pathlib import Path

from recut import agentes_disponiveis, aplicar_regra, comandos_crop, extrair_json, suavizar_trajetoria, carregar_estrategia, energia_relativa, legenda_ass, no_horario, recorte_vertical, slug, ts_ass


def test_ts_ass():
    assert ts_ass(0) == "0:00:00.00"
    assert ts_ass(3725.5) == "1:02:05.50"


def test_legenda_relativa_ao_corte_e_em_blocos():
    palavras = [(10.0, 10.4, "oi"), (10.4, 10.8, "{gente}"), (10.8, 11.2, "hoje"), (11.2, 11.6, "tem"), (50, 51, "fora")]
    linhas = [l for l in legenda_ass(palavras, 10.0, 20.0).splitlines() if l.startswith("Dialogue")]
    assert linhas == [
        "Dialogue: 0,0:00:00.00,0:00:01.20,Default,,0,0,0,,OI (GENTE) HOJE",
        "Dialogue: 0,0:00:01.20,0:00:01.60,Default,,0,0,0,,TEM",
    ]


def test_recorte_vertical():
    assert recorte_vertical(960, 1920, 1080) == (657, 606)  # centralizado
    assert recorte_vertical(0, 1920, 1080) == (0, 606)  # rosto na borda esquerda
    assert recorte_vertical(1920, 1920, 1080) == (1314, 606)  # borda direita
    assert recorte_vertical(540, 1080, 1920) is None  # já vertical


def test_energia_relativa():
    assert energia_relativa([1, 1, 1, 4, 4], 3, 5) == 4


def test_aplicar_regra():
    cortes = [
        {"inicio": -5, "fim": 30, "nota": 7},  # início negativo é corrigido
        {"inicio": 100, "fim": 200, "nota": 9.5},  # longo demais
        {"inicio": 40, "fim": 60, "nota": 9},
        {"inicio": 60, "fim": 80, "nota": 4},  # nota baixa
        {"inicio": 80, "fim": 100, "nota": 6.5},
    ]
    assert [(c["inicio"], c["nota"]) for c in aplicar_regra(cortes, 300, 6, 15, 90, 2)] == [(40, 9), (0.0, 7)]


def test_no_horario():
    sexta_20h = dt.datetime(2026, 10, 23, 20)
    assert no_horario(sexta_20h, set(), set())
    assert no_horario(sexta_20h, {5}, {20, 21})
    assert not no_horario(sexta_20h, {6, 7}, set())
    assert not no_horario(sexta_20h, set(), {18})


def test_carregar_estrategia():
    pasta = Path(__file__).with_name("estrategias")
    assert carregar_estrategia("reacoes", pasta).startswith("Foque em reações")
    assert carregar_estrategia("foque em humor", pasta) == "foque em humor"
    assert carregar_estrategia("", pasta) == ""


def test_slug():
    assert slug("Gaules TV!") == "gaules-tv"


def test_agentes_disponiveis():
    instalados = {"claude": "/bin/claude", "codex": "/bin/codex"}
    assert agentes_disponiveis(which=instalados.get) == [("claude", "/bin/claude"), ("codex", "/bin/codex")]
    assert agentes_disponiveis("codex", instalados.get)[0] == ("codex", "/bin/codex")
    assert agentes_disponiveis("xyz", {"codex": "/bin/codex"}.get) == [("codex", "/bin/codex")]


def test_extrair_json():
    assert extrair_json('{"cortes": []}') == {"cortes": []}
    assert extrair_json('Aqui está:\n```json\n{"cortes": [{"nota": 8}]}\n```\nAbraço') == {"cortes": [{"nota": 8}]}


def test_suavizar_trajetoria():
    assert suavizar_trajetoria([None, None], 960) == [960, 960]  # sem rosto: centro
    parado = suavizar_trajetoria([500, 510, 495, 1800, 505, 500], 960, zona_morta=40)
    assert parado == [500] * 6  # jitter fica na zona morta e o falso positivo (1800) some na mediana
    pan = suavizar_trajetoria([500] * 3 + [1300] * 12, 960, zona_morta=40)
    assert pan[0] == 500 and 1250 < pan[-1] <= 1300  # chega ao novo lugar...
    assert all(b - a < 300 for a, b in zip(pan, pan[1:]))  # ...sem saltar
    assert suavizar_trajetoria([None, 700, None], 960) == [700, 700, 700]


def test_comandos_crop():
    linhas = comandos_crop([600, 800], passo=0.5, iw=1920, w=606, hz=10).splitlines()
    assert linhas[0] == "0.00 crop@rosto x 297;" and linhas[-1] == "0.50 crop@rosto x 497;"
    assert len(linhas) == 6
    assert comandos_crop([10, 1900], 0.5, 1920, 606).splitlines()[-1].endswith("x 1314;")  # preso no quadro
    assert {l.split()[-1] for l in comandos_crop([960], 0.5, 1920, 606).splitlines()} == {"657;"}  # 1 amostra: fixo
