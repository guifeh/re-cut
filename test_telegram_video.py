import json

import pytest

import contas
import publicar
import recut


@pytest.mark.parametrize("dimensoes", [(1080, 1920), (1920, 1080), (1080, 1080)])
def test_envio_telegram_informa_dimensoes_reais_do_mp4(tmp_path, monkeypatch, dimensoes):
    pasta_contas = tmp_path / "contas"
    contas.salvar("telegram", {"token": "123:TESTE", "bot": "teste_bot", "chat_id": 7}, pasta_contas)
    video = tmp_path / "fonte_corte01.mp4"
    video.write_bytes(b"video")
    corte = video.with_suffix(".json")
    corte.write_text(json.dumps({"arquivo": video.name, "titulo": "Corte", "duracao": 37.2}), encoding="utf-8")
    publicar.aprovar(corte, "Legenda", [], pasta_contas=pasta_contas)
    vistos = []
    monkeypatch.setattr(recut, "tamanho_video", lambda caminho: vistos.append(caminho) or dimensoes)
    chamadas = []

    def http(metodo, url, dados=None, cabecalhos=None, corpo=None, timeout=60):
        chamadas.append({"url": url, "dados": dados, "corpo": corpo})
        return 200, {}, json.dumps({"ok": True, "result": {"message_id": len(chamadas)}}).encode()

    resultado = publicar.enviar(corte, "telegram", http=http, pasta_contas=pasta_contas)

    assert resultado["estado"] == "ok" and resultado["mensagens"] == [1, 2]
    assert vistos == [video]
    multipart = chamadas[0]["corpo"]
    assert f'name="width"\r\n\r\n{dimensoes[0]}\r\n'.encode() in multipart
    assert f'name="height"\r\n\r\n{dimensoes[1]}\r\n'.encode() in multipart
    assert b'name="duration"\r\n\r\n38\r\n' in multipart
    assert b'name="supports_streaming"\r\n\r\ntrue\r\n' in multipart
    assert chamadas[1]["url"].endswith("/sendMessage")


def test_envio_telegram_nao_envia_dimensoes_ilegíveis(tmp_path, monkeypatch):
    pasta_contas = tmp_path / "contas"
    contas.salvar("telegram", {"token": "123:TESTE", "bot": "teste_bot", "chat_id": 7}, pasta_contas)
    video = tmp_path / "fonte_corte01.mp4"
    video.write_bytes(b"video")
    corte = video.with_suffix(".json")
    corte.write_text(json.dumps({"arquivo": video.name, "titulo": "Antigo"}), encoding="utf-8")
    publicar.aprovar(corte, "Legenda", [], pasta_contas=pasta_contas)
    monkeypatch.setattr(recut, "tamanho_video", lambda caminho: (0, 0))
    chamadas = []

    def http(metodo, url, dados=None, cabecalhos=None, corpo=None, timeout=60):
        chamadas.append(corpo)
        return 200, {}, json.dumps({"ok": True, "result": {"message_id": len(chamadas)}}).encode()

    resultado = publicar.enviar(corte, "telegram", http=http, pasta_contas=pasta_contas)

    assert resultado["estado"] == "ok"
    assert b'name="width"' not in chamadas[0]
    assert b'name="height"' not in chamadas[0]
    assert b'name="duration"' not in chamadas[0]
