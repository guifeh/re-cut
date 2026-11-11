"""Ferramentas MCP do re-cut sobre a API HTTP local."""
import json
import os
from http.client import HTTPConnection, HTTPException
from typing import Literal
from urllib.parse import quote, urlsplit

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError


def pedir(porta, caminho, dados=None):
    conexao = HTTPConnection("127.0.0.1", porta, timeout=15)
    try:
        corpo = json.dumps(dados).encode() if dados is not None else None
        metodo = "POST" if corpo is not None else "GET"
        conexao.request(metodo, caminho, corpo, {"Content-Type": "application/json"})
        resposta = conexao.getresponse()
        resultado = json.load(resposta)
    except (OSError, HTTPException, ValueError) as erro:
        mensagem = "Não foi possível obter resposta do re-cut local."
        if dados is not None:
            mensagem += " Consulte o job antes de repetir a operação."
        raise ToolError(mensagem) from erro
    finally:
        conexao.close()
    if not 200 <= resposta.status < 300:
        raise ToolError(resultado.get("erro") or f"re-cut retornou HTTP {resposta.status}")
    return resultado


def criar_mcp(porta=8000):
    mcp = FastMCP("re-cut")

    def job_path(job_id):
        return f"/api/jobs/{quote(job_id, safe='')}"

    @mcp.tool
    def listar_jobs() -> list[dict]:
        """Lista jobs e seus cortes, com status e registros de publicação."""
        return pedir(porta, "/api/jobs")

    @mcp.tool
    def consultar_job(job_id: str) -> dict:
        """Consulta o job, os cortes e o andamento na esteira."""
        return pedir(porta, f"/api/esteira/{quote(job_id, safe='')}")

    @mcp.tool
    def listar_templates() -> list[dict]:
        """Lista os templates disponíveis para criar jobs ou renderizar cortes de novo."""
        return pedir(porta, "/api/templates")

    @mcp.tool
    def listar_estrategias() -> list[dict]:
        """Lista as estratégias de corte salvas."""
        return pedir(porta, "/api/estrategias")

    @mcp.tool
    def criar_job(entrada: str, modo: Literal["video", "live"], template: str = "classico",
                  gameplay: bool = False, estrategia: str = "", dur_min: int = 15,
                  dur_max: int = 90, limite: int = 10, nota_min: float = 6) -> dict:
        """Processa uma URL de vídeo/VOD ou inicia a monitoração de uma live. Confirme o modo com o usuário."""
        url = urlsplit(entrada.strip())
        if url.scheme not in ("http", "https") or not url.hostname:
            raise ToolError("informe uma URL HTTP ou HTTPS")
        if not 0 < dur_min <= dur_max or limite < 1:
            raise ToolError("informe durações válidas e um limite de pelo menos um corte")
        return pedir(porta, "/api/jobs", {
            "entrada": entrada.strip(), "monitorar": modo == "live", "template": template,
            "gameplay": gameplay, "estrategia": estrategia, "dur_min": dur_min,
            "dur_max": dur_max, "limite": limite, "nota_min": nota_min,
        })

    @mcp.tool
    def parar_job(job_id: str) -> dict:
        """Para um job ou a monitoração de uma live a pedido do usuário."""
        return pedir(porta, f"{job_path(job_id)}/parar", {})

    @mcp.tool
    def reaplicar_template(job_id: str, template: str, cortes: list[str] | None = None) -> dict:
        """Renderiza novamente os cortes indicados pelo campo json. Sem seleção, reaplica ao job inteiro."""
        return pedir(porta, f"{job_path(job_id)}/aplicar_template", {"template": template, "cortes": cortes})

    @mcp.tool
    def recusar_corte(job_id: str, corte: str) -> dict:
        """Move para a lixeira o corte indicado pelo campo json, a pedido do usuário."""
        return pedir(porta, f"{job_path(job_id)}/cortes/excluir", {"json": corte})

    @mcp.tool
    def aprovar_corte(job_id: str, corte: str, legenda: str, hashtags: list[str]) -> dict:
        """Aprova o corte e aciona a publicação existente do re-cut. Use após aprovação explícita do usuário."""
        return pedir(porta, f"{job_path(job_id)}/cortes/aprovar",
                     {"json": corte, "legenda": legenda, "hashtags": hashtags})

    @mcp.tool
    def enviar_corte(job_id: str, corte: str, plataforma: Literal["youtube", "telegram"],
                     publish_at: str | None = None, forcar: bool = False) -> dict:
        """Envia um corte ao destino autorizado. No YouTube, publish_at é uma data futura ISO 8601 com fuso.
        Use forcar somente se o usuário autorizar o reenvio de um corte já enviado ou com resultado incerto."""
        return pedir(porta, f"{job_path(job_id)}/cortes/enviar",
                     {"json": corte, "plataforma": plataforma, "publish_at": publish_at, "forcar": forcar})

    return mcp


if __name__ == "__main__":
    criar_mcp(int(os.getenv("RECUT_PORT", "8000"))).run(transport="stdio", show_banner=False)
