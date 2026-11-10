import datetime as dt
import json
import threading

import pytest

import contas
import lembretes
import publicar
import recut

AGORA = dt.datetime(2026, 11, 8, 15, tzinfo=dt.timezone.utc)


@pytest.fixture
def ambiente(tmp_path):
    jobs = tmp_path / "jobs"
    job = jobs / "j1"
    job.mkdir(parents=True)
    (job / "job.json").write_text("{}")
    pasta = tmp_path / "contas"
    contas.salvar("telegram", {"token": "123:SEGREDO", "chat_id": 7, "bot": "teste_bot"}, pasta)
    return jobs, pasta


def corte(jobs, nome="fonte_corte01", minutos=11, aprovado=False, pronto=True):
    f = jobs / "j1" / f"{nome}.json"
    f.write_text(json.dumps({"arquivo": f"{nome}.mp4", "titulo": nome,
                            "criado_em": (AGORA - dt.timedelta(minutes=minutos)).isoformat()}))
    f.with_suffix(".mp4").write_bytes(b"video" if pronto else b"")
    if aprovado:
        f.with_suffix(".publicacao").write_text(json.dumps({"aprovado_em": AGORA.isoformat()}))
    return f


class HTTP:
    def __init__(self, status=200, erro=None):
        self.chamadas = []
        self.status = status
        self.erro = erro

    def __call__(self, metodo, url, dados=None, cabecalhos=None, corpo=None, timeout=60):
        self.chamadas.append(dados)
        if self.erro:
            raise self.erro
        resposta = {"ok": self.status == 200, "result": {"message_id": 42}, "description": "recusado"}
        return self.status, {}, json.dumps(resposta).encode()


def registro(f):
    return json.loads(f.with_suffix(".publicacao").read_text())


def test_avisa_apos_dez_minutos_uma_vez_por_corte(ambiente):
    jobs, pasta = ambiente
    f = corte(jobs, minutos=9)
    http = HTTP()
    assert lembretes.lembrar(jobs, http, pasta, AGORA) == 0
    assert lembretes.lembrar(jobs, http, pasta, AGORA + dt.timedelta(minutes=1)) == 1
    assert lembretes.lembrar(jobs, http, pasta, AGORA + dt.timedelta(hours=1)) == 0
    assert len(http.chamadas) == 1
    assert "aprovar ou recusar" in http.chamadas[0]["text"]
    pub = registro(f)
    assert pub["lembrete_aprovacao"]["message_id"] == 42
    assert not pub.get("aprovado_em") and not pub.get("plataformas")


def test_aprovado_recusado_ou_video_incompleto_nao_recebe_aviso(ambiente):
    jobs, pasta = ambiente
    corte(jobs, aprovado=True)
    f = corte(jobs, "fonte_corte02")
    f.unlink()  # A recusa move o JSON para fora de jobs.
    corte(jobs, "fonte_corte03", pronto=False)
    http = HTTP()
    assert lembretes.lembrar(jobs, http, pasta, AGORA) == 0
    assert http.chamadas == []


def test_agrupa_cortes_do_mesmo_job_e_preserva_estado(ambiente):
    jobs, pasta = ambiente
    f = corte(jobs)
    corte(jobs, "fonte_corte02")
    estado = {"telegram": {"estado": "ok", "mensagens": [1, 2]}, "legenda": "legenda"}
    recut.gravar_json(f.with_suffix(".publicacao"), estado)
    http = HTTP()
    assert lembretes.lembrar(jobs, http, pasta, AGORA) == 1
    assert "2 corte(s)" in http.chamadas[0]["text"]
    assert "fonte_corte01" in http.chamadas[0]["text"] and "fonte_corte02" in http.chamadas[0]["text"]
    assert registro(f)["telegram"] == estado["telegram"]
    assert registro(f)["legenda"] == "legenda"


def test_lembrete_persistido_nao_repete_apos_reinicio(ambiente):
    jobs, pasta = ambiente
    f = corte(jobs)
    lembretes.lembrar(jobs, HTTP(), pasta, AGORA)
    http = HTTP()
    assert lembretes.lembrar(jobs, http, pasta, AGORA + dt.timedelta(days=1)) == 0
    assert registro(f)["lembrete_aprovacao"]["estado"] == "ok"


def test_falha_incerta_nao_duplica_mensagem(ambiente):
    jobs, pasta = ambiente
    f = corte(jobs)
    http = HTTP(erro=TimeoutError("rede"))
    lembretes.lembrar(jobs, http, pasta, AGORA)
    assert registro(f)["lembrete_aprovacao"]["estado"] == "incerto"
    assert lembretes.lembrar(jobs, http, pasta, AGORA + dt.timedelta(hours=1)) == 0
    assert len(http.chamadas) == 1


def test_recusa_http_reagenda_tentativa_sem_marcar_aprovacao(ambiente):
    jobs, pasta = ambiente
    f = corte(jobs)
    assert lembretes.lembrar(jobs, HTTP(status=429), pasta, AGORA) == 0
    assert registro(f)["lembrete_aprovacao"]["estado"] == "erro"
    http = HTTP()
    assert lembretes.lembrar(jobs, http, pasta, AGORA + dt.timedelta(seconds=30)) == 0
    assert lembretes.lembrar(jobs, http, pasta, AGORA + dt.timedelta(minutes=5)) == 1


def test_sem_telegram_pareado_nao_muda_estado(ambiente):
    jobs, pasta = ambiente
    f = corte(jobs)
    contas.salvar("telegram", {"token": "123:SEGREDO"}, pasta)
    assert lembretes.lembrar(jobs, HTTP(), pasta, AGORA) == 0
    assert not f.with_suffix(".publicacao").exists()


def test_aprovacao_entre_varredura_e_reserva_cancela_aviso(ambiente, monkeypatch):
    jobs, pasta = ambiente
    f = corte(jobs)
    original = lembretes._registrar

    def aprovar_antes_da_reserva(arquivos, estado, agora, conta, **campos):
        recut.gravar_json(f.with_suffix(".publicacao"), {"aprovado_em": AGORA.isoformat()})
        return original(arquivos, estado, agora, conta, **campos)

    monkeypatch.setattr(lembretes, "_registrar", aprovar_antes_da_reserva)
    http = HTTP()
    assert lembretes.lembrar(jobs, http, pasta, AGORA) == 0
    assert http.chamadas == []


def test_duas_rodadas_concorrentes_enviam_uma_vez(ambiente):
    jobs, pasta = ambiente
    corte(jobs)
    http = HTTP()
    threads = [threading.Thread(target=lembretes.lembrar, args=(jobs, http, pasta, AGORA)) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert len(http.chamadas) == 1


def test_worker_continua_apos_falha_sem_expor_segredo(ambiente, monkeypatch, capsys):
    jobs, pasta = ambiente
    chamadas = []

    def falhar(*args, **kwargs):
        chamadas.append(True)
        raise ValueError("123:SEGREDO")

    monkeypatch.setattr(lembretes, "lembrar", falhar)
    dormidas = []
    lembretes.ouvir(jobs, pasta=pasta, dormir=dormidas.append, continuar=lambda: len(chamadas) < 2)
    assert dormidas == [30, 30]
    assert "SEGREDO" not in capsys.readouterr().err


def test_video_removido_entre_varredura_e_reserva_nao_dispara(ambiente, monkeypatch):
    jobs, pasta = ambiente
    f = corte(jobs)
    original = lembretes._registrar

    def recusar_antes_da_reserva(arquivos, estado, agora, conta, **campos):
        f.with_suffix(".mp4").unlink()
        return original(arquivos, estado, agora, conta, **campos)

    monkeypatch.setattr(lembretes, "_registrar", recusar_antes_da_reserva)
    http = HTTP()
    assert lembretes.lembrar(jobs, http, pasta, AGORA) == 0
    assert not http.chamadas
