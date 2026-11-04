from datetime import date
from unittest.mock import ANY

from esteira import estado, eventos, resumo_do_dia


def ev(etapa, est, item="v", **kw):
    return {"etapa": etapa, "estado": est, "item": item, "t": "2026-11-04T10:00:00", **kw}


def test_etapa_aberta_roda_so_com_job_vivo():
    evs = [ev("transcrever", "inicio", "v"), ev("transcrever", "progresso", "v", progresso=0.5)]
    assert estado(evs, vivo=True, cortes=[])["nos"]["transcrever"] == {"estado": "rodando", "progresso": 0.5, "itens": ["v"], "msg": ANY}


def test_job_morto_nao_anima():
    no = estado([ev("ia", "inicio", "v")], vivo=False, cortes=[])["nos"]["ia"]
    assert no["estado"] == "erro" and "interrompido" in no["msg"]


def test_cartao_fica_na_etapa_mais_recente_e_aresta_conta():
    evs = [ev("baixar", "fim", "a"), ev("transcrever", "inicio", "a"), ev("baixar", "fim", "b")]
    s = estado(evs, vivo=True, cortes=[])
    assert s["nos"]["transcrever"]["itens"] == ["a"] and s["nos"]["baixar"]["itens"] == ["b"]
    assert s["arestas"]["baixar-transcrever"] == 2


def test_erro_fim_e_ocioso():
    evs = [ev("ia", "inicio"), ev("ia", "erro", msg="falhou"), ev("baixar", "inicio"), ev("baixar", "fim")]
    nos = estado(evs, vivo=True, cortes=[])["nos"]
    assert (nos["ia"]["estado"], nos["ia"]["msg"]) == ("erro", "falhou")
    assert nos["baixar"]["estado"] == "ok" and nos["ranking"]["estado"] == "ocioso"


def test_feed_mais_recente_primeiro_e_limitado():
    evs = [ev("ia", "progresso", f"i{n}", msg=str(n)) for n in range(60)]
    feed = estado(evs, vivo=True, cortes=[])["feed"]
    assert len(feed) == 50 and feed[0] == {"t": ANY, "etapa": "ia", "msg": "59", "estado": "progresso"}


def test_aprovacao_espera_e_ordena_por_nota():
    cortes = [{"nome": "c1", "nota": 7, "publicacao": {}}, {"nome": "c2", "nota": 9, "publicacao": {}}]
    no = estado([], vivo=False, cortes=cortes)["nos"]["aprovacao"]
    assert no["estado"] == "esperando" and no["itens"] == ["c2", "c1"]


def test_publicacao_agrega_por_plataforma():
    pub = {"aprovado_em": "2026-11-04T10:00:00", "plataformas": {"youtube": {"estado": "ok"}, "instagram": {"estado": "incerto"}, "tiktok": {"estado": "manual"}}}
    nos = estado([], vivo=False, cortes=[{"nome": "c", "nota": 8, "publicacao": pub}])["nos"]
    assert (nos["youtube"]["estado"], nos["instagram"]["estado"], nos["tiktok"]["estado"]) == ("ok", "erro", "esperando")


def test_linha_quebrada_no_log_e_ignorada():
    assert eventos('@@ {"etapa": "ia"\nlinha comum\n@@ {"etapa":"ia","estado":"fim","item":"x","t":"2026-11-04T10:00:00"}') == [ANY]


def test_resumo_do_dia():
    hoje = "2026-11-04T10:00:00"
    pub = {"aprovado_em": hoje, "plataformas": {"youtube": {"estado": "ok", "em": hoje}, "instagram": {"estado": "erro", "em": hoje}}}
    cortes = [
        {"nome": "a", "nota": 8, "criado_em": hoje, "publicacao": pub},
        {"nome": "b", "nota": 5, "criado_em": hoje, "publicacao": {}},
        {"nome": "c", "nota": 5, "criado_em": "2026-11-03T09:00:00", "publicacao": {}},
    ]
    assert resumo_do_dia(cortes, date(2026, 11, 4)) == {"cortes": 2, "aprovados": 1, "postados": 1, "erros": 1}


def test_erro_de_um_item_nao_some_com_outro_ok():
    evs = [ev("ia", "inicio", "a"), ev("ia", "erro", "a", msg="x"), ev("ia", "inicio", "b"), ev("ia", "fim", "b")]
    no = estado(evs, vivo=True, cortes=[])["nos"]["ia"]
    assert (no["estado"], no["msg"]) == ("erro", "x")


def test_item_reaberto_e_concluido_limpa_erro():
    evs = [ev("ia", "inicio", "a"), ev("ia", "erro", "a"), ev("ia", "inicio", "a"), ev("ia", "fim", "a")]
    assert estado(evs, vivo=True, cortes=[])["nos"]["ia"]["estado"] == "ok"


def test_progresso_vem_do_item_atualizado_por_ultimo():
    evs = [ev("renderizar", "inicio", "a"), ev("renderizar", "inicio", "b"),
           ev("renderizar", "progresso", "b", progresso=0.3), ev("renderizar", "progresso", "a", progresso=0.8)]
    assert estado(evs, vivo=True, cortes=[])["nos"]["renderizar"]["progresso"] == 0.8


def test_corte_malformado_nao_quebra():
    cortes = [{"nome": "c", "nota": None}, {"nome": "d", "nota": 3, "publicacao": None}]
    nos = estado([], vivo=False, cortes=cortes)["nos"]
    assert nos["aprovacao"]["itens"] == ["d", "c"] and nos["youtube"]["estado"] == "ocioso"
