import base64
import datetime as dt
import hashlib
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from contas import concluir, configurar, ler, publico, renovar_instagram, requisitar, salvar, token, url_autorizacao

AGORA = dt.datetime(2026, 11, 4, 10, 0, 0)


class Falso:
    """http falso: registra (metodo, url, dados) e devolve as respostas prontas em ordem."""
    def __init__(self, *respostas):
        self.respostas, self.chamadas = list(respostas), []

    def __call__(self, metodo, url, dados=None, cabecalhos=None, corpo=None):
        self.chamadas.append((metodo, url, dados))
        status, obj = self.respostas.pop(0)
        return status, {}, json.dumps(obj).encode()


def query(url):
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))


def test_publico_nunca_expoe_segredos(tmp_path):
    salvar("youtube", {"client_id": "id", "client_secret": "S", "access_token": "A", "refresh_token": "R",
                       "nome": "Canal", "vence_em": "2026-11-04T11:00:00"}, tmp_path)
    p = publico("youtube", tmp_path)
    assert p["conectada"] and "S" not in json.dumps(p) and "A" not in json.dumps(p) and "R" not in json.dumps(p)


def test_publico_instagram_dias_restantes(tmp_path):
    salvar("instagram", {"client_id": "id", "client_secret": "s", "access_token": "t", "nome": "eu",
                         "vence_em": "2026-11-20T09:00:00"}, tmp_path)
    p = publico("instagram", tmp_path, agora=AGORA)
    assert p == {"plataforma": "instagram", "configurada": True, "conectada": True, "nome": "eu",
                 "vence_em": "2026-11-20T09:00:00", "dias_restantes": 15}
    assert publico("youtube", tmp_path)["configurada"] is False and publico("youtube", tmp_path)["dias_restantes"] is None


def test_url_youtube_pkce_e_porta(tmp_path, monkeypatch):
    monkeypatch.setenv("PORT", "8123")
    configurar("youtube", "cid", "csec", tmp_path)
    q = query(url_autorizacao("youtube", "e1", tmp_path))
    salvo = ler("youtube", tmp_path)
    assert q["redirect_uri"] == "http://127.0.0.1:8123/api/contas/youtube/retorno" and q["state"] == "e1"
    assert q["scope"] == "https://www.googleapis.com/auth/youtube.upload" and q["access_type"] == "offline"
    assert q["prompt"] == "consent" and q["code_challenge_method"] == "S256" and q["client_id"] == "cid"
    esperado = base64.urlsafe_b64encode(hashlib.sha256(salvo["verificador"].encode()).digest()).rstrip(b"=").decode()
    assert q["code_challenge"] == esperado and salvo["estado"] == "e1"


def test_url_instagram(tmp_path):
    configurar("instagram", "iid", "isec", tmp_path)
    u = url_autorizacao("instagram", "x", tmp_path)
    q = query(u)
    assert u.startswith("https://www.instagram.com/oauth/authorize?") and q["response_type"] == "code"
    assert q["redirect_uri"] == "https://guifeh.github.io/re-cut-site/callback.html"
    assert q["scope"] == "instagram_business_basic,instagram_business_content_publish"


def test_url_sem_configurar_recusa(tmp_path):
    with pytest.raises(ValueError):
        url_autorizacao("youtube", "e", tmp_path)


def test_youtube_concluir_troca_codigo_e_limpa_estado(tmp_path):
    configurar("youtube", "cid", "csec", tmp_path)
    url_autorizacao("youtube", "e1", tmp_path)
    verificador = ler("youtube", tmp_path)["verificador"]
    http = Falso((200, {"access_token": "A1", "refresh_token": "R1", "expires_in": 3599}))
    p = concluir("youtube", "cod", "e1", http=http, pasta=tmp_path, agora=AGORA)
    metodo, url, dados = http.chamadas[0]
    assert (metodo, url) == ("POST", "https://oauth2.googleapis.com/token")
    assert dados["code"] == "cod" and dados["code_verifier"] == verificador and dados["grant_type"] == "authorization_code"
    salvo = ler("youtube", tmp_path)
    assert salvo["access_token"] == "A1" and salvo["refresh_token"] == "R1" and salvo["vence_em"] == "2026-11-04T10:59:59"
    assert "estado" not in salvo and "verificador" not in salvo and p["conectada"]
    with pytest.raises(ValueError):  # uso único
        concluir("youtube", "cod", "e1", http=Falso(), pasta=tmp_path)


def test_youtube_estado_errado_recusa(tmp_path):
    configurar("youtube", "cid", "csec", tmp_path)
    url_autorizacao("youtube", "e1", tmp_path)
    antes = ler("youtube", tmp_path)
    http = Falso()
    with pytest.raises(ValueError):
        concluir("youtube", "cod", "outro", http=http, pasta=tmp_path)
    assert http.chamadas == [] and ler("youtube", tmp_path) == antes


def test_youtube_renova_token_vencendo(tmp_path):
    salvar("youtube", {"client_id": "cid", "client_secret": "csec", "access_token": "velho", "refresh_token": "R",
                       "vence_em": "2026-11-04T10:02:00"}, tmp_path)
    http = Falso((200, {"access_token": "novo", "expires_in": 3600}))
    assert token("youtube", http=http, pasta=tmp_path, agora=AGORA) == "novo"
    metodo, url, dados = http.chamadas[0]
    assert (metodo, url) == ("POST", "https://oauth2.googleapis.com/token")
    assert dados == {"client_id": "cid", "client_secret": "csec", "refresh_token": "R", "grant_type": "refresh_token"}
    salvo = ler("youtube", tmp_path)
    assert salvo["access_token"] == "novo" and salvo["refresh_token"] == "R" and salvo["vence_em"] == "2026-11-04T11:00:00"


def test_youtube_token_valido_nao_chama(tmp_path):
    salvar("youtube", {"access_token": "A", "refresh_token": "R", "vence_em": "2026-11-04T10:30:00"}, tmp_path)
    assert token("youtube", http=Falso(), pasta=tmp_path, agora=AGORA) == "A"


def test_youtube_renovacao_recusada_pede_para_conectar(tmp_path):
    salvar("youtube", {"client_id": "cid", "client_secret": "csec", "access_token": "A", "refresh_token": "REFRESH-SECRETO",
                       "vence_em": "2026-11-04T09:00:00"}, tmp_path)
    with pytest.raises(ValueError, match="aba Contas") as erro:
        token("youtube", http=Falso((400, {"error": "invalid_grant"})), pasta=tmp_path, agora=AGORA)
    assert "csec" not in str(erro.value) and "REFRESH-SECRETO" not in str(erro.value)


def test_instagram_codigo_tira_sufixo_e_pega_token_longo(tmp_path):
    configurar("instagram", "iid", "isec", tmp_path)
    http = Falso((200, {"access_token": "curto", "user_id": 17}),
                 (200, {"access_token": "longo", "token_type": "bearer", "expires_in": 5184000}),
                 (200, {"user_id": "17841", "username": "meu.perfil"}))
    p = concluir("instagram", "abc#_", None, http=http, pasta=tmp_path, agora=AGORA)
    (m1, u1, d1), (m2, u2, _), (m3, u3, _) = http.chamadas
    assert (m1, u1) == ("POST", "https://api.instagram.com/oauth/access_token")
    assert d1 == {"client_id": "iid", "client_secret": "isec", "grant_type": "authorization_code",
                  "redirect_uri": "https://guifeh.github.io/re-cut-site/callback.html", "code": "abc"}
    assert m2 == "GET" and u2.startswith("https://graph.instagram.com/access_token?")
    assert query(u2) == {"grant_type": "ig_exchange_token", "client_secret": "isec", "access_token": "curto"}
    assert m3 == "GET" and u3.startswith("https://graph.instagram.com/me?") and query(u3)["access_token"] == "longo"
    salvo = ler("instagram", tmp_path)
    assert salvo["access_token"] == "longo" and salvo["user_id"] == "17841" and salvo["nome"] == "meu.perfil"
    assert salvo["vence_em"] == "2027-01-03T10:00:00" and p["nome"] == "meu.perfil" and p["dias_restantes"] == 60


def test_instagram_erro_nao_vaza_segredo(tmp_path):
    configurar("instagram", "iid", "isec", tmp_path)
    http = Falso((400, {"error_message": "code isec abc invalido"}))
    with pytest.raises(ValueError) as erro:
        concluir("instagram", "abc", None, http=http, pasta=tmp_path)
    assert "isec" not in str(erro.value) and "abc" not in str(erro.value) and "invalido" in str(erro.value)


def test_instagram_renova_so_perto_de_vencer(tmp_path):
    salvar("instagram", {"access_token": "t1", "vence_em": "2026-12-04T10:00:00"}, tmp_path)
    http = Falso((200, {"access_token": "t2", "expires_in": 5184000}))
    assert renovar_instagram(http=http, pasta=tmp_path, agora=AGORA) is False and http.chamadas == []
    salvar("instagram", {"access_token": "t1", "vence_em": "2026-11-09T10:00:00"}, tmp_path)
    assert renovar_instagram(http=http, pasta=tmp_path, agora=AGORA) is True
    metodo, url, _ = http.chamadas[0]
    assert metodo == "GET" and url.startswith("https://graph.instagram.com/refresh_access_token?")
    assert query(url) == {"grant_type": "ig_refresh_token", "access_token": "t1"}
    salvo = ler("instagram", tmp_path)
    assert salvo["access_token"] == "t2" and salvo["vence_em"] == "2027-01-03T10:00:00"


def test_token_sem_conta_pede_para_conectar(tmp_path):
    with pytest.raises(ValueError, match="aba Contas"):
        token("instagram", pasta=tmp_path)


def test_token_instagram_vencido_pede_para_conectar(tmp_path):
    salvar("instagram", {"access_token": "t", "vence_em": "2026-11-04T09:00:00"}, tmp_path)
    with pytest.raises(ValueError, match="aba Contas"):
        token("instagram", pasta=tmp_path, agora=AGORA)


def test_requisitar_devolve_erro_e_envia_arquivo(tmp_path):
    recebido = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            recebido["corpo"] = self.rfile.read(int(self.headers["Content-Length"]))
            recebido["tipo"] = self.headers["Content-Type"]
            self.send_response(400)
            self.send_header("X-Coisa", "1")
            self.end_headers()
            self.wfile.write(b'{"error": "ruim"}')

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}/"
    try:
        status, cab, corpo = requisitar("POST", url, dados={"a": "1 2"})
        assert status == 400 and json.loads(corpo) == {"error": "ruim"} and cab.get("x-coisa") == "1"
        assert recebido == {"corpo": b"a=1+2", "tipo": "application/x-www-form-urlencoded"}
        requisitar("POST", url, dados={"a": 1}, cabecalhos={"Content-Type": "application/json"})
        assert json.loads(recebido["corpo"]) == {"a": 1}
        arquivo = tmp_path / "v.mp4"
        arquivo.write_bytes(b"x" * 100000)
        with arquivo.open("rb") as f:
            requisitar("POST", url, cabecalhos={"Content-Length": "100000", "Content-Type": "video/mp4"}, corpo=f)
        assert recebido["corpo"] == b"x" * 100000
    finally:
        srv.shutdown()


def test_desconectar_mantem_o_app(tmp_path):
    from contas import desconectar
    salvar("youtube", {"client_id": "c", "client_secret": "s", "access_token": "t", "refresh_token": "r",
                       "vence_em": "2999-01-01T00:00:00", "nome": "canal"}, tmp_path)
    assert desconectar("youtube", tmp_path)["conectada"] is False
    assert ler("youtube", tmp_path) == {"client_id": "c", "client_secret": "s"}


def test_trocar_client_id_apaga_tokens_do_app_antigo(tmp_path):
    salvar("youtube", {"client_id": "c", "client_secret": "s", "access_token": "t", "refresh_token": "r",
                       "vence_em": "2999-01-01T00:00:00", "nome": "canal"}, tmp_path)
    configurar("youtube", "c", "s2", tmp_path)  # mesmo app, segredo novo: mantém a conexão
    assert ler("youtube", tmp_path)["refresh_token"] == "r"
    configurar("youtube", "outro", "s3", tmp_path)
    assert ler("youtube", tmp_path) == {"client_id": "outro", "client_secret": "s3"}
