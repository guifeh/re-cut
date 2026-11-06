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


OK = (200, {"ok": True, "result": {"message_id": 99}})


def msg(texto, chat=7, reply=None, update_id=1):
    m = {"message_id": 50, "chat": {"id": chat}, "from": {"first_name": "Gui"}, "text": texto}
    if reply:
        m["reply_to_message"] = {"message_id": reply}
    return {"update_id": update_id, "message": m}


def enviados(http):
    return [c[2]["text"] for c in http.chamadas if c[1].endswith("/sendMessage")]


@pytest.fixture
def pareado(tmp_path):
    p = tmp_path / "contas"
    contas.salvar("telegram", {"token": TOKEN, "bot": "meu_bot", "chat_id": 7, "nome": "Gui"}, p)
    return p


def novo_corte(tmp_path, bot="meu_bot", tiktok=None):
    job = tmp_path / "jobs" / "j1"
    job.mkdir(parents=True)
    arq = job / "c01.json"
    arq.write_text(json.dumps({"arquivo": "c01.mp4", "titulo": "t"}), encoding="utf-8")
    pub = {"plataformas": {"tiktok": tiktok or {"estado": "manual", "link": None, "erro": None, "em": None}},
           "telegram": {"estado": "ok", "erro": None, "em": None, "mensagens": [10, 11], "bot": bot, "chat_id": 7}}
    arq.with_suffix(".publicacao").write_text(json.dumps(pub), encoding="utf-8")
    return arq


def tiktok(corte_json):
    return json.loads(corte_json.with_suffix(".publicacao").read_text(encoding="utf-8"))["plataformas"]["tiktok"]


def test_start_com_codigo_pareia(tmp_path):
    contas.salvar("telegram", {"token": TOKEN, "bot": "meu_bot", "pareamento": "abc"}, tmp_path)
    http = Falso(OK)
    telegram.processar(msg("/start abc"), tmp_path / "jobs", http, tmp_path)
    d = telegram.conta(tmp_path)
    assert d["chat_id"] == 7 and d["nome"] == "Gui" and "pareamento" not in d
    assert enviados(http) == ["Pronto, os cortes aprovados vão chegar aqui"]


def test_start_errado_ou_outro_chat_ignorado(tmp_path, pareado):
    contas.salvar("telegram", {"token": TOKEN, "bot": "meu_bot", "pareamento": "abc"}, tmp_path)
    http = Falso()
    telegram.processar(msg("/start xyz"), tmp_path / "jobs", http, tmp_path)
    assert "chat_id" not in telegram.conta(tmp_path) and http.chamadas == []
    telegram.processar(msg("/start abc", chat=8), tmp_path / "jobs", http, pareado)
    assert telegram.conta(pareado)["chat_id"] == 7 and http.chamadas == []


def test_reply_com_link_salva_no_corte(tmp_path, pareado):
    corte = novo_corte(tmp_path)
    http = Falso(OK)
    telegram.processar(msg("olha https://www.tiktok.com/@eu/video/1", reply=11), tmp_path / "jobs", http, pareado)
    t = tiktok(corte)
    assert t["estado"] == "ok" and t["link"] == "https://www.tiktok.com/@eu/video/1"
    assert enviados(http) == ["✓ link salvo em t"]


def test_reply_de_outro_bot_nao_salva(tmp_path, pareado):
    corte = novo_corte(tmp_path, bot="velho")
    http = Falso(OK)
    telegram.processar(msg("https://www.tiktok.com/@eu/video/1", reply=11), tmp_path / "jobs", http, pareado)
    assert tiktok(corte)["link"] is None
    assert enviados(http) == ["Responda (arrastar para o lado) à mensagem do corte com o link"]


def test_link_sem_reply_pede_reply(tmp_path, pareado):
    novo_corte(tmp_path)
    http = Falso(OK)
    telegram.processar(msg("https://vm.tiktok.com/xyz"), tmp_path / "jobs", http, pareado)
    assert enviados(http) == ["Responda (arrastar para o lado) à mensagem do corte com o link"]


def test_link_repetido_responde_erro_do_colar_link(tmp_path, pareado):
    corte = novo_corte(tmp_path, tiktok={"estado": "ok", "link": "https://www.tiktok.com/@eu/video/0",
                                         "erro": None, "em": None})
    antes = corte.with_suffix(".publicacao").read_bytes()
    http = Falso(OK)
    telegram.processar(msg("https://www.tiktok.com/@eu/video/1", reply=10), tmp_path / "jobs", http, pareado)
    assert corte.with_suffix(".publicacao").read_bytes() == antes
    assert enviados(http) == ["essa plataforma não espera link agora"]


def test_ouvir_grava_offset_e_volta_apos_erro(tmp_path, pareado):
    falso = Falso((200, {"ok": True, "result": [msg("oi", update_id=5)]}))
    voltas, dormidas = [], []

    def http(*a, **kw):
        if not voltas[1:]:
            raise OSError("caiu")
        return falso(*a, **kw)

    def continuar():
        voltas.append(1)
        return len(voltas) <= 2

    telegram.ouvir(tmp_path / "jobs", http, pareado, dormidas.append, continuar)
    assert telegram.conta(pareado)["offset"] == 6 and dormidas == [1]
    _, url, dados, _, _ = falso.chamadas[0]
    assert url.endswith("/getUpdates") and dados["timeout"] == 50 and dados["allowed_updates"] == ["message"]
    assert falso.timeout == 60


def test_token_mal_formado_recusado_sem_http_e_sem_vazar(tmp_path):
    http = Falso()
    with pytest.raises(ValueError) as e:
        telegram.configurar("123:AB CD", http, tmp_path)
    assert http.chamadas == [] and "AB CD" not in str(e.value) and "token inválido" in str(e.value)


def test_link_tiktok_sem_pontuacao_final():
    assert telegram._link_tiktok("veja https://vm.tiktok.com/x/.") == "https://vm.tiktok.com/x/"
    assert telegram._link_tiktok("(https://vm.tiktok.com/x/)!?") == "https://vm.tiktok.com/x/"


def test_ouvir_update_com_erro_avanca_offset(tmp_path, pareado, monkeypatch):
    http = Falso((200, {"ok": True, "result": [msg("a", update_id=5)]}),
                 (200, {"ok": True, "result": [msg("b", update_id=6)]}))
    vistos, voltas = [], []

    def processar(u, *a, **kw):
        vistos.append(u["update_id"])
        if u["update_id"] == 5:
            raise RuntimeError("boom")

    monkeypatch.setattr(telegram, "processar", processar)

    def continuar():
        voltas.append(1)
        return len(voltas) <= 2

    telegram.ouvir(tmp_path / "jobs", http, pareado, lambda s: None, continuar)
    assert vistos == [5, 6] and telegram.conta(pareado)["offset"] == 7
    assert http.chamadas[1][2]["offset"] == 6


def test_link_tiktok_sem_https_vira_https():
    assert telegram._link_tiktok("olha http://vm.tiktok.com/x/") == "https://vm.tiktok.com/x/"
    assert telegram._link_tiktok("vm.tiktok.com/x/.") == "https://vm.tiktok.com/x/"
    assert telegram._link_tiktok("www.tiktok.com/@eu/video/1") == "https://www.tiktok.com/@eu/video/1"
    assert telegram._link_tiktok("https://nao-tiktok.com/x") is None
    assert telegram._link_tiktok("https://tiktok.com.evil.com/x") is None
