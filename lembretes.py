"""Consome cortes prontos persistidos e avisa sobre aprovações vencidas no Telegram."""
import datetime as dt
import json
import sys
import threading
import time
from pathlib import Path

import contas
import publicar
import recut
import telegram

PRAZO = dt.timedelta(minutes=10)
INTERVALO = 30
_consumindo = threading.Lock()


def _pendente(arquivo, agora):
    meta = json.loads(arquivo.read_text(encoding="utf-8"))
    if publicar._ler(arquivo).get("aprovado_em"):
        return None
    video = arquivo.with_name(meta["arquivo"])
    if not video.is_file() or not video.stat().st_size:
        return None
    criado = meta.get("criado_em")
    inicio = dt.datetime.fromisoformat(criado).astimezone() if criado else dt.datetime.fromtimestamp(
        arquivo.stat().st_mtime, dt.timezone.utc)
    return meta if agora - inicio >= PRAZO else None


def _registrar(arquivos, estado, agora, conta, reservar=False, **campos):
    registrados = []
    with publicar._trava:
        for arquivo in arquivos:
            if not arquivo.is_file():
                continue
            pub = publicar._ler(arquivo)
            if reservar:
                try:
                    if not _pendente(arquivo, agora):
                        continue
                except (OSError, ValueError, KeyError, TypeError):
                    continue
            pub["lembrete_aprovacao"] = {
                "estado": estado, "em": agora.isoformat(), "bot": conta.get("bot"),
                "chat_id": conta["chat_id"], **campos}
            recut.gravar_json(arquivo.with_suffix(".publicacao"), pub)
            registrados.append(arquivo)
    return registrados


def lembrar(jobs, http=None, pasta=contas.PASTA, agora=None):
    """Uma rodada do consumidor. Retorna quantos avisos foram confirmados pela API."""
    agora = agora or dt.datetime.now(dt.timezone.utc)
    conta = telegram.conta(pasta)
    if not conta.get("token") or not conta.get("chat_id") or not Path(jobs).is_dir():
        return 0
    enviados = 0
    # Uma rodada por processo; o registro em disco mantém a deduplicação após reinícios.
    with _consumindo:
        for job in sorted(Path(jobs).iterdir()):
            if not (job / "job.json").is_file():
                continue
            candidatos = []
            with publicar._trava:
                for arquivo in sorted(job.rglob("*_corte[0-9]*.json")):
                    try:
                        meta = _pendente(arquivo, agora)
                        lembrete = publicar._ler(arquivo).get("lembrete_aprovacao", {})
                        mesma_conta = (lembrete.get("bot"), lembrete.get("chat_id")) == (conta.get("bot"), conta["chat_id"])
                        if mesma_conta and lembrete.get("estado") in ("ok", "enviando", "incerto"):
                            continue
                        if mesma_conta and lembrete.get("tentar_apos") and agora < dt.datetime.fromisoformat(lembrete["tentar_apos"]):
                            continue
                        if meta:
                            candidatos.append((arquivo, meta.get("titulo") or arquivo.stem))
                    except (OSError, ValueError, KeyError, TypeError):
                        continue  # Um arquivo antigo ou incompleto não interrompe os demais.
            # A aprovação é revalidada no mesmo lock que reserva o aviso.
            arquivos = _registrar([f for f, _ in candidatos], "enviando", agora, conta, reservar=True)
            candidatos = [(f, titulo) for f, titulo in candidatos if f in arquivos]
            if not candidatos:
                continue
            titulos = "\n".join(f"• {titulo[:180]}" for _, titulo in candidatos[:10])
            outros = f"\nE mais {len(candidatos) - 10} corte(s)." if len(candidatos) > 10 else ""
            texto = (f"⏳ {len(candidatos)} corte(s) aguardando sua aprovação há pelo menos 10 minutos.\n\n"
                     f"{titulos}{outros}\n\nJob {job.name}\n"
                     "Abra o re-cut no computador → Esteira → Sua aprovação para aprovar ou recusar.")
            try:
                resposta = telegram.chamar(conta["token"], "sendMessage", {"chat_id": conta["chat_id"], "text": texto}, http=http)
                _registrar(arquivos, "ok", agora, conta, message_id=resposta["message_id"])
                enviados += 1
            except telegram.Recusado as erro:
                espera = max(erro.retry_after or 300, INTERVALO)
                _registrar(arquivos, "erro", agora, conta, tentar_apos=(agora + dt.timedelta(seconds=espera)).isoformat())
            except Exception as erro:  # A API pode ter aceitado a mensagem antes de a conexão cair.
                _registrar(arquivos, "incerto", agora, conta)
                print(f"telegram: lembrete sem confirmação ({type(erro).__name__})", file=sys.stderr)
    return enviados


def ouvir(jobs, pasta=contas.PASTA, http=None, dormir=time.sleep, continuar=lambda: True):
    """Worker de prazos separado do long polling das mensagens do Telegram."""
    while continuar():
        try:
            lembrar(jobs, http=http, pasta=pasta)
        except Exception as erro:
            print(f"telegram: worker de aprovação falhou ({type(erro).__name__})", file=sys.stderr)
        dormir(INTERVALO)
