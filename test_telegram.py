import json

import pytest

import contas
import telegram


class Falso:
    """http falso: registra (metodo, url, dados, cabecalhos, corpo) e devolve as respostas em ordem."""
    def __init__(self, *respostas):
        self.respostas, self.chamadas = list(respostas), []

    def __call__(self, metodo, url, dados=None, cabecalhos=None, corpo=None, timeout=60):
        self.chamadas.append((metodo, url, dados, cabecalhos, corpo))
        self.timeout = timeout
        status, obj = self.respostas.pop(0)
        return status, {}, json.dumps(obj).encode()


TOKEN = "123:SEGREDO"


def test_configurar_valida_token_e_gera_pareamento(tmp_path):
    http = Falso((200, {"ok": True, "result": {"username": "meu_bot"}}))
    p = telegram.configurar(TOKEN, http, tmp_path)
    par = telegram.conta(tmp_path)["pareamento"]
    assert p == {"plataforma": "telegram", "configurada": True, "conectada": False, "nome": None,
                 "bot": "meu_bot", "link_pareamento": f"https://t.me/meu_bot?start={par}"}
    assert http.chamadas[0][1].endswith("/getMe")


def test_token_invalido_e_400_sem_vazar(tmp_path):
    http = Falso((401, {"ok": False, "description": f"Unauthorized {TOKEN}"}))
    with pytest.raises(ValueError) as e:
        telegram.configurar(TOKEN, http, tmp_path)
    assert "Unauthorized" in str(e.value) and TOKEN not in str(e.value)
    assert telegram.conta(tmp_path) == {}


def test_trocar_token_zera_chat(tmp_path):
    contas.salvar("telegram", {"token": TOKEN, "bot": "a", "chat_id": 7, "nome": "G", "offset": 3}, tmp_path)
    p = telegram.configurar("9:OUTRO", Falso((200, {"ok": True, "result": {"username": "b"}})), tmp_path)
    assert p["conectada"] is False and p["bot"] == "b"
    assert "chat_id" not in telegram.conta(tmp_path) and "offset" not in telegram.conta(tmp_path)


def test_desconectar_apaga_arquivo(tmp_path):
    telegram.configurar(TOKEN, Falso((200, {"ok": True, "result": {"username": "b"}})), tmp_path)
    p = telegram.desconectar(tmp_path)
    assert not (tmp_path / "telegram.json").exists() and p["configurada"] is False and p["link_pareamento"] is None


def test_chamar_429_traz_retry_after():
    http = Falso((429, {"ok": False, "description": "Too Many Requests", "parameters": {"retry_after": 3}}))
    with pytest.raises(telegram.Recusado) as e:
        telegram.chamar(TOKEN, "sendMessage", {"chat_id": 1}, http=http)
    assert e.value.retry_after == 3 and e.value.status == 429


def test_chamar_5xx_e_value_error_simples():
    with pytest.raises(ValueError) as e:
        telegram.chamar(TOKEN, "getMe", http=Falso((502, {"ok": False, "description": "Bad Gateway"})))
    assert not isinstance(e.value, telegram.Recusado)


def test_chamar_multipart(tmp_path):
    mp4 = tmp_path / "corte.mp4"
    mp4.write_bytes(b"BYTESDOVIDEO")
    http = Falso((200, {"ok": True, "result": {"message_id": 5}}))
    r = telegram.chamar(TOKEN, "sendVideo", {"chat_id": 99}, ("video", mp4), http=http)
    _, url, _, cab, corpo = http.chamadas[0]
    assert r == {"message_id": 5} and url.endswith("/sendVideo")
    assert cab["Content-Type"].startswith("multipart/form-data; boundary=")
    assert b"corte.mp4" in corpo and b"BYTESDOVIDEO" in corpo and b'name="chat_id"' in corpo and b"99" in corpo


def test_publico_nunca_tem_token(tmp_path):
    telegram.configurar(TOKEN, Falso((200, {"ok": True, "result": {"username": "b"}})), tmp_path)
    assert "token" not in json.dumps(telegram.publico(tmp_path)).replace("link_pareamento", "")
    assert "SEGREDO" not in json.dumps(telegram.publico(tmp_path))


def test_chamar_repassa_timeout(tmp_path):
    mp4 = tmp_path / "c.mp4"
    mp4.write_bytes(b"x")
    http = Falso((200, {"ok": True, "result": []}), (200, {"ok": True, "result": {}}))
    telegram.chamar(TOKEN, "getUpdates", {"timeout": 50}, http=http, timeout=70)
    assert http.timeout == 70
    telegram.chamar(TOKEN, "sendVideo", arquivo=("video", mp4), http=http, timeout=90)
    assert http.timeout == 90
