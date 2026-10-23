import datetime as dt
from pathlib import Path

import pytest

from recut import (agentes_disponiveis, agrupar_palavras, aplicar_regra, carregar_estrategia, carregar_template,
                   comandos_crop, cor_ass, energia_relativa, extrair_json, filtro_video, legenda_ass, no_horario,
                   normalizar_template, recorte_vertical, slug, suavizar_trajetoria, ts_ass)


def test_ts_ass():
    assert ts_ass(0) == "0:00:00.00"
    assert ts_ass(3725.5) == "1:02:05.50"


def test_legenda_relativa_ao_corte_e_em_blocos():
    palavras = [(10.0, 10.4, "oi"), (10.4, 10.8, "{gente}"), (10.8, 11.2, "hoje"), (11.2, 11.6, "tem"), (50, 51, "fora")]
    linhas = [l for l in legenda_ass(palavras, 10.0, 20.0).splitlines() if l.startswith("Dialogue")]
    assert [l.split(",")[1:3] for l in linhas] == [["0:00:00.00", "0:00:01.20"], ["0:00:01.20", "0:00:01.60"]]
    assert linhas[0].endswith("}OI (GENTE) HOJE") and linhas[1].endswith("}TEM")  # chaves escapadas, maiúsculas
    assert "PlayResY: 1920" in legenda_ass(palavras, 10, 20)


def test_agrupar_palavras():
    ws = [(0, 0.3, "a"), (0.3, 0.6, "b."), (0.6, 0.9, "c"), (2.0, 2.3, "d"), (2.3, 2.6, "e"), (2.6, 2.9, "f"), (2.9, 3.2, "g")]
    grupos = agrupar_palavras(ws, por_grupo=3, pausa_max=0.5, pontuacao=True)
    assert [[w[2] for w in g] for g in grupos] == [["a", "b."], ["c"], ["d", "e", "f"], ["g"]]  # ponto, pausa, limite
    assert len(agrupar_palavras(ws, 3, 5, False)[0]) == 3


def test_cor_ass():
    assert cor_ass("#FFD700") == "&H0000D7FF"  # RGB -> BGR com alfa
    assert cor_ass("#000000", 70) == "&H4C000000"


def test_destaque_titulo_e_velocidade():
    tpl = normalizar_template({"velocidade": 2, "legenda": {"destaque": True, "maiusculas": False},
                               "titulo": {"ativo": True, "segundos": 3}})
    ass = legenda_ass([(10, 11, "oi"), (11, 12, "tudo")], 10, 30, tpl, "Meu título")
    linhas = [l for l in ass.splitlines() if l.startswith("Dialogue")]
    assert linhas[0].startswith("Dialogue: 1,0:00:00.00,0:00:03.00,Titulo") and linhas[0].endswith("Meu título")
    # 2 palavras = 2 eventos, cada um com uma palavra pintada; tempos divididos pela velocidade
    assert linhas[1].split(",")[1:3] == ["0:00:00.00", "0:00:00.50"] and "{\\c&H0000D7FF}oi" in linhas[1]
    assert linhas[2].split(",")[1:3] == ["0:00:00.50", "0:00:01.00"] and "{\\c&H0000D7FF}tudo" in linhas[2]


def test_normalizar_template():
    t = normalizar_template({"nome": "Meu Template!", "legenda": {"cor": "#00FF00", "inexistente": 1}, "lixo": 2})
    assert t["nome"] == "meu-template" and t["legenda"]["cor"] == "#00FF00" and t["legenda"]["tamanho"] == 84
    assert "inexistente" not in t["legenda"] and "lixo" not in t
    for ruim in ({"proporcao": "3:2"}, {"legenda": {"cor": "vermelho"}}, {"legenda": {"fonte": "Montserrat"}},
                 {"velocidade": 5}, {"legenda": {"tamanho": "grande"}}, {"legenda": {"tamanho": "84\n"}},
                 {"legenda": {"contorno": "6,0\nDialogue: 0,0:00:00.00,0:00:09.00,Legenda,,0,0,0,,X"}},
                 {"legenda": {"pausa_max": "x"}}, {"titulo": {"segundos": None}}, {"legenda": {"negrito": "sim"}},
                 {"legenda": {"tamanho": True}}):
        with pytest.raises(ValueError):
            normalizar_template(ruim)


def test_templates_do_repo_sao_validos():
    arquivos = list(Path(__file__).with_name("templates").glob("*.json"))
    assert arquivos
    for f in arquivos:
        assert carregar_template(f.stem)["nome"] == f.stem


def test_filtro_video():
    base = normalizar_template({})
    assert "sendcmd=f=c1.cmd,crop@rosto=606:1080:300:0" in filtro_video(base, 1920, 1080, "c1", x=300, seguir=True)
    assert "crop=606:1080:100:0,scale=1080:1920" in filtro_video(base, 1920, 1080, "c1", x=100)
    assert "crop=606:1080:657:0" in filtro_video(base, 1920, 1080, "c1")  # sem rosto: centro
    ajustar = filtro_video(normalizar_template({"enquadramento": "ajustar"}), 1920, 1080, "c1")
    assert "boxblur" in ajustar and ajustar.endswith("[out]")
    quadrado = filtro_video(normalizar_template({"proporcao": "1:1", "enquadramento": "centro"}), 1920, 1080, "c1")
    assert "crop=1080:1080:420:0,scale=1080:1080" in quadrado
    rapido = filtro_video(normalizar_template({"velocidade": 1.25}), 1920, 1080, "c1")
    assert rapido.index("setpts=PTS/1.25") < rapido.index("subtitles=")  # legenda depois do ajuste de tempo
    logo = filtro_video(normalizar_template({"logo": {"posicao": "base-esquerda"}}), 1920, 1080, "c1", com_logo=True)
    assert logo.endswith("[1:v]scale=194:-1[lg];[v][lg]overlay=40:H-h-40[out]")
    sem_legenda = normalizar_template({"legenda": {"ativa": False}})
    assert "subtitles" not in filtro_video(sem_legenda, 1920, 1080, "c1")


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


def test_legenda_nao_pisca_em_pausa_curta():
    ws = [(0, 0.4, "um"), (0.4, 0.8, "dois."), (1.0, 1.4, "tres"), (5.0, 5.4, "quatro")]
    linhas = [l.split(",")[1:3] for l in legenda_ass(ws, 0, 10).splitlines() if l.startswith("Dialogue")]
    assert linhas == [["0:00:00.00", "0:00:01.00"],  # pausa de 0.2s: segura até "tres"
                      ["0:00:01.00", "0:00:01.40"],  # pausa de 3.6s: some
                      ["0:00:05.00", "0:00:05.40"]]


def test_publico_tira_campos_internos():
    from recut import publico
    c = {"arquivo": "a.mp4", "nota": 7, "fonte": "C:/x/fonte.mp4", "palavras": [[0, 1, "oi"]]}
    assert publico(c) == {"arquivo": "a.mp4", "nota": 7}


def test_atualizar_indices_reconstroi_do_disco(tmp_path):
    import json
    from recut import atualizar_indices
    def corte(nome, nota, template):
        (tmp_path / f"{nome}.json").write_text(json.dumps(
            {"arquivo": f"{nome}.mp4", "nota": nota, "template": template, "fonte": "C:/x.ts", "palavras": []}))
    corte("lote_0000_corte01", 6, "caixa")   # reaplicado: o índice ainda diz "classico"
    corte("lote_0001_corte01", 9, "classico")  # gravado pela live depois: ainda fora do índice
    (tmp_path / "cortes.json").write_text(json.dumps(
        {"titulo": "live", "cortes": [{"arquivo": "lote_0000_corte01.mp4", "nota": 6, "template": "classico"}]}))
    atualizar_indices(tmp_path)
    dados = json.loads((tmp_path / "cortes.json").read_text())
    assert dados["titulo"] == "live"
    assert [(c["arquivo"], c["template"]) for c in dados["cortes"]] == [
        ("lote_0001_corte01.mp4", "classico"), ("lote_0000_corte01.mp4", "caixa")]
    assert all("fonte" not in c and "palavras" not in c for c in dados["cortes"])
    assert not list(tmp_path.glob(".*.tmp"))  # gravação atômica não deixa lixo


def test_atualizar_indices_nao_derruba_a_live(tmp_path, capsys):
    import json
    from recut import atualizar_indices
    (tmp_path / "lote_0000_corte01.json").write_text('{"arquivo": "a.mp4", "no')  # gravação pela metade
    atualizar_indices(tmp_path, {"titulo": "live"})  # não levanta: só avisa e o próximo lote refaz
    assert "índice não atualizado" in capsys.readouterr().err
    (tmp_path / "lote_0000_corte01.json").write_text(json.dumps({"arquivo": "a.mp4", "nota": 7}))
    atualizar_indices(tmp_path, {"titulo": "live"})  # primeira gravação da live cria o índice com o cabeçalho
    assert json.loads((tmp_path / "cortes.json").read_text())["cortes"] == [{"arquivo": "a.mp4", "nota": 7}]
