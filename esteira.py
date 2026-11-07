"""Estado da esteira derivado dos eventos '@@ {...}' do log do job. Funções puras, sem I/O."""
import json
from datetime import date

import contas
from recut import ETAPAS, PREFIXO_EVENTO

PLATAFORMAS = contas.PLATAFORMAS + ("tiktok",)  # TikTok é manual: sem conta, o link é colado
NOMES = {"youtube": "YouTube", "instagram": "Instagram", "tiktok": "TikTok"}
NOS = ETAPAS + ("aprovacao",) + PLATAFORMAS


def eventos(log: str) -> list[dict]:
    """Eventos do log; linhas sem o prefixo ou com JSON inválido são ignoradas."""
    evs = []
    for linha in log.splitlines():
        if not linha.startswith(PREFIXO_EVENTO):
            continue
        try:
            e = json.loads(linha[len(PREFIXO_EVENTO):])
        except ValueError:
            continue
        if isinstance(e, dict):
            evs.append(e)
    return evs


def _no(estado="ocioso", progresso=None, itens=(), msg=""):
    return {"estado": estado, "progresso": progresso, "itens": list(itens), "msg": msg}


def _etapa(evs_etapa, aberto, term, vivo):
    """aberto: {item: progresso} dos itens com inicio sem fim/erro (último atualizado por último);
    term: {item: (estado, msg)} do último fim/erro de cada item."""
    msg = next((e["msg"] for e in reversed(evs_etapa) if e.get("msg")), "")
    if aberto:
        if not vivo:
            return "erro", None, "interrompido"
        return "rodando", list(aberto.values())[-1], msg
    erros = [m for est, m in term.values() if est == "erro"]
    if erros:
        return "erro", None, erros[-1] or msg
    return ("ok" if term else "ocioso"), None, msg


def _plataforma(p, aprovados):
    posts = [(c["nome"], (c.get("publicacao") or {}).get("plataformas", {}).get(p)) for c in aprovados]
    posts = [(n, x) for n, x in posts if x]
    sts = [x.get("estado") for _, x in posts]
    if "enviando" in sts:
        est = "rodando"
    elif "erro" in sts or "incerto" in sts:
        est = "erro"
    elif p == "tiktok" and "manual" in sts:
        est = "esperando"
    elif sts and all(s == "ok" for s in sts):
        est = "ok"
    else:
        est = "ocioso"
    return _no(est, None, [n for n, _ in posts])


def estado(evs: list[dict], vivo: bool, cortes: list[dict]) -> dict:
    por_etapa = {e: [] for e in ETAPAS}
    aberto = {e: {} for e in ETAPAS}   # etapa -> {item: último progresso}
    fins = {e: set() for e in ETAPAS}  # etapa -> itens com fim
    term = {e: {} for e in ETAPAS}     # etapa -> {item: (estado, msg)} do último fim/erro
    atual = {}                         # item -> etapa do evento mais recente
    for ev in evs:
        etapa, est, item = ev.get("etapa"), ev.get("estado"), ev.get("item", "")
        if etapa not in por_etapa:
            continue
        por_etapa[etapa].append(ev)
        # item vazio (a entrada do job) conta para o estado do nó, mas não é cartão. O cartão só anda para a
        # frente (logs antigos marcavam ranking antes de renderizar) ou recomeça em transcrever: numa live a
        # transmissão seguinte repete os nomes dos lotes (lote_0000 de novo)
        recomeca = (etapa, est) == ("transcrever", "inicio")
        if item and (recomeca or ETAPAS.index(etapa) >= ETAPAS.index(atual.get(item, etapa))):
            atual.pop(item, None)  # reinsere: ordem = chegada na etapa
            atual[item] = etapa
        if est == "inicio":
            aberto[etapa].pop(item, None)
            aberto[etapa][item] = None
        elif est == "progresso":
            if item in aberto[etapa] and "progresso" in ev:
                aberto[etapa].pop(item)
                aberto[etapa][item] = ev["progresso"]
        elif est in ("fim", "erro"):
            aberto[etapa].pop(item, None)
            term[etapa].pop(item, None)
            term[etapa][item] = (est, ev.get("msg", ""))
            if est == "fim":
                fins[etapa].add(item)

    nos = {}
    for etapa in ETAPAS:
        est, prog, msg = _etapa(por_etapa[etapa], aberto[etapa], term[etapa], vivo)
        nos[etapa] = _no(est, prog, [i for i, e in atual.items() if e == etapa], msg)

    pub = lambda c: c.get("publicacao") or {}
    pendentes = sorted((c for c in cortes if not pub(c).get("aprovado_em")), key=lambda c: -(c.get("nota") or 0))
    aprovados = [c for c in cortes if pub(c).get("aprovado_em")]
    nos["aprovacao"] = _no("esperando" if pendentes else ("ok" if aprovados else "ocioso"), None, [c["nome"] for c in pendentes])
    for p in PLATAFORMAS:
        nos[p] = _plataforma(p, aprovados)

    arestas = {f"{a}-{b}": len(fins[a]) for a, b in zip(ETAPAS, ETAPAS[1:])}
    arestas["ranking-aprovacao"] = len(cortes)
    for p in PLATAFORMAS:
        arestas[f"aprovacao-{p}"] = len(nos[p]["itens"])

    marcos = [{"t": e.get("t"), "etapa": e.get("etapa"), "msg": e.get("msg", ""), "estado": e.get("estado")}
              for e in evs if e.get("estado") != "progresso"]  # progresso inundaria as 50 linhas
    feed = sorted(marcos + _feed_publicacao(aprovados), key=lambda f: f["t"] or "")  # estável: empate fica na ordem do log
    return {"nos": nos, "arestas": arestas, "feed": feed[-50:][::-1]}


def _feed_publicacao(aprovados):
    """Uma linha por aprovação e pelo estado atual de cada plataforma (o arquivo guarda só a última mudança)."""
    linhas = []
    for c in aprovados:
        pub, nome = c["publicacao"], c.get("titulo") or c["nome"]
        linhas.append({"t": pub["aprovado_em"], "etapa": "aprovacao", "msg": f"Corte {nome} aprovado", "estado": "fim"})
        for p, x in (pub.get("plataformas") or {}).items():
            est = (x or {}).get("estado")
            if not (x or {}).get("em"):
                continue
            if est == "ok":
                msg = "Link do TikTok salvo" if p == "tiktok" else f"Postado no {NOMES.get(p, p)}"
            elif est in ("erro", "incerto"):
                msg = x.get("erro") or est
            else:
                continue
            linhas.append({"t": x["em"], "etapa": p, "msg": f"{msg} · {nome}", "estado": "fim" if est == "ok" else "erro"})
        tg = pub.get("telegram") or {}  # fora de `plataformas`: sem nó próprio, entra na etapa do TikTok
        if tg.get("em") and tg.get("estado") in ("ok", "erro", "incerto"):
            ok = tg["estado"] == "ok"
            msg = "Enviado ao Telegram" if ok else f"Telegram: {tg.get('erro') or tg['estado']}"
            linhas.append({"t": tg["em"], "etapa": "tiktok", "msg": f"{msg} · {nome}", "estado": "fim" if ok else "erro"})
    return linhas


def resumo_do_dia(cortes: list[dict], hoje: date) -> dict:
    """Contagens de "Hoje" na Esteira (os rótulos da tela entre aspas):
    cortes ("Cortes gerados"): cortes com criado_em no dia;
    aprovados ("Cortes aprovados"): cortes com aprovado_em no dia;
    postados ("Posts publicados"): posts, um por plataforma, com estado ok e `em` no dia (TikTok conta ao colar o link);
    erros ("Erros de publicação"): plataformas em erro/incerto entre os cortes aprovados no dia."""
    d = hoje.isoformat()
    pubs = [c.get("publicacao") or {} for c in cortes]
    do_dia = [p for p in pubs if str(p.get("aprovado_em", ""))[:10] == d]
    plats = [x for p in pubs for x in p.get("plataformas", {}).values()]
    return {
        "cortes": sum(str(c.get("criado_em", ""))[:10] == d for c in cortes),
        "aprovados": len(do_dia),
        "postados": sum(x.get("estado") == "ok" and str(x.get("em", ""))[:10] == d for x in plats),
        "erros": sum(x.get("estado") in ("erro", "incerto") for p in do_dia for x in p.get("plataformas", {}).values()),
    }
