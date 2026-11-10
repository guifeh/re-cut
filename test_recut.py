import datetime as dt
import json
import sys
import types
from pathlib import Path

import pytest

from recut import (agentes_disponiveis, agrupar_palavras, aplicar_regra, carregar_estrategia, carregar_template,
                   comandos_crop, cor_ass, energia_relativa, extrair_json, filtro_video, legenda_ass, no_horario,
                   baixar, limpar_legendas, marcar, marcar_erro, normalizar_template, PREFIXO_EVENTO, recorte_vertical, slug, suavizar_trajetoria, ts_ass)


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
    assert [(c["inicio"], c["nota"]) for c in aplicar_regra(cortes, 300, 6, 15, 90, 2)[0]] == [(40, 9), (0.0, 7)]


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
    assert agentes_disponiveis(which=instalados.get) == [("codex", "/bin/codex"), ("claude", "/bin/claude")]
    assert agentes_disponiveis("claude", instalados.get)[0] == ("claude", "/bin/claude")
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


def test_limpar_momentos():
    from recut import limpar_momentos
    brutos = [{"t": 12, "tipo": "risada", "intensidade": 5, "emoji": "😂{x}"},   # intensidade presa em 3, chaves fora
              {"t": 12.8, "tipo": "reacao", "intensidade": 1, "emoji": "😱"},  # colado e mais fraco: sai
              {"t": 99, "tipo": "risada", "intensidade": 2, "emoji": ""},      # fora do corte
              {"t": 15, "tipo": "meme", "intensidade": 2, "emoji": ""},        # tipo inválido
              {"tipo": "enfase"},                                              # sem t
              {"t": 20, "tipo": "enfase", "intensidade": 2, "emoji": "🔥"}]
    assert limpar_momentos(brutos, 10, 30) == [{"t": 12.0, "tipo": "risada", "intensidade": 3, "emoji": "😂x"},
                                               {"t": 20.0, "tipo": "enfase", "intensidade": 2, "emoji": "🔥"}]
    assert limpar_momentos(None, 0, 10) == []


def test_plano_efeitos():
    from recut import plano_efeitos
    ms = [{"t": 12.0, "tipo": "punchline", "intensidade": 3, "emoji": "😂"},
          {"t": 20.0, "tipo": "risada", "intensidade": 1, "emoji": "🤣"}]
    assert plano_efeitos(ms, normalizar_template({}), 10) == []  # efeitos desligados por padrão
    tpl = normalizar_template({"efeitos": {"ativo": True, "intensidade_min": 2}})
    assert [(t, e) for t, e, _ in plano_efeitos(ms, tpl, 10)] == [(2.0, "zoom"), (2.0, "som")]  # risada fraca não entra
    with pytest.raises(ValueError):
        normalizar_template({"efeitos": {"regras": {"risada": ["explosao"]}}})
    with pytest.raises(ValueError):
        normalizar_template({"efeitos": {"sons": {"risada": "../../segredo"}}})


def test_efeitos_no_filtro():
    from recut import expr_zoom, filtro_audio
    tpl = normalizar_template({"efeitos": {"ativo": True}})
    assert expr_zoom([2.0], 1.3) == r"1+0.300*min(1\,clip((it-1.94)/0.08\,0\,1)*clip((2.90-it)/0.2\,0\,1))"
    v = filtro_video(tpl, 1920, 1080, "c1", x=100, zooms=[(2.0, 0.6, 0.3)], flashes=[6.0], com_emoji=True)
    assert ",fps=30,zoompan=" in v and r"between(t\,6.00\,6.06)" in v
    # a mira vale a âncora do rosto perto do momento e o centro fora dele
    assert r"iw*(0.5+0.100*between(it\,1.85\,3.20))" in v and r"ih*(0.45-0.150*between(it\,1.85\,3.20))" in v
    assert v.index("zoompan") < v.index("drawbox") < v.index("subtitles=")  # efeitos antes da legenda
    assert "zoompan" not in filtro_video(tpl, 1920, 1080, "c1")
    assert filtro_audio([], 1, 1) is None
    a = filtro_audio([2.0, 6.5], 2, 1.1)
    assert "[2:a]aresample=44100,adelay=2000:all=1" in a and "[3:a]aresample=44100,adelay=6500:all=1" in a
    assert a.endswith("amix=inputs=3:normalize=0:duration=first,atempo=1.1,alimiter=limit=0.95[aout]")


def test_ancora_zoom_mira_o_rosto_no_quadro_final():
    from recut import ancora_zoom
    xs, ys = [None, 900, 960, None], [None, 0.3, 0.32, None]
    # recorte de 606px começando em 657: rosto em x=960 fica no meio do quadro, na altura em que está
    assert ancora_zoom(1.0, xs, ys, 0.5, 1920, 1080, 1080, 1920, "centro", 657) == (0.5, 0.32)
    # vídeo inteiro encaixado (ajustar): a altura do rosto é convertida para dentro da faixa do meio
    assert ancora_zoom(1.0, xs, ys, 0.5, 1920, 1080, 1080, 1920, "ajustar") == (0.5, 0.443)
    # sem rosto perto do momento: centro, um pouco acima
    assert ancora_zoom(9.0, xs, ys, 0.5, 1920, 1080, 1080, 1920, "centro", 657) == (0.5, 0.45)
    # rosto fora do recorte fica preso na borda
    assert ancora_zoom(0.5, xs, ys, 0.5, 1920, 1080, 1080, 1920, "centro", 0)[0] == 1


def test_sons_por_categoria(tmp_path, monkeypatch):
    import recut
    monkeypatch.setattr(recut, "SONS", tmp_path)
    monkeypatch.setattr(recut, "SONS_PADRAO", {})  # não gera nada no teste
    (tmp_path / "comedia").mkdir()
    (tmp_path / "comedia" / "risada-1.wav").write_bytes(b"x")
    (tmp_path / "solto.mp3").write_bytes(b"x")
    (tmp_path / "Nome Invalido.wav").write_bytes(b"x")  # o template não aceitaria: não aparece
    assert recut.listar_sons() == [{"id": "comedia/risada-1", "categoria": "comedia", "nome": "risada-1"},
                                  {"id": "solto", "categoria": "geral", "nome": "solto"}]
    assert recut.arquivo_som("comedia/risada-1") == tmp_path / "comedia" / "risada-1.wav"
    assert recut.arquivo_som("../segredo") is None and recut.arquivo_som("") is None
    t = normalizar_template({"efeitos": {"sons": {"risada": "comedia/risada-1"}}})
    assert t["efeitos"]["sons"]["risada"] == "comedia/risada-1"
    assert t["efeitos"]["sons"]["virada"] == "transicao/whoosh"  # sons parcial mescla com o padrão
    for ruim in ("a/b/c", "../x", "Comedia/X"):
        with pytest.raises(ValueError):
            normalizar_template({"efeitos": {"sons": {"risada": ruim}}})


def test_emoji_vira_figurinha_na_legenda():
    tpl = normalizar_template({"efeitos": {"ativo": True}})
    plano = [(4.0, "emoji", {"emoji": "😂"}), (8.0, "zoom", {"emoji": "🔥"})]
    linhas = [l for l in legenda_ass([], 10, 30, tpl, "", plano).splitlines() if ",Emoji," in l]
    assert len(linhas) == 1 and linhas[0].startswith("Dialogue: 2,0:00:04.00,0:00:05.30,Emoji") and linhas[0].endswith("😂")


def test_marcar_emite_linha_json(capsys):
    marcar("transcrever", "progresso", "lote_0003", progresso=0.62, msg="Transcrevendo lote 3")
    linha = capsys.readouterr().out.strip()
    assert linha.startswith(PREFIXO_EVENTO)
    ev = json.loads(linha[len(PREFIXO_EVENTO):])
    assert ev["etapa"] == "transcrever" and ev["estado"] == "progresso" and ev["item"] == "lote_0003"
    assert ev["progresso"] == 0.62 and "t" in ev


def test_legendas_completa_e_corta():
    assert limpar_legendas({"legendas": ["a", "", "b", "c"], "descricao": "d", "titulo": "t"}) == ["a", "b", "c"]
    assert limpar_legendas({"descricao": "d", "titulo": "t"}) == ["d", "t", "t"]
    assert len(limpar_legendas({"legendas": ["x" * 3000], "descricao": "d", "titulo": "t"})[0]) == 2200


def _eventos(out):
    return [json.loads(l[len(PREFIXO_EVENTO):]) for l in out.splitlines() if l.startswith(PREFIXO_EVENTO)]


def test_erro_fecha_o_item_aberto(capsys):
    marcar("transcrever", "inicio", "x")
    marcar_erro(RuntimeError("falhou"))
    ev = _eventos(capsys.readouterr().out)[-1]
    assert (ev["etapa"], ev["estado"], ev["item"], ev["msg"]) == ("transcrever", "erro", "x", "falhou")


def test_comando_gravacao_live_separa_video_e_audio(tmp_path):
    import recut
    info = {"requested_formats": [
        {"url": "https://video.test/live.m3u8", "http_headers": {"User-Agent": "teste"}},
        {"url": "https://audio.test/live.m3u8"},
    ]}
    cmd = recut.comando_gravacao_live(info, tmp_path, 3)
    assert [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-i"] == [
        "https://video.test/live.m3u8", "https://audio.test/live.m3u8"]
    assert [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-map"] == [
        "0:v:0?", "0:a:0?", "1:v:0?", "1:a:0?"]
    assert "User-Agent: teste\r\n" in cmd
    assert cmd[cmd.index("-segment_start_number") + 1] == "3"


def test_comando_gravacao_live_url_unica(tmp_path):
    import recut
    cmd = recut.comando_gravacao_live({"url": "https://stream.test/live.m3u8"}, tmp_path, 0)
    assert cmd.count("-i") == 1
    assert cmd[cmd.index("-i") + 1] == "https://stream.test/live.m3u8"
    assert cmd[-1] == str(tmp_path / "lote_%04d.ts")


def test_baixar_usa_o_mesmo_item(monkeypatch, tmp_path, capsys):
    class YDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def extract_info(self, url):
            self.opts["progress_hooks"][0]({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100})
            return {"requested_downloads": [{"filepath": str(tmp_path / "fonte.mp4")}]}

    monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=YDL))
    baixar("http://x", tmp_path)
    evs = _eventos(capsys.readouterr().out)
    assert [e["estado"] for e in evs] == ["inicio", "progresso", "fim"]
    assert {e["item"] for e in evs} == {"fonte"}


def test_processar_marca_ranking_depois_de_renderizar(monkeypatch, tmp_path, capsys):
    import recut
    monkeypatch.setattr(recut, "transcrever", lambda v: ([(0, 30, "oi")], [[0, 1, "oi"]]))
    monkeypatch.setattr(recut, "rms_por_segundo", lambda v: [1.0] * 60)
    monkeypatch.setattr(recut, "escolher_cortes", lambda *a: [])
    monkeypatch.setattr(recut, "aplicar_regra", lambda *a: ([{"inicio": 0, "fim": 20, "nota": 8, "titulo": "t"}], "regra"))
    monkeypatch.setattr(recut, "renderizar", lambda *a: None)
    cfg = {"nota_min": 6, "dur_min": 15, "dur_max": 90, "limite": 10, "template": {"nome": "p", "velocidade": 1}}
    recut.processar(tmp_path / "lote_0000.ts", tmp_path, "lote_0000", cfg)
    passos = [(e["etapa"], e["estado"]) for e in _eventos(capsys.readouterr().out)]
    assert passos[-3:] == [("renderizar", "progresso"), ("renderizar", "fim"), ("ranking", "fim")]


def test_aplicar_regra_explica_os_descartes():
    sugeridos = [{"inicio": 0, "fim": 20, "nota": 9}, {"inicio": 30, "fim": 50, "nota": 7},
                 {"inicio": 60, "fim": 65, "nota": 8}, {"inicio": 70, "fim": 90, "nota": 4}]
    assert aplicar_regra(sugeridos, 300, 6, 15, 90, 1)[1] == (
        "IA sugeriu 4, ficaram 1 (descartados: 1 com nota abaixo de 6, 1 fora de 15-90s, 1 acima do limite de 1)")
    assert aplicar_regra(sugeridos[:1], 300, 6, 15, 90, 1)[1] == "IA sugeriu 1, ficaram 1"


# ---------- layout de jogo (facecam em cima, personagem embaixo) ----------

from recut import achar_facecam, ancora_gameplay, caixa_facecam, filtro_gameplay, paineis_gameplay, trechos_facecam


def test_achar_facecam_prefere_rosto_parado_no_canto():
    iw, ih = 1920, 1080
    cam = (100, 60, 200, 200)  # facecam no canto superior esquerdo, sempre no mesmo lugar
    amostras = []
    for i in range(20):
        rostos = [cam] if i % 4 else []  # o detector falha às vezes
        rostos.append((600 + i * 40, 400, 150, 150))  # personagem andando pela tela
        amostras.append(rostos)
    fc = achar_facecam(amostras, iw, ih)
    assert fc and abs(fc["cx"] - 200) < 1 and abs(fc["cy"] - 160) < 1
    assert len(fc["amostras"]) == 15


def test_achar_facecam_ignora_camera_em_tela_cheia_e_vazio():
    assert achar_facecam([[]] * 10, 1920, 1080) is None
    assert achar_facecam([[(700, 100, 500, 500)]] * 10, 1920, 1080) is None  # rosto enorme: câmera em tela cheia


def test_trechos_facecam_preenche_buracos_e_descarta_piscadas():
    # 0-10s presente com buraco de 2s, sumida até 25s, uma piscada isolada aos 20s
    indices = [i for i in range(21) if not 8 <= i <= 11] + [40]
    assert trechos_facecam(indices, 60, 0.5) == [(0.0, 10.25)]
    assert trechos_facecam(list(range(60)), 60, 0.5) == [(0.0, 30.0)]
    assert trechos_facecam([], 60, 0.5) == []


def test_caixa_facecam_fica_dentro_do_quadro_na_proporcao():
    x, y, w, h = caixa_facecam(150, 100, 200, 1920, 1080, 1080 / 672)
    assert x == 0 and y == 0 and w % 2 == 0 and h % 2 == 0
    assert abs(w / h - 1080 / 672) < 0.02


def test_filtro_gameplay_alterna_layout_pelos_trechos():
    sem_cam = filtro_gameplay(1920, 1080, 1080, 1920)
    assert sem_cam.startswith("[0:v]crop=606:1080:657:0") and "vstack" not in sem_cam
    sempre = filtro_gameplay(1920, 1080, 1080, 1920, (0, 0, 400, 248), [(0.0, 30.0)], 30.0)
    assert "vstack" in sempre and "overlay" not in sempre
    parte = filtro_gameplay(1920, 1080, 1080, 1920, (0, 0, 400, 248), [(0.0, 10.0), (20.0, 30.0)], 30.0)
    assert "enable='between(t\,0.00\,10.00)+between(t\,20.00\,30.00)'" in parte
    assert filtro_gameplay(1080, 1920, 1080, 1920) is None  # fonte vertical: não há o que dividir


def test_ancora_gameplay_reacao_mira_a_facecam():
    hf, hg = paineis_gameplay(1920)
    assert hf + hg == 1920
    assert ancora_gameplay(5, "reacao", [(0, 10)], 1920) == (0.5, round(hf / 2 / 1920, 3))
    assert ancora_gameplay(5, "enfase", [(0, 10)], 1920)[1] > 0.5
    assert ancora_gameplay(15, "reacao", [(0, 10)], 1920) == (0.5, 0.5)
