import http.client
import json
import threading
import time
import urllib.error
import urllib.request

import pytest

import contas
import publicar
import server
from lixeira import Lixeira

JID = "20261104-100000-abc123"


@pytest.fixture
def servidor(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "RAIZ", tmp_path)
    monkeypatch.setattr(server, "JOBS", tmp_path / "jobs")
    monkeypatch.setattr(server, "UPLOADS", tmp_path / "uploads")
    monkeypatch.setattr(server, "LIXEIRA", tmp_path / "lixeira")
    monkeypatch.setattr(server, "lixeira", Lixeira(tmp_path / "lixeira", tmp_path / "jobs", tmp_path / "uploads"))
    monkeypatch.setattr(contas, "PASTA", tmp_path / "contas")
    job = tmp_path / "jobs" / JID
    job.mkdir(parents=True)
    (job / "job.json").write_text(json.dumps({"id": JID, "entrada": "https://x", "status": "rodando"}))
    (job / "log.txt").write_text('@@ {"etapa": "ia", "estado": "inicio"}\n', encoding="utf-8")
    (job / "fonte_corte01.json").write_text(json.dumps({
        "arquivo": "fonte_corte01.mp4", "thumbnail": "fonte_corte01.jpg", "titulo": "t", "nota": 8,
        "criado_em": "2026-11-04T10:00:00"}))
    (job / "fonte_corte01.mp4").write_bytes(b"v")
    s = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield s.server_address[1]
    s.shutdown()
    s.server_close()
    fim = time.time() + 5
    while server.enviando_agora and time.time() < fim:  # threads de envio dos testes terminam antes do próximo
        time.sleep(0.01)


def pedir(porta, caminho, corpo=None, cabecalhos=None):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    cab = {"Content-Type": "application/json", **(cabecalhos or {})}
    req = urllib.request.Request(f"http://127.0.0.1:{porta}{caminho}", data=dados, headers=cab,
                                 method="POST" if dados else "GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        with e:
            return e.code, json.loads(e.read())


def corte():
    return server.JOBS / JID / "fonte_corte01.json"


APROVAR = f"/api/jobs/{JID}/cortes/aprovar"
PEDIDO = {"json": "fonte_corte01.json", "legenda": "olha isso", "hashtags": ["a", "b"]}


def envio_falso(monkeypatch, liberar=None):
    """Troca publicar.enviar: registra a plataforma e o estado no disco na hora da chamada; espera `liberar`."""
    chamadas = []

    def enviar(corte_json, plataforma, **_):
        estado = publicar.ler_publicacao(corte_json, server.enviando_agora)["plataformas"][plataforma]["estado"]
        chamadas.append((plataforma, estado))
        if liberar:
            liberar.wait(5)
        return publicar._mudar(corte_json, plataforma, "ok", link="https://youtube.com/shorts/x")
    monkeypatch.setattr(publicar, "enviar", enviar)
    return chamadas


def esperar_envios():
    fim = time.time() + 5
    while server.enviando_agora and time.time() < fim:
        time.sleep(0.01)
    assert not server.enviando_agora


def test_esteira_de_job_parado_nao_tem_no_rodando(servidor):
    status, r = pedir(servidor, f"/api/esteira/{JID}")
    assert status == 200
    assert r["esteira"]["nos"]["ia"]["estado"] == "erro"
    assert r["job"]["status"] == "interrompido"
    c = r["job"]["cortes"][0]
    assert c["nome"] == "fonte_corte01" and c["publicacao"] == {}
    assert r["esteira"]["nos"]["aprovacao"]["itens"] == ["fonte_corte01"]


def test_esteira_resumo_do_dia(servidor):
    status, r = pedir(servidor, "/api/esteira/resumo")
    assert status == 200 and set(r) == {"cortes", "aprovados", "postados", "erros"}


def test_aprovar_dispara_envios_e_tiktok_fica_manual(servidor, monkeypatch):
    chamadas = envio_falso(monkeypatch)
    status, r = pedir(servidor, APROVAR, PEDIDO)
    assert status == 200 and r["plataformas"]["tiktok"]["estado"] == "manual"
    esperar_envios()
    assert sorted(p for p, _ in chamadas) == ["instagram", "youtube"]
    pub = publicar.ler_publicacao(corte(), set())
    assert pub["plataformas"]["youtube"]["estado"] == "ok" and pub["plataformas"]["tiktok"]["estado"] == "manual"


def test_aprovar_duas_vezes_so_envia_uma(servidor, monkeypatch):
    liberar = threading.Event()
    chamadas = envio_falso(monkeypatch, liberar)
    assert pedir(servidor, APROVAR, PEDIDO)[0] == 200
    status, r = pedir(servidor, APROVAR, PEDIDO)  # envio ainda rodando
    assert status == 400 and r["erro"]
    liberar.set()
    esperar_envios()
    assert pedir(servidor, APROVAR, PEDIDO)[0] == 400  # já aprovado
    assert len(chamadas) == 2


def test_consulta_logo_depois_de_aprovar_nao_vira_incerto(servidor, monkeypatch):
    liberar = threading.Event()
    chamadas = envio_falso(monkeypatch, liberar)
    original = publicar.aprovar

    def aprovar_e_consultar(*a, **kw):  # uma consulta concorrente cai logo depois da gravação de "enviando"
        r = original(*a, **kw)
        publicar.ler_publicacao(a[0], server.enviando_agora)
        return r
    monkeypatch.setattr(publicar, "aprovar", aprovar_e_consultar)
    assert pedir(servidor, APROVAR, PEDIDO)[0] == 200
    _, r = pedir(servidor, f"/api/esteira/{JID}")
    assert r["job"]["cortes"][0]["publicacao"]["plataformas"]["youtube"]["estado"] == "enviando"
    assert r["esteira"]["nos"]["youtube"]["estado"] == "rodando"
    liberar.set()
    esperar_envios()
    assert sorted(chamadas) == [("instagram", "enviando"), ("youtube", "enviando")]


def test_tentar_de_novo_com_envio_ativo_e_recusado(servidor, monkeypatch):
    liberar = threading.Event()
    chamadas = envio_falso(monkeypatch, liberar)
    pedir(servidor, APROVAR, PEDIDO)
    status, r = pedir(servidor, f"/api/jobs/{JID}/cortes/publicacao",
                      {"json": "fonte_corte01.json", "plataforma": "youtube", "acao": "forcar"})
    assert status == 400 and "enviado" in r["erro"]
    liberar.set()
    esperar_envios()
    assert len(chamadas) == 2


def test_tentar_de_novo_e_link(servidor, monkeypatch):
    chamadas = envio_falso(monkeypatch)
    publicar.aprovar(corte(), "x", [], pasta_contas=contas.PASTA)
    publicar._mudar(corte(), "youtube", "erro", erro="caiu")
    publicar._mudar(corte(), "instagram", "erro", erro="caiu")
    url = f"/api/jobs/{JID}/cortes/publicacao"
    status, r = pedir(servidor, url, {"json": "fonte_corte01.json", "plataforma": "youtube", "acao": "tentar"})
    assert status == 200
    esperar_envios()
    assert chamadas == [("youtube", "enviando")]
    status, r = pedir(servidor, url, {"json": "fonte_corte01.json", "plataforma": "tiktok", "acao": "link",
                                      "link": "https://www.tiktok.com/@a/video/1"})
    assert status == 200 and r["plataformas"]["tiktok"]["estado"] == "ok"
    assert pedir(servidor, url, {"json": "fonte_corte01.json", "plataforma": "tiktok", "acao": "tentar"})[0] == 400
    assert pedir(servidor, url, {"json": "fonte_corte01.json", "plataforma": "youtube", "acao": "x"})[0] == 400
    assert chamadas == [("youtube", "enviando")]


def test_aprovar_corte_de_outro_job_e_400(servidor):
    for pedido in ({**PEDIDO, "json": "../outro/fonte_corte01.json"}, {**PEDIDO, "legenda": ""},
                   {**PEDIDO, "hashtags": "a"}, {**PEDIDO, "hashtags": [1]}):
        assert pedir(servidor, APROVAR, pedido)[0] == 400
    assert not corte().with_suffix(".publicacao").exists() and not server.enviando_agora


def test_api_contas_nao_vaza_segredo(servidor):
    contas.salvar("youtube", {"client_id": "cid", "client_secret": "SEGREDO-1", "access_token": "SEGREDO-2",
                              "refresh_token": "SEGREDO-3", "vence_em": "2999-01-01T00:00:00"}, contas.PASTA)
    with urllib.request.urlopen(f"http://127.0.0.1:{servidor}/api/contas", timeout=5) as r:
        texto = r.read().decode()
    assert "SEGREDO" not in texto
    assert [c["conectada"] for c in json.loads(texto)] == [True, False]
    assert pedir(servidor, "/api/contas/youtube/desconectar", {})[1]["conectada"] is False
    assert contas.ler("youtube", contas.PASTA) == {"client_id": "cid", "client_secret": "SEGREDO-1"}


def test_configurar_e_conectar(servidor):
    status, r = pedir(servidor, "/api/contas/instagram/configurar", {"client_id": "app", "client_secret": "s"})
    assert status == 200 and r["configurada"] and "client_secret" not in r
    status, r = pedir(servidor, "/api/contas/instagram/conectar", {})
    assert status == 200 and r["url"].startswith("https://www.instagram.com/oauth/authorize?")
    assert pedir(servidor, "/api/contas/youtube/conectar", {})[0] == 400  # sem app configurado
    assert pedir(servidor, "/api/contas/tiktok/configurar", {"client_id": "a", "client_secret": "b"})[0] == 400


def redirecionamento(porta, caminho):
    c = http.client.HTTPConnection("127.0.0.1", porta, timeout=5)
    try:
        c.request("GET", caminho)
        r = c.getresponse()
        r.read()
        return r.status, r.getheader("Location")
    finally:
        c.close()


def test_retorno_youtube_redireciona_para_aba_contas(servidor, monkeypatch):
    recebido = []

    def concluir(p, codigo, estado, **kw):
        recebido.append((p, codigo, estado))
        if codigo == "ruim":
            raise ValueError("login do YouTube expirado")
        return {}
    monkeypatch.setattr(contas, "concluir", concluir)
    assert redirecionamento(servidor, "/api/contas/youtube/retorno?code=C1&state=E1") == (302, "/?aba=contas")
    assert recebido == [("youtube", "C1", "E1")]
    status, destino = redirecionamento(servidor, "/api/contas/youtube/retorno?code=ruim&state=E1")
    assert status == 302 and destino.startswith("/?aba=contas&erro=login%20do%20YouTube")
    status, destino = redirecionamento(servidor, "/api/contas/youtube/retorno?error=access_denied")
    assert status == 302 and "erro=" in destino and len(recebido) == 2


def test_expirar_renova_instagram_sem_derrubar(monkeypatch, capsys):
    monkeypatch.setattr(server.lixeira, "expirar", lambda: [])

    def falha(**_):
        raise RuntimeError("TOKEN-SECRETO")
    monkeypatch.setattr(contas, "renovar_instagram", falha)

    class Parar(Exception):
        pass

    def dormir(_):
        raise Parar
    monkeypatch.setattr(server.time, "sleep", dormir)
    with pytest.raises(Parar):
        server.expirar_periodicamente()
    err = capsys.readouterr().err
    assert "RuntimeError" in err and "TOKEN-SECRETO" not in err


def test_host_estranho_e_recusado(servidor, monkeypatch):
    chamadas = envio_falso(monkeypatch)
    rebind = {"Host": f"evil.example:{servidor}"}
    assert pedir(servidor, f"/api/esteira/{JID}", cabecalhos=rebind) == (403, {"erro": "host não permitido"})
    assert pedir(servidor, APROVAR, PEDIDO, rebind)[0] == 403
    assert pedir(servidor, "/api/jobs", cabecalhos={"Host": f"localhost:{servidor}"})[0] == 200
    assert pedir(servidor, "/api/jobs", cabecalhos={"Host": f"192.168.0.10:{servidor}"})[0] == 200
    assert pedir(servidor, "/api/jobs", cabecalhos={"Host": f"192.168.0.10:{servidor + 1}"})[0] == 403
    assert pedir(servidor, "/api/jobs", cabecalhos={"Host": "192.168.0.10"})[0] == 403
    assert pedir(servidor, "/api/jobs", cabecalhos={"Host": f"[::1]:{servidor}"})[0] == 200
    assert not corte().with_suffix(".publicacao").exists() and not chamadas


def test_post_sem_json_e_415(servidor, monkeypatch):
    chamadas = envio_falso(monkeypatch)
    status, r = pedir(servidor, APROVAR, PEDIDO, {"Content-Type": "text/plain"})
    assert status == 415 and r["erro"]
    assert pedir(servidor, f"/api/jobs/{JID}/parar", {}, {"Content-Type": "text/plain"})[0] == 415
    assert not corte().with_suffix(".publicacao").exists() and not chamadas


def test_get_com_dado_quebrado_e_500_com_erro(servidor):
    (server.JOBS / JID / "fonte_corte01.json").write_text("{quebrado")
    status, r = pedir(servidor, f"/api/esteira/{JID}")
    assert status == 500 and r["erro"]


def test_cortes_de_duas_transmissoes_com_mesmo_nome_sao_distintos(servidor):
    job = server.JOBS / JID
    for stream in ("canal/20261104-100000", "canal/20261104-200000"):
        pasta = job / stream
        pasta.mkdir(parents=True)
        (pasta / "lote_0000_corte01.json").write_text(json.dumps({
            "arquivo": "lote_0000_corte01.mp4", "thumbnail": "lote_0000_corte01.jpg", "titulo": stream, "nota": 7}))
    _, d = pedir(servidor, f"/api/esteira/{JID}")
    itens = d["esteira"]["nos"]["aprovacao"]["itens"]
    assert {"canal/20261104-100000/lote_0000_corte01", "canal/20261104-200000/lote_0000_corte01"} <= set(itens)
    assert len(itens) == len(set(itens)) == 3
    nomes = {c["nome"]: c["json"] for c in d["job"]["cortes"]}
    assert nomes["canal/20261104-200000/lote_0000_corte01"] == "canal/20261104-200000/lote_0000_corte01.json"


def test_log_do_job_nao_mostra_eventos(servidor):
    (server.JOBS / JID / "log.txt").write_text(
        '[v] transcrevendo\n@@ {"etapa": "ia", "estado": "inicio", "item": "v"}\n', encoding="utf-8")
    _, jobs = pedir(servidor, "/api/jobs")
    assert jobs[0]["log"] == ["[v] transcrevendo"]
    _, job = pedir(servidor, f"/api/jobs/{JID}")
    assert "@@" not in job["log"] and "transcrevendo" in job["log"]
    _, d = pedir(servidor, f"/api/esteira/{JID}")
    assert d["esteira"]["nos"]["ia"]["estado"] == "erro"  # a esteira ainda lê os eventos (job parado: interrompido)


def test_publicacao_sem_estado_nao_quebra_a_lista(servidor):
    corte().with_suffix(".publicacao").write_text(json.dumps(
        {"aprovado_em": "2026-11-04T10:00:00", "plataformas": {"youtube": {"link": None}}}))
    status, jobs = pedir(servidor, "/api/jobs")
    assert status == 200 and jobs[0]["cortes"][0]["publicacao"]["plataformas"] == {}
    assert pedir(servidor, f"/api/esteira/{JID}")[0] == 200
