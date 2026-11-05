import datetime as dt
import json

import pytest

import lixeira


@pytest.fixture
def ambiente(tmp_path):
    jobs, uploads = tmp_path / "jobs", tmp_path / "uploads"
    job = jobs / "20261023-100000-abc123"
    job.mkdir(parents=True)
    uploads.mkdir()
    enviado = uploads / "1a2b3c4d-minha-live.mp4"
    enviado.write_bytes(b"video original")
    (job / "job.json").write_text(json.dumps({"id": job.name, "entrada": str(enviado), "status": "concluido"}))
    for n, nota in ((1, 7.5), (2, 9.0)):
        base = job / f"fonte_corte0{n}"
        base.with_suffix(".json").write_text(json.dumps({"titulo": f"corte {n}", "nota": nota, "duracao": 30}))
        for ext in (".mp4", ".jpg", ".ass"):
            base.with_suffix(ext).write_bytes(b"x" * 10)
    return lixeira.Lixeira(tmp_path / "lixeira", jobs, uploads), job, enviado


def test_excluir_e_restaurar_corte(ambiente):
    lx, job, _ = ambiente
    item = lx.excluir_corte(job / "fonte_corte01.json")
    assert not (job / "fonte_corte01.mp4").exists() and (job / "fonte_corte02.mp4").exists()  # só aquele corte
    assert item["tipo"] == "corte" and item["titulo"] == "corte 1" and item["nota"] == 7.5
    assert sorted(item["arquivos"]) == ["fonte_corte01.ass", "fonte_corte01.jpg", "fonte_corte01.json", "fonte_corte01.mp4"]
    assert [i["id"] for i in lx.listar()] == [item["id"]]
    lx.restaurar(item["id"])
    assert (job / "fonte_corte01.mp4").read_bytes() == b"x" * 10 and lx.listar() == []
    assert [(h["acao"], h["titulo"]) for h in lx.historico()] == [("restaurado", "corte 1"), ("excluido", "corte 1")]


def test_excluir_video_leva_o_arquivo_enviado(ambiente):
    lx, job, enviado = ambiente
    item = lx.excluir_video(job)
    assert not job.exists() and not enviado.exists()
    assert item["titulo"] == "minha-live.mp4" and item["cortes"] == 2
    assert item["thumb"] == "job/fonte_corte02.jpg"  # capa = corte de maior nota
    assert item["tamanho"] > 0
    lx.restaurar(item["id"])
    assert (job / "fonte_corte02.mp4").exists() and enviado.read_bytes() == b"video original"


def test_registro_tem_data_hora_e_o_video(ambiente):
    lx, job, enviado = ambiente
    item = lx.excluir_video(job)
    lx.apagar(item["id"])
    ultimo, primeiro = lx.historico()
    assert ultimo["acao"] == "apagado" and primeiro["acao"] == "excluido"
    assert primeiro["entrada"] == str(enviado) and primeiro["job_id"] == job.name and primeiro["tipo"] == "video"
    dt.datetime.fromisoformat(primeiro["em"])  # data e hora em ISO
    assert lx.listar() == [] and not job.exists()  # apagado de vez


def test_restaurar_com_conflito_ou_sem_o_video(ambiente):
    lx, job, _ = ambiente
    corte = lx.excluir_corte(job / "fonte_corte01.json")
    video = lx.excluir_video(job)
    with pytest.raises(ValueError, match="restaure o vídeo antes"):
        lx.restaurar(corte["id"])
    lx.restaurar(video["id"])
    (job / "fonte_corte01.mp4").write_bytes(b"outro")  # alguém gerou um corte com o mesmo nome
    with pytest.raises(ValueError, match="mesmo nome|já existe"):
        lx.restaurar(corte["id"])
    assert (job / "fonte_corte01.mp4").read_bytes() == b"outro"  # nada sobrescrito


def test_expira_depois_do_prazo(ambiente):
    lx, job, _ = ambiente
    item = lx.excluir_corte(job / "fonte_corte01.json")
    assert lx.expirar(dt.datetime.now()) == []
    depois = dt.datetime.now() + dt.timedelta(days=lixeira.RETENCAO_DIAS, seconds=1)
    assert lx.expirar(depois) == [item["id"]]
    assert lx.historico()[0]["acao"] == "expirado"


def test_id_da_lixeira_nao_sai_da_pasta(ambiente):
    lx, _, _ = ambiente
    for ruim in ("../jobs", "..", "a/b", ""):
        with pytest.raises(FileNotFoundError):
            lx.item(ruim)


def test_upload_compartilhado_fica(ambiente):
    lx, job, enviado = ambiente
    outro = job.parent / "20261023-110000-def456"
    outro.mkdir()
    (outro / "job.json").write_text(json.dumps({"id": outro.name, "entrada": str(enviado)}))
    item = lx.excluir_video(job)
    assert enviado.exists() and item["upload"] is None  # o outro vídeo ainda precisa do arquivo
    lx.restaurar(item["id"])
    assert job.exists() and enviado.exists()


def travar(monkeypatch, quando):
    """Simula o Windows recusando mover um arquivo aberto (WinError 32) quando `quando(origem)` é verdade."""
    original = lixeira.os.replace

    def replace(origem, destino):
        if quando(str(origem)):
            raise PermissionError(32, "O arquivo já está sendo usado por outro processo")
        return original(origem, destino)
    monkeypatch.setattr(lixeira.os, "replace", replace)


def test_upload_travado_nao_deixa_video_orfao(ambiente, monkeypatch):
    lx, job, enviado = ambiente
    travar(monkeypatch, lambda origem: origem.endswith("minha-live.mp4"))
    item = lx.excluir_video(job)
    assert not job.exists() and enviado.exists() and item["upload"] is None  # upload ficou, vídeo foi
    assert [i["id"] for i in lx.listar()] == [item["id"]]  # aparece na lixeira...
    assert lx.historico()[0]["acao"] == "excluido"  # ...e no histórico
    monkeypatch.undo()
    lx.restaurar(item["id"])
    assert (job / "job.json").exists()


def test_restaurar_travado_volta_tudo_para_a_lixeira(ambiente, monkeypatch):
    lx, job, enviado = ambiente
    item = lx.excluir_video(job)
    travar(monkeypatch, lambda origem: origem.endswith("minha-live.mp4"))  # o job volta, o upload não
    with pytest.raises(ValueError, match="restaurar agora"):
        lx.restaurar(item["id"])
    assert not job.exists() and not enviado.exists()  # o job voltou para a lixeira: nada pela metade
    assert [i["id"] for i in lx.listar()] == [item["id"]]
    monkeypatch.undo()
    lx.restaurar(item["id"])
    assert job.exists() and enviado.exists()


def test_apagar_travado_nao_some_da_lista(ambiente, monkeypatch):
    lx, job, _ = ambiente
    item = lx.excluir_corte(job / "fonte_corte01.json")
    travar(monkeypatch, lambda origem: item["id"] in origem)
    with pytest.raises(ValueError, match="apagar agora"):
        lx.apagar(item["id"])
    assert [i["id"] for i in lx.listar()] == [item["id"]] and lx.historico()[0]["acao"] == "excluido"


def test_linha_corrompida_no_historico(ambiente):
    lx, job, _ = ambiente
    lx.excluir_corte(job / "fonte_corte01.json")
    with open(lx.registro, "a", encoding="utf-8") as f:
        f.write('{"em": "2026-10-23T1')  # queda no meio da escrita
    lx.excluir_corte(job / "fonte_corte02.json")
    assert [h["titulo"] for h in lx.historico()] == ["corte 2", "corte 1"]


def test_upload_compartilhado_volta_com_o_video_restaurado(ambiente):
    lx, job, enviado = ambiente
    outro = job.parent / "20261023-110000-def456"
    outro.mkdir()
    (outro / "job.json").write_text(json.dumps({"id": outro.name, "entrada": str(enviado)}))
    primeiro = lx.excluir_video(job)       # o outro ainda usa o upload: fica
    segundo = lx.excluir_video(outro)      # ninguém mais usa: vai com o segundo
    assert not enviado.exists() and segundo["upload"] == str(enviado)
    lx.restaurar(primeiro["id"])           # o primeiro volta e busca o arquivo na pasta do segundo
    assert job.exists() and enviado.read_bytes() == b"video original"
    assert lx.item(segundo["id"])["upload"] is None
    lx.restaurar(segundo["id"])            # o segundo volta sem precisar do arquivo (já está em uploads/)
    assert outro.exists() and enviado.exists()


def test_item_fantasma_some_da_lista(ambiente, monkeypatch):
    lx, job, _ = ambiente
    monkeypatch.setattr(lixeira, "IDADE_FANTASMA", dt.timedelta(0))  # na vida real só depois de 1 min
    # o processo "cai" logo depois de gravar item.json: nada é movido
    os_replace_original = lixeira.os.replace
    def cai_ao_mover(origem, destino):  # item.json (gravado via .tmp) passa; mover o vídeo/corte "derruba" o processo
        if str(origem).endswith(".tmp"):
            return os_replace_original(origem, destino)
        raise KeyboardInterrupt()
    monkeypatch.setattr(lixeira.os, "replace", cai_ao_mover)
    for excluir in (lambda: lx.excluir_video(job), lambda: lx.excluir_corte(job / "fonte_corte01.json")):
        with pytest.raises(KeyboardInterrupt):
            excluir()
    monkeypatch.setattr(lixeira.os, "replace", os_replace_original)
    assert len(list(lx.pasta.glob("*/item.json"))) == 2  # dois fantasmas no disco
    assert lx.listar() == [] and (job / "fonte_corte01.mp4").exists()  # somem da lista; o vídeo segue intacto
    assert lx.historico() == []  # nada foi excluído de verdade, então nada no histórico


def test_devolucao_incompleta_nao_apaga_nada(ambiente, monkeypatch):
    """O cenário da revisão: o .jpg falha ao mover e a devolução do .mp4 também falha (antivírus abriu o arquivo)."""
    lx, job, _ = ambiente
    original = lixeira.os.replace

    def replace(origem, destino):
        origem = str(origem)
        if origem.endswith("fonte_corte01.jpg") or (origem.endswith("fonte_corte01.mp4") and "lixeira" in origem):
            raise PermissionError(32, "em uso")
        return original(origem, destino)
    monkeypatch.setattr(lixeira.os, "replace", replace)
    with pytest.raises(ValueError, match="movido só em parte"):
        lx.excluir_corte(job / "fonte_corte01.json")
    monkeypatch.undo()
    itens = lx.listar()
    assert len(itens) == 1  # o item ficou: o .mp4 só existe na lixeira
    mp4_na_lixeira = lx.pasta / itens[0]["id"] / "corte" / "fonte_corte01.mp4"
    assert mp4_na_lixeira.read_bytes() == b"x" * 10 and (job / "fonte_corte01.jpg").exists()
    lx.restaurar(itens[0]["id"])  # restaura só o que está na lixeira; o resto já estava no lugar
    assert all((job / f"fonte_corte01{ext}").exists() for ext in (".mp4", ".jpg", ".json", ".ass"))
    assert lx.listar() == []


def test_pasta_apagando_nao_vira_item(ambiente):
    lx, job, _ = ambiente
    item = lx.excluir_corte(job / "fonte_corte01.json")
    os_pasta = lx.pasta / item["id"]
    os_pasta.rename(lx.pasta / (lixeira.APAGANDO + item["id"]))  # sobra de um apagar interrompido
    assert lx.listar() == []
    with pytest.raises(FileNotFoundError):
        lx.item(lixeira.APAGANDO + item["id"])


def test_video_restaurado_em_parte_termina_depois(ambiente, monkeypatch):
    """Restaurar: o job volta, o upload trava e a devolução do job também falha. Nada some e dá para terminar."""
    lx, job, enviado = ambiente
    item = lx.excluir_video(job)
    original = lixeira.os.replace

    def replace(origem, destino):
        origem = str(origem)
        if origem.endswith("minha-live.mp4") or (origem.endswith(job.name) and "jobs" in origem):
            raise PermissionError(32, "em uso")  # upload travado; devolver o job para a lixeira também falha
        return original(origem, destino)
    monkeypatch.setattr(lixeira.os, "replace", replace)
    with pytest.raises(ValueError, match="restaurar agora"):
        lx.restaurar(item["id"])
    monkeypatch.undo()
    assert job.exists() and not enviado.exists()  # job voltou, upload ainda na lixeira...
    assert [i["id"] for i in lx.listar()] == [item["id"]]  # ...e o item não é tratado como fantasma
    lx.restaurar(item["id"])  # termina: traz só o upload
    assert enviado.read_bytes() == b"video original" and lx.listar() == []


def test_tirar_da_lista_nunca_apaga_arquivo(tmp_path):
    pasta = tmp_path / "item"
    (pasta / "corte").mkdir(parents=True)
    (pasta / "item.json").write_text("{}")
    (pasta / "corte" / "unica-copia.mp4").write_bytes(b"x")
    assert lixeira.Lixeira._tirar_da_lista(pasta) is False and (pasta / "corte" / "unica-copia.mp4").exists()
    (pasta / "corte" / "unica-copia.mp4").unlink()
    assert lixeira.Lixeira._tirar_da_lista(pasta) is True and not pasta.exists()


def test_listar_durante_exclusao_nao_apaga_o_video(ambiente, monkeypatch):
    """A corrida da revisão: GET /api/lixeira chega entre gravar item.json e mover a pasta do vídeo."""
    import threading
    lx, job, _ = ambiente
    monkeypatch.setattr(lixeira, "IDADE_FANTASMA", dt.timedelta(0))  # sem a folga de idade: testa só o lock
    original, no_meio, segue = lixeira.os.replace, threading.Event(), threading.Event()

    def replace(origem, destino):
        if str(origem) == str(job):
            no_meio.set()
            segue.wait(5)
        return original(origem, destino)
    monkeypatch.setattr(lixeira.os, "replace", replace)
    excluindo = threading.Thread(target=lx.excluir_video, args=(job,))
    excluindo.start()
    assert no_meio.wait(5)
    listagem = []
    listando = threading.Thread(target=lambda: listagem.append(lx.listar()))
    listando.start()
    listando.join(0.3)  # bloqueado no lock enquanto a exclusão não termina
    segue.set()
    excluindo.join(5)
    listando.join(5)
    item = listagem[0][0]
    assert (lx.pasta / item["id"] / "job" / "fonte_corte01.mp4").exists()  # o vídeo está inteiro na lixeira
    lx.restaurar(item["id"])
    assert (job / "fonte_corte01.mp4").exists()


def test_restaurar_com_upload_ja_existente_nao_descarta_a_copia(ambiente):
    lx, job, enviado = ambiente
    item = lx.excluir_video(job)
    enviado.write_bytes(b"outro arquivo com o mesmo nome")
    with pytest.raises(ValueError, match="mesmo nome em uploads"):
        lx.restaurar(item["id"])
    assert (lx.pasta / item["id"] / "upload" / enviado.name).read_bytes() == b"video original"


def test_apagar_de_vez_nao_leva_o_upload_de_outro_video(ambiente):
    lx, job, enviado = ambiente
    outro = job.parent / "20261023-110000-def456"
    outro.mkdir()
    (outro / "job.json").write_text(json.dumps({"id": outro.name, "entrada": str(enviado)}))
    a = lx.excluir_video(job)    # B ainda usa o upload: fica em uploads/
    b = lx.excluir_video(outro)  # agora ninguém usa: o arquivo vai com B
    lx.apagar(b["id"])           # apagar B de vez não pode levar o original de A
    assert (lx.pasta / a["id"] / "upload" / enviado.name).read_bytes() == b"video original"
    assert lx.item(a["id"])["upload"] == str(enviado)
    lx.restaurar(a["id"])
    assert enviado.read_bytes() == b"video original" and job.exists()


def test_item_editado_a_mao_nao_derruba_a_lista(ambiente):
    lx, job, _ = ambiente
    item = lx.excluir_corte(job / "fonte_corte01.json")
    caminho = lx.pasta / item["id"] / "item.json"
    dados = json.loads(caminho.read_text())
    del dados["excluido_em"]
    caminho.write_text(json.dumps(dados))
    assert [i["id"] for i in lx.listar()] == [item["id"]]


def test_publicacao_vai_junto_para_a_lixeira(ambiente):
    lx, job, _ = ambiente
    (job / "fonte_corte01.publicacao").write_text("{}")
    item = lx.excluir_corte(job / "fonte_corte01.json")
    assert not (job / "fonte_corte01.publicacao").exists() and "fonte_corte01.publicacao" in item["arquivos"]
    lx.restaurar(item["id"])
    assert (job / "fonte_corte01.publicacao").exists()
