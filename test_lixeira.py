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
