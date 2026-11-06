"""Contas do re-cut: credenciais e tokens do YouTube e do Instagram, um JSON por plataforma em contas/ (fora do git).

Só publico() sai daqui para o frontend; client_secret, tokens e o verificador PKCE nunca vão para log, API ou
mensagem de erro. O guia de como criar os apps está em docs/contas-passo-a-passo.md.
"""
import base64
import datetime as dt
import hashlib
import json
import os
import secrets
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import recut

PLATAFORMAS = ("youtube", "instagram")
PASTA = Path(__file__).with_name("contas")
REDIRECT_INSTAGRAM = "https://guifeh.github.io/re-cut-site/callback.html"
TOKEN_GOOGLE = "https://oauth2.googleapis.com/token"
GRAPH = "https://graph.instagram.com"
SEGREDOS = ("client_secret", "access_token", "refresh_token", "code", "code_verifier")  # tirados das mensagens de erro
FOLGA_YOUTUBE = dt.timedelta(minutes=5)
FOLGA_INSTAGRAM = dt.timedelta(days=10)

# ponytail: um lock global para tudo que lê-altera-grava (inclusive durante a chamada de rede); por plataforma se pesar
_trava = threading.RLock()


def _agora(agora=None):
    return (agora or dt.datetime.now()).replace(microsecond=0)


def requisitar(metodo, url, dados=None, cabecalhos=None, corpo=None, timeout=60):
    """urllib com resposta sempre devolvida: (status, cabeçalhos, bytes), inclusive em 4xx/5xx.
    dados: dict em form-urlencoded (ou JSON se Content-Type for application/json). corpo: bytes ou arquivo aberto
    em binário (enviado em blocos; quem chama põe o Content-Length). Erro de rede sobe como OSError."""
    cab = dict(cabecalhos or {})
    if dados is not None:
        if any(k.lower() == "content-type" and "json" in v for k, v in cab.items()):
            corpo = json.dumps(dados).encode()
        else:
            corpo = urllib.parse.urlencode(dados).encode()
            cab.setdefault("Content-Type", "application/x-www-form-urlencoded")
    pedido = urllib.request.Request(url, data=corpo, headers=cab, method=metodo)
    try:
        with urllib.request.urlopen(pedido, timeout=timeout) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        with e:
            return e.code, e.headers, e.read()


def _validar(plataforma):
    if plataforma not in PLATAFORMAS + ("telegram",):  # telegram: conta do bot, sem OAuth
        raise ValueError(f"plataforma desconhecida: {plataforma}")


def ler(plataforma, pasta=PASTA):
    _validar(plataforma)
    arquivo = Path(pasta) / f"{plataforma}.json"
    return json.loads(arquivo.read_text(encoding="utf-8")) if arquivo.exists() else {}


def salvar(plataforma, dados, pasta=PASTA):
    _validar(plataforma)
    with _trava:  # gravar_json usa um temporário por processo: duas threads no mesmo arquivo colidiriam
        Path(pasta).mkdir(parents=True, exist_ok=True)
        recut.gravar_json(Path(pasta) / f"{plataforma}.json", dados)


def publico(plataforma, pasta=PASTA, agora=None):
    d = ler(plataforma, pasta)
    # YouTube: vence_em é do access token de 1 h, renovado sozinho; a conexão não vence, então não mostra prazo
    vence = d.get("vence_em") if plataforma == "instagram" and d.get("access_token") else None
    dias = (dt.datetime.fromisoformat(vence) - _agora(agora)) // dt.timedelta(days=1) if vence else None
    return {"plataforma": plataforma, "configurada": bool(d.get("client_id") and d.get("client_secret")),
            "conectada": bool(d.get("access_token")), "nome": d.get("nome"), "vence_em": vence, "dias_restantes": dias}


def configurar(plataforma, client_id, client_secret, pasta=PASTA):
    client_id, client_secret = (client_id or "").strip(), (client_secret or "").strip()
    if not client_id or not client_secret:
        raise ValueError("preencha o client id e o client secret")
    with _trava:
        d = ler(plataforma, pasta)
        if d.get("client_id") != client_id:  # outro app: tokens, nome e validade eram do app antigo
            d = {}
        salvar(plataforma, {**d, "client_id": client_id, "client_secret": client_secret}, pasta)


def desconectar(plataforma, pasta=PASTA):
    """Tira a conexão e mantém o app (client id/secret) para conectar de novo sem redigitar."""
    with _trava:  # sob a trava: uma renovação de token no meio de um envio não regrava os tokens apagados
        d = ler(plataforma, pasta)
        salvar(plataforma, {k: d[k] for k in ("client_id", "client_secret") if k in d}, pasta)
    return publico(plataforma, pasta)


def _redirect_youtube():
    return f"http://127.0.0.1:{os.getenv('PORT', '8000')}/api/contas/youtube/retorno"


def url_autorizacao(plataforma, estado, pasta=PASTA):
    with _trava:
        d = ler(plataforma, pasta)
        if not d.get("client_id"):
            raise ValueError(f"configure o app do {plataforma} na aba Contas antes de conectar")
        if plataforma == "instagram":
            return "https://www.instagram.com/oauth/authorize?" + urllib.parse.urlencode({
                "client_id": d["client_id"], "redirect_uri": REDIRECT_INSTAGRAM, "response_type": "code",
                "scope": "instagram_business_basic,instagram_business_content_publish", "state": estado})
        verificador = secrets.token_urlsafe(64)
        desafio = base64.urlsafe_b64encode(hashlib.sha256(verificador.encode()).digest()).rstrip(b"=").decode()
        salvar(plataforma, {**d, "estado": estado, "verificador": verificador}, pasta)
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
            "client_id": d["client_id"], "redirect_uri": _redirect_youtube(), "response_type": "code",
            "scope": "https://www.googleapis.com/auth/youtube.upload", "access_type": "offline", "prompt": "consent",
            "state": estado, "code_challenge": desafio, "code_challenge_method": "S256"})


def _pedir(http, rotulo, metodo, url, dados=None):
    """Chama e devolve o JSON; em erro, ValueError com a resposta da plataforma sem os segredos enviados."""
    status, _, corpo = http(metodo, url, dados)
    if 200 <= status < 300:
        return json.loads(corpo)
    texto = corpo.decode("utf-8", "replace")[:500]
    enviados = {**dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query)), **(dados or {})}
    for chave in SEGREDOS:
        if enviados.get(chave):
            texto = texto.replace(str(enviados[chave]), "***")
    raise ValueError(f"{rotulo} recusado ({status}): {texto}")


def _vence(agora, segundos):
    return (_agora(agora) + dt.timedelta(seconds=int(segundos))).isoformat()


def concluir(plataforma, codigo, estado, http=None, pasta=PASTA, agora=None):
    """Troca o código do login por tokens e grava. Devolve publico()."""
    http = http or requisitar
    codigo = (codigo or "").strip()
    with _trava:
        d = ler(plataforma, pasta)
        if not d.get("client_id"):
            raise ValueError(f"configure o app do {plataforma} na aba Contas antes de conectar")
        if plataforma == "youtube":
            if not estado or estado != d.get("estado"):
                raise ValueError("login do YouTube expirado ou de outra aba: clique em conectar de novo")
            verificador = d.pop("verificador", None)
            d.pop("estado")
            salvar(plataforma, d, pasta)  # uso único, mesmo que a troca falhe
            r = _pedir(http, "login do YouTube", "POST", TOKEN_GOOGLE, {
                "code": codigo, "client_id": d["client_id"], "client_secret": d["client_secret"],
                "redirect_uri": _redirect_youtube(), "grant_type": "authorization_code", "code_verifier": verificador})
            # ponytail: nome do canal fica vazio; youtube.upload não lê o canal (precisaria de youtube.readonly)
            d.update(access_token=r["access_token"], refresh_token=r.get("refresh_token", d.get("refresh_token")),
                     vence_em=_vence(agora, r.get("expires_in", 3600)))
        else:
            codigo = codigo.removesuffix("#_")  # o Instagram cola "#_" no fim do código
            r = _pedir(http, "login do Instagram", "POST", "https://api.instagram.com/oauth/access_token", {
                "client_id": d["client_id"], "client_secret": d["client_secret"], "grant_type": "authorization_code",
                "redirect_uri": REDIRECT_INSTAGRAM, "code": codigo})
            curto = r.get("data", [r])[0]["access_token"]  # a resposta às vezes vem dentro de "data"
            longo = _pedir(http, "token longo do Instagram", "GET", f"{GRAPH}/access_token?" + urllib.parse.urlencode({
                "grant_type": "ig_exchange_token", "client_secret": d["client_secret"], "access_token": curto}))
            eu = _pedir(http, "perfil do Instagram", "GET", f"{GRAPH}/me?" + urllib.parse.urlencode({
                "fields": "user_id,username", "access_token": longo["access_token"]}))
            d.update(access_token=longo["access_token"], vence_em=_vence(agora, longo["expires_in"]),
                     user_id=str(eu["user_id"]), nome=eu.get("username"))
        salvar(plataforma, d, pasta)
    return publico(plataforma, pasta, agora)


def _conecte(plataforma, motivo=""):
    return ValueError(f"conecte a conta do {plataforma} na aba Contas" + (f" ({motivo})" if motivo else ""))


def token(plataforma, http=None, pasta=PASTA, agora=None):
    """Access token válido; o do YouTube é renovado com o refresh token quando faltam menos de 5 min."""
    with _trava:
        d = ler(plataforma, pasta)
        if not d.get("access_token"):
            raise _conecte(plataforma)
        vence = dt.datetime.fromisoformat(d["vence_em"])
        if plataforma == "instagram":
            if vence <= _agora(agora):
                raise _conecte(plataforma, "o acesso venceu")
            return d["access_token"]
        if vence - _agora(agora) >= FOLGA_YOUTUBE:
            return d["access_token"]
        if not d.get("refresh_token"):
            raise _conecte(plataforma)
        try:
            r = _pedir(http or requisitar, "renovação do YouTube", "POST", TOKEN_GOOGLE, {
                "client_id": d.get("client_id"), "client_secret": d.get("client_secret"),
                "refresh_token": d["refresh_token"], "grant_type": "refresh_token"})
        except ValueError as e:
            raise _conecte(plataforma, str(e)) from None
        d.update(access_token=r["access_token"], vence_em=_vence(agora, r.get("expires_in", 3600)))
        if r.get("refresh_token"):
            d["refresh_token"] = r["refresh_token"]
        salvar(plataforma, d, pasta)
        return d["access_token"]


def renovar_instagram(http=None, pasta=PASTA, agora=None):
    """Renova o token longo (60 dias) quando faltam menos de 10 dias. True se renovou."""
    with _trava:
        d = ler("instagram", pasta)
        if not d.get("access_token") or dt.datetime.fromisoformat(d["vence_em"]) - _agora(agora) >= FOLGA_INSTAGRAM:
            return False
        r = _pedir(http or requisitar, "renovação do Instagram", "GET", f"{GRAPH}/refresh_access_token?" +
                   urllib.parse.urlencode({"grant_type": "ig_refresh_token", "access_token": d["access_token"]}))
        d.update(access_token=r["access_token"], vence_em=_vence(agora, r["expires_in"]))
        salvar("instagram", d, pasta)
        return True
