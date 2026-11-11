import asyncio

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

import server
from test_server import JID, envio_falso, esperar_envios, servidor


def chamar(porta, nome, argumentos=None):
    from mcp_recut import criar_mcp

    async def executar():
        async with Client(criar_mcp(porta)) as client:
            return (await client.call_tool(nome, argumentos or {})).data

    return asyncio.run(executar())


def test_mcp_consulta_cortes_do_servidor(servidor):
    resultado = chamar(servidor, "consultar_job", {"job_id": JID})
    assert resultado["job"]["id"] == JID
    assert resultado["job"]["cortes"][0]["json"] == "fonte_corte01.json"


def test_mcp_cria_monitoramento_com_gameplay(servidor, monkeypatch):
    chamadas = []
    monkeypatch.setattr(server, "executar", lambda pasta, args, modo: chamadas.append(args))
    job = chamar(servidor, "criar_job", {"entrada": "https://example.com/live", "modo": "live", "gameplay": True})
    assert job["monitorar"] and job["config"]["gameplay"]
    assert len(chamadas) == 1 and "--monitorar" in chamadas[0] and "--gameplay" in chamadas[0]


def test_mcp_aprovacao_reutiliza_regra_contra_duplicacao(servidor, monkeypatch):
    chamadas = envio_falso(monkeypatch)
    dados = {"job_id": JID, "corte": "fonte_corte01.json", "legenda": "Legenda aprovada", "hashtags": ["teste"]}
    pub = chamar(servidor, "aprovar_corte", dados)
    assert pub["aprovado_em"] and pub["legenda"] == "Legenda aprovada"
    esperar_envios()
    with pytest.raises(ToolError, match="já foi aprovado"):
        chamar(servidor, "aprovar_corte", dados)
    assert sorted(p for p, _ in chamadas) == ["instagram", "youtube"]
