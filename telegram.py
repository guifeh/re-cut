"""Telegram: conta do bot (contas/telegram.json) e chamadas à Bot API. O token nunca sai daqui: erros trazem ***."""
import json
import secrets
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
            status, _, resp = http("POST", url, None, {"Content-Type": tipo}, corpo)
        else:
            status, _, resp = http("POST", url, dados or {}, {"Content-Type": "application/json"})
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
