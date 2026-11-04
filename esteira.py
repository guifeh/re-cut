"""Estado da esteira derivado dos eventos '@@ {...}' do log do job. Funções puras, sem I/O."""
import json
from datetime import date

from recut import ETAPAS, PREFIXO_EVENTO

PLATAFORMAS = ("youtube", "instagram", "tiktok")
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


def _etapa(evs_etapa, aberto, vivo):
    """aberto: {item: progresso} dos itens com inicio sem fim/erro."""
    msg = next((e["msg"] for e in reversed(evs_etapa) if e.get("msg")), "")
    if aberto:
        if not vivo:
            return "erro", None, "interrompido"
        return "rodando", list(aberto.values())[-1], msg
    if not evs_etapa:
        return "ocioso", None, ""
    if evs_etapa[-1].get("estado") == "erro":
        return "erro", None, msg
    return ("ok" if any(e.get("estado") == "fim" for e in evs_etapa) else "ocioso"), None, msg


def _plataforma(p, aprovados):
    posts = [(c["nome"], c["publicacao"].get("plataformas", {}).get(p)) for c in aprovados]
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
    atual = {}                         # item -> etapa do evento mais recente
    for ev in evs:
        etapa, est, item = ev.get("etapa"), ev.get("estado"), ev.get("item", "")
        if etapa not in por_etapa:
            continue
        por_etapa[etapa].append(ev)
        atual.pop(item, None)  # reinsere: ordem = chegada na etapa
        atual[item] = etapa
        if est == "inicio":
            aberto[etapa][item] = None
        elif est == "progresso":
            if item in aberto[etapa] and "progresso" in ev:
                aberto[etapa][item] = ev["progresso"]
        elif est in ("fim", "erro"):
            aberto[etapa].pop(item, None)
            if est == "fim":
                fins[etapa].add(item)

    nos = {}
    for etapa in ETAPAS:
        est, prog, msg = _etapa(por_etapa[etapa], aberto[etapa], vivo)
        nos[etapa] = _no(est, prog, [i for i, e in atual.items() if e == etapa], msg)

    pendentes = sorted((c for c in cortes if not c["publicacao"].get("aprovado_em")), key=lambda c: -c["nota"])
    aprovados = [c for c in cortes if c["publicacao"].get("aprovado_em")]
    nos["aprovacao"] = _no("esperando" if pendentes else ("ok" if aprovados else "ocioso"), None, [c["nome"] for c in pendentes])
    for p in PLATAFORMAS:
        nos[p] = _plataforma(p, aprovados)

    arestas = {f"{a}-{b}": len(fins[a]) for a, b in zip(ETAPAS, ETAPAS[1:])}
    arestas["ranking-aprovacao"] = len(cortes)
    for p in PLATAFORMAS:
        arestas[f"aprovacao-{p}"] = len(nos[p]["itens"])

    feed = [{"t": e.get("t"), "etapa": e.get("etapa"), "msg": e.get("msg", ""), "estado": e.get("estado")} for e in reversed(evs[-50:])]
    return {"nos": nos, "arestas": arestas, "feed": feed}


def resumo_do_dia(cortes: list[dict], hoje: date) -> dict:
    """cortes: criados no dia; aprovados: aprovados no dia; postados: plataformas com estado ok e `em`
    no dia; erros: plataformas em erro/incerto entre os cortes aprovados no dia."""
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
