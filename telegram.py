"""Telegram: conta do bot (contas/telegram.json) e chamadas à Bot API. O token nunca sai daqui: erros trazem ***."""
import json
import re
import secrets
import sys
import time
import urllib.parse
import uuid
from pathlib import Path

import contas

API = "https://api.telegram.org"


class Recusado(ValueError):
    """4xx da Bot API; a mensagem é a description. 429 traz retry_after (segundos)."""
    def __init__(self, mensagem, status, retry_after=None):
        super().__init__(mensagem)
        self.status, self.retry_after = status, retry_after


def _multipart(dados, campo, caminho):
    limite = uuid.uuid4().hex
    partes = [f'--{limite}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
              for k, v in (dados or {}).items()]
    nome = Path(caminho).name.replace('"', "")
    partes.append(f'--{limite}\r\nContent-Disposition: form-data; name="{campo}"; filename="{nome}"\r\n'
                  "Content-Type: application/octet-stream\r\n\r\n".encode())
    # ponytail: arquivo inteiro em memória (teto de 50 MB do Telegram); em blocos se o teto subir
    partes += [Path(caminho).read_bytes(), f"\r\n--{limite}--\r\n".encode()]
    return f"multipart/form-data; boundary={limite}", b"".join(partes)


def chamar(token, metodo, dados=None, arquivo=None, http=None, timeout=60):
    """POST em /bot<token>/<metodo>; devolve result. 4xx: Recusado; 5xx: ValueError; rede: OSError."""
    http = http or contas.requisitar
    url = f"{API}/bot{token}/{metodo}"
    try:
        if arquivo:
            tipo, corpo = _multipart(dados, *arquivo)
            status, _, resp = http("POST", url, None, {"Content-Type": tipo}, corpo, timeout)
        else:
            status, _, resp = http("POST", url, dados or {}, {"Content-Type": "application/json"}, timeout=timeout)
    except OSError as e:
        raise OSError(str(e).replace(token, "***")) from None
    try:
        r = json.loads(resp)
    except ValueError:
        r = {}
    if status < 300 and r.get("ok"):
        return r.get("result")
    texto = str(r.get("description") or f"erro {status}").replace(token, "***")
    if 400 <= status < 500:
        raise Recusado(texto, status, (r.get("parameters") or {}).get("retry_after"))
    raise ValueError(f"Telegram falhou ({status}): {texto}")


def conta(pasta=contas.PASTA):
    return contas.ler("telegram", pasta)


def publico(pasta=contas.PASTA):
    d = conta(pasta)
    pendente = d.get("token") and not d.get("chat_id") and d.get("pareamento")
    return {"plataforma": "telegram", "configurada": bool(d.get("token")), "conectada": bool(d.get("chat_id")),
            "nome": d.get("nome"), "bot": d.get("bot"),
            "link_pareamento": f"https://t.me/{d.get('bot')}?start={d['pareamento']}" if pendente else None}


def configurar(token, http=None, pasta=contas.PASTA):
    token = (token or "").strip()
    if not token:
        raise ValueError("cole o token do bot")
    if not re.fullmatch(r"\d+:[\w-]+", token):  # antes de qualquer chamada: http.client levantaria InvalidURL com o token
        raise ValueError("token inválido: copie o token inteiro que o BotFather mandou")
    bot = chamar(token, "getMe", http=http)["username"]  # token inválido: sobe antes de gravar
    with contas._trava:
        d = conta(pasta)
        if d.get("token") != token:  # outro bot: chat, nome e offset eram do antigo
            d = {}
        d.update(token=token, bot=bot)
        if not d.get("chat_id"):
            d["pareamento"] = secrets.token_urlsafe(6)
        contas.salvar("telegram", d, pasta)
    return publico(pasta)


def desconectar(pasta=contas.PASTA):
    with contas._trava:
        (Path(pasta) / "telegram.json").unlink(missing_ok=True)
    return publico(pasta)


PEDE_REPLY = "Responda (arrastar para o lado) à mensagem do corte com o link"


def achar_corte(jobs, bot, chat_id, message_id):
    """.json do corte cuja mensagem no Telegram (deste bot e chat) é message_id; None se nenhum."""
    # ponytail: varre os .publicacao; índice em contas/telegram.json se ficar lento
    for f in Path(jobs).glob("**/*.publicacao"):
        try:
            t = json.loads(f.read_text(encoding="utf-8")).get("telegram") or {}
        except (OSError, ValueError):  # apagado ou corrompido no meio da varredura: não trava a escuta
            continue
        for envio in [t, *(t.get("historico") or [])]:
            if isinstance(envio, dict) and envio.get("bot") == bot and envio.get("chat_id") == chat_id \
                    and message_id in (envio.get("mensagens") or []):
                return f.with_suffix(".json")
    return None


def _link_tiktok(texto):
    for url in re.findall(r"(?<![\w.-])(?:https?://)?(?:[\w-]+\.)*tiktok\.com\S*", texto, re.I):
        url = "https://" + re.sub(r"^https?://", "", url, flags=re.I)
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
        if host == "tiktok.com" or host.endswith(".tiktok.com"):
            return url.rstrip(".,;:!?)]}>'\"")
    return None


def _responder(token, chat_id, texto, http):
    try:  # o que importa já foi gravado; resposta perdida não refaz o update
        chamar(token, "sendMessage", {"chat_id": chat_id, "text": texto}, http=http)
    except (OSError, ValueError) as e:
        print(f"telegram: resposta não saiu ({type(e).__name__})", file=sys.stderr)


def processar(update, jobs, http=None, pasta=contas.PASTA):
    import publicar  # publicar importa telegram no topo
    m = update.get("message") or {}
    chat, texto = (m.get("chat") or {}).get("id"), m.get("text") or ""
    d = conta(pasta)
    if not d.get("token") or chat is None:
        return
    if not d.get("chat_id"):
        with contas._trava:
            d = conta(pasta)
            if d.get("chat_id") or not d.get("pareamento") or texto.strip() != f"/start {d['pareamento']}":
                return
            d.pop("pareamento")
            d.update(chat_id=chat, nome=(m.get("from") or m["chat"]).get("first_name"))
            contas.salvar("telegram", d, pasta)
        return _responder(d["token"], chat, "Pronto, os cortes aprovados vão chegar aqui", http)
    link = _link_tiktok(texto)
    if chat != d["chat_id"] or not link:  # outro chat ou conversa: silêncio
        return
    reply = (m.get("reply_to_message") or {}).get("message_id")
    corte = reply and achar_corte(jobs, d.get("bot"), chat, reply)
    if not corte:
        return _responder(d["token"], chat, PEDE_REPLY, http)
    try:
        publicar.colar_link(corte, "tiktok", link)
        titulo = json.loads(Path(corte).read_text(encoding="utf-8")).get("titulo") or Path(corte).stem
        resposta = f"✓ link salvo em {titulo}"
    except (OSError, ValueError) as e:
        resposta = str(e)
    _responder(d["token"], chat, resposta, http)


def ouvir(jobs, http=None, pasta=contas.PASTA, dormir=time.sleep, continuar=lambda: True):
    """Long polling enquanto continuar(): sem token espera; erro espera 1, 2, 4… até 60 s."""
    espera = 1
    while continuar():
        token = conta(pasta).get("token")
        if not token:
            dormir(5)
            continue
        try:
            dados = {"offset": conta(pasta).get("offset", 0), "timeout": 50, "allowed_updates": ["message"]}
            for u in chamar(token, "getUpdates", dados, http=http, timeout=60) or []:
                try:
                    processar(u, jobs, http, pasta)
                finally:  # update com erro não pode repetir para sempre e travar os seguintes
                    with contas._trava:
                        d = conta(pasta)
                        if d.get("token") == token:  # trocou de bot ou desconectou: o offset era do antigo
                            d["offset"] = u["update_id"] + 1
                            contas.salvar("telegram", d, pasta)
            espera = 1
        except Exception as e:  # noqa: BLE001 - a escuta não pode morrer; só o tipo (a mensagem pode ter o token)
            print(f"telegram: escuta falhou ({type(e).__name__})", file=sys.stderr)
            dormir(espera)
            espera = min(espera * 2, 60)
