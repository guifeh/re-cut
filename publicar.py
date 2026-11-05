"""Publicação de um corte aprovado: YouTube Shorts e Instagram Reels pela API, TikTok manual (o usuário cola o link).

Estado por plataforma em <corte>.publicacao, ao lado do JSON do corte. Toda mudança é gravada antes da chamada de
rede que ela anuncia: um processo que morre no meio deixa "enviando", que vira "incerto" na leitura e nunca é
reenviado sozinho. "ok" nunca é reenviado.
"""
import datetime as dt
import json
import threading
import time
import urllib.parse
from pathlib import Path

import contas
import recut

VERSAO_IG = "v26.0"
GRAPH_IG = f"{contas.GRAPH}/{VERSAO_IG}"
DOMINIOS = {"youtube": ("youtube.com", "youtu.be"), "instagram": ("instagram.com",), "tiktok": ("tiktok.com",)}
ESPERA_IG, TENTATIVAS_IG = 30, 21  # confere na hora e a cada 30 s por até 10 min

# ponytail: um lock global para todo lê-altera-grava de .publicacao (gravar_json usa um temporário por processo)
_trava = threading.Lock()


class Recusado(ValueError):
    """A plataforma respondeu 4xx: o vídeo não saiu. (5xx num passo que publica vira "incerto": pode ter saído.)"""


def _arquivo(corte_json):
    return Path(corte_json).with_suffix(".publicacao")


def _agora():
    return dt.datetime.now().replace(microsecond=0).isoformat()


def _ler(corte_json):
    """Plataforma sem "estado" (arquivo editado à mão, versão antiga) conta como ausente em vez de quebrar a lista."""
    f = _arquivo(corte_json)
    pub = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    if "plataformas" in pub:
        pub["plataformas"] = {p: e for p, e in pub["plataformas"].items() if isinstance(e, dict) and "estado" in e}
    return pub


def _estado(estado, **extra):
    return {"estado": estado, "link": None, "erro": None, "em": _agora(), "container": None, **extra}


def _mudar(corte_json, plataforma, estado, **campos):
    with _trava:
        pub = _ler(corte_json)
        if plataforma not in pub.get("plataformas", {}):  # corte foi para a Lixeira no meio do envio: não recria
            return _estado(estado, **campos)
        pub["plataformas"][plataforma] = {**pub["plataformas"][plataforma], "estado": estado, "em": _agora(), **campos}
        recut.gravar_json(_arquivo(corte_json), pub)
        return pub["plataformas"][plataforma]


def _plataforma(pub, plataforma):
    if plataforma not in pub.get("plataformas", {}):
        raise ValueError("esse corte ainda não foi aprovado" if not pub else f"plataforma desconhecida: {plataforma}")
    return pub["plataformas"][plataforma]


def ler_publicacao(corte_json, ativos):
    """{} se não aprovado. "enviando" sem envio ativo (processo caiu no meio) vira "incerto" e é regravado."""
    chave = str(Path(corte_json).resolve())
    with _trava:
        pub = _ler(corte_json)
        orfaos = [p for p, e in pub.get("plataformas", {}).items() if e["estado"] == "enviando" and (chave, p) not in ativos]
        for p in orfaos:
            pub["plataformas"][p].update(estado="incerto", em=_agora(),
                                         erro="o envio foi interrompido; confira no app se o vídeo saiu")
        if orfaos:
            recut.gravar_json(_arquivo(corte_json), pub)
        return pub


def sem_sinais(texto):
    """O YouTube recusa (400) título e descrição com < ou >."""
    return texto.replace("<", "").replace(">", "")


def texto_final(legenda, hashtags):
    """Legenda + linha em branco + até 30 hashtags; a legenda é cortada para o total caber em 2200 caracteres."""
    tags = " ".join([f"#{t}" for t in ("".join(h.split()).lstrip("#") for h in hashtags) if t][:30])
    sufixo = f"\n\n{tags}" if tags else ""
    return (legenda.strip()[:2200 - len(sufixo)] + sufixo)[:2200]


def aprovar(corte_json, legenda, hashtags):
    """Grava a escolha e marca YouTube/Instagram como "enviando"; devolve as plataformas que o servidor envia."""
    with _trava:
        if _ler(corte_json).get("aprovado_em"):
            raise ValueError("esse corte já foi aprovado")
        recut.gravar_json(_arquivo(corte_json), {
            "aprovado_em": _agora(), "legenda": legenda, "hashtags": list(hashtags),
            "plataformas": {"youtube": _estado("enviando"), "instagram": _estado("enviando"), "tiktok": _estado("manual")}})
    return ["youtube", "instagram"]


def tentar_de_novo(corte_json, plataforma, forcar):
    with _trava:
        pub = _ler(corte_json)
        estado = _plataforma(pub, plataforma)["estado"]
        if estado == "ok":
            raise ValueError("já foi postado")
        if estado == "incerto" and not forcar:
            raise ValueError("o envio anterior pode ter saído: confira no app antes de enviar de novo")
        if estado not in ("erro", "incerto"):
            raise ValueError(f"não dá para reenviar agora ({estado})")
        pub["plataformas"][plataforma].update(estado="enviando", erro=None, em=_agora())  # container fica: ver _instagram
        recut.gravar_json(_arquivo(corte_json), pub)


def colar_link(corte_json, plataforma, link):
    partes = urllib.parse.urlsplit((link or "").strip())
    host = (partes.hostname or "").lower()
    if partes.scheme != "https" or not any(host == d or host.endswith("." + d) for d in DOMINIOS.get(plataforma, ())):
        raise ValueError(f"cole um link https do {plataforma}")
    with _trava:
        pub = _ler(corte_json)
        atual = _plataforma(pub, plataforma)
        if atual["estado"] not in ("manual", "incerto", "erro") and not (atual["estado"] == "ok" and not atual.get("link")):
            raise ValueError("essa plataforma não espera link agora")
        pub["plataformas"][plataforma].update(estado="ok", link=partes.geturl(), erro=None, em=_agora())
        recut.gravar_json(_arquivo(corte_json), pub)


def _json(resposta, rotulo):
    status, _, corpo = resposta
    if not 200 <= status < 300:
        raise (Recusado if status < 500 else ValueError)(f"{rotulo} recusado ({status}): {corpo.decode('utf-8', 'replace')[:300]}")
    return json.loads(corpo)


def enviar(corte_json, plataforma, http=None, esperar=time.sleep, pasta_contas=contas.PASTA):
    """Envia e grava "ok" + link, "erro" + mensagem ou "incerto" (caiu depois que o vídeo pode ter saído).
    Nunca levanta depois de começar: a falha fica no arquivo e não atrapalha a outra plataforma."""
    with _trava:
        pub = _ler(corte_json)
        if _plataforma(pub, plataforma)["estado"] != "enviando":  # tiktok nunca fica "enviando"
            raise ValueError(f"{plataforma} não está para enviar")
    http, tok, etapa = http or contas.requisitar, None, ["antes"]
    try:
        tok = contas.token(plataforma, http, pasta_contas)
        meta = json.loads(Path(corte_json).read_text(encoding="utf-8"))
        video = Path(corte_json).with_name(meta["arquivo"])
        texto = texto_final(pub["legenda"], pub["hashtags"])
        if plataforma == "youtube":
            link = _youtube(http, tok, video, pub["legenda"], texto, etapa)
        else:
            link = _instagram(http, tok, contas.ler("instagram", pasta_contas)["user_id"], video, texto, corte_json,
                              pub["plataformas"]["instagram"].get("container"), esperar, etapa)
        return _mudar(corte_json, plataforma, "ok", link=link, erro=None)
    except Exception as e:  # noqa: BLE001 — qualquer falha vira estado; nunca derruba a thread da outra plataforma
        incerto = etapa[0] == "arriscada" and not isinstance(e, Recusado)  # resposta perdida ou ilegível: pode ter saído
        msg = (f"falha de rede: {e}" if isinstance(e, OSError) else str(e)) or type(e).__name__
        if incerto:
            msg = f"não deu para confirmar o envio ({msg}); confira no app se o vídeo saiu"
        if tok:
            msg = msg.replace(tok, "***")
        return _mudar(corte_json, plataforma, "incerto" if incerto else "erro", erro=msg)


def _youtube(http, tok, video, legenda, texto, etapa):
    tamanho = video.stat().st_size
    metadados = {"snippet": {"title": sem_sinais(legenda).strip()[:100], "description": sem_sinais(texto), "categoryId": "22"},
                 "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False}}
    status, cab, corpo = http("POST", "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable"
                              "&part=snippet,status", dados=metadados, cabecalhos={
                                  "Authorization": f"Bearer {tok}", "Content-Type": "application/json; charset=UTF-8",
                                  "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(tamanho)})
    _json((status, cab, corpo or b"{}"), "início do envio ao YouTube")
    sessao = cab.get("Location") or cab.get("location")
    if not sessao:
        raise ValueError("o YouTube não devolveu o endereço de envio")
    etapa[0] = "arriscada"  # daqui em diante o vídeo pode sair mesmo que a resposta não chegue
    with open(video, "rb") as f:
        r = _json(http("PUT", sessao, cabecalhos={"Authorization": f"Bearer {tok}", "Content-Type": "video/mp4",
                                                  "Content-Length": str(tamanho)}, corpo=f), "envio ao YouTube")
    return f"https://youtube.com/shorts/{r['id']}"


def _instagram(http, tok, user_id, video, texto, corte_json, container, esperar, etapa):
    q = lambda **p: urllib.parse.urlencode({**p, "access_token": tok})  # noqa: E731
    if container:  # reenvio: um container já publicado quer dizer que o Reel saiu
        if _json(http("GET", f"{GRAPH_IG}/{container}?{q(fields='status_code')}"),
                 "consulta do container").get("status_code") == "PUBLISHED":
            raise ValueError("esse vídeo já saiu no Instagram: cole o link do Reel")
    tamanho = video.stat().st_size
    container = _json(http("POST", f"{GRAPH_IG}/{user_id}/media", dados={
        "media_type": "REELS", "upload_type": "resumable", "caption": texto, "access_token": tok}),
        "criação do Reel")["id"]
    _mudar(corte_json, "instagram", "enviando", container=container)
    with open(video, "rb") as f:
        _json(http("POST", f"https://rupload.facebook.com/ig-api-upload/{VERSAO_IG}/{container}", cabecalhos={
            "Authorization": f"OAuth {tok}", "offset": "0", "file_size": str(tamanho),
            "Content-Length": str(tamanho)}, corpo=f), "envio do vídeo ao Instagram")
    for tentativa in range(TENTATIVAS_IG):
        if tentativa:
            esperar(ESPERA_IG)
        situacao = _json(http("GET", f"{GRAPH_IG}/{container}?{q(fields='status_code')}"),
                         "consulta do container").get("status_code")
        if situacao == "FINISHED":
            break
        if situacao in ("ERROR", "EXPIRED"):
            raise ValueError(f"o Instagram não aceitou o vídeo ({situacao})")
    else:
        raise ValueError("o Instagram não terminou de processar o vídeo em 10 min")
    etapa[0] = "arriscada"
    media = _json(http("POST", f"{GRAPH_IG}/{user_id}/media_publish",
                       dados={"creation_id": container, "access_token": tok}), "publicação do Reel")["id"]
    try:
        return _json(http("GET", f"{GRAPH_IG}/{media}?{q(fields='permalink')}"), "link do Reel")["permalink"]
    except Exception:  # noqa: BLE001 — já saiu: marca ok sem link em vez de deixar reenviar
        # ponytail: sem link fica sem link; conferir de novo depois se o permalink costumar demorar
        return None
