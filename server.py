"""API HTTP do re-cut + frontend buildado. python server.py -> http://localhost:8000

Cada job roda `recut.py` num subprocesso: o log é o stdout, os cortes são os .json que ele grava,
e parar um monitoramento é encerrar o processo.
"""
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import recut
import lixeira as lixeira_mod
from lixeira import Lixeira

RAIZ = Path(__file__).parent
JOBS = RAIZ / "jobs"
UPLOADS = RAIZ / "uploads"
DIST = RAIZ / "frontend" / "dist"
PORTA = int(os.getenv("PORT", "8000"))
MAX_UPLOAD = 20 * 1024 ** 3  # 20 GB
LIXEIRA = RAIZ / "lixeira"
ARQUIVOS_SERVIDOS = (".mp4", ".jpg", ".png")  # /files só entrega mídia; .json e o registro têm caminhos locais
lixeira = Lixeira(LIXEIRA, JOBS, UPLOADS)

processos = {}  # id (ou id + REAPLICANDO) -> Popen; só os desta execução do servidor
REAPLICANDO = ":reaplicar"  # chave à parte: reaplicar template não espera nem mexe no status do job (ex.: live rodando)
CORTES_GLOB = "*_corte[0-9]*.json"
lock = threading.Lock()


def meta(job_dir):
    return json.loads((job_dir / "job.json").read_text(encoding="utf-8"))


def salvar_meta(job_dir, dados):
    (job_dir / "job.json").write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


def resumo(job_dir, com_log=False):
    m = meta(job_dir)
    with lock:
        p = processos.get(m["id"])
        m["reaplicando"] = m["id"] + REAPLICANDO in processos
    if m["status"] == "rodando" and p is None:  # servidor reiniciou no meio do job
        m["status"] = "interrompido"
    cortes = []
    for f in job_dir.rglob(CORTES_GLOB):
        c = json.loads(f.read_text(encoding="utf-8"))
        c["reaplicavel"] = c.pop("palavras", None) is not None  # cortes antigos não guardavam as palavras
        c.pop("fonte", None)
        rel = f.parent.relative_to(RAIZ).as_posix()
        versao = int(f.stat().st_mtime)
        c["json"] = f.relative_to(job_dir).as_posix()
        c["video_url"] = f"/files/{rel}/{c['arquivo']}?v={versao}"
        c["thumb_url"] = f"/files/{rel}/{c['thumbnail']}?v={versao}"
        cortes.append(c)
    m["cortes"] = sorted(cortes, key=lambda c: -c["nota"])
    log = (job_dir / "log.txt").read_text(encoding="utf-8", errors="replace") if (job_dir / "log.txt").exists() else ""
    m["log"] = log[-20000:] if com_log else log.strip().splitlines()[-1:] or [""]
    return m


def criar_job(dados):
    entrada = str(dados.get("entrada", "")).strip()
    if not entrada:
        raise ValueError("informe uma URL ou envie um arquivo")
    if not re.match(r"https?://", entrada) and not Path(entrada).resolve().is_relative_to(UPLOADS.resolve()):
        raise ValueError("arquivo local só pode vir de um upload")  # não deixa a API ler qualquer caminho do disco
    if dados.get("monitorar") and not re.match(r"https?://", entrada):
        raise ValueError("monitoramento precisa da URL do canal")
    if dados.get("template"):
        recut.carregar_template(dados["template"])  # ValueError se não existe ou é inválido
    jid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    job_dir = JOBS / jid
    job_dir.mkdir(parents=True)
    args = [sys.executable, "-u", str(RAIZ / "recut.py"), entrada, "--saida", str(job_dir)]
    if dados.get("monitorar"):
        args.append("--monitorar")
    for chave, flag in [("estrategia", "--estrategia"), ("nota_min", "--nota-min"), ("limite", "--limite-por-lote"),
                        ("dur_min", "--dur-min"), ("dur_max", "--dur-max"), ("webhook", "--webhook"),
                        ("template", "--template")]:
        if dados.get(chave) not in (None, ""):
            args += [flag, str(dados[chave])]
    for chave in ("dias", "horas"):
        if dados.get(chave):
            args += [f"--{chave}", ",".join(str(int(x)) for x in dados[chave])]
    m = {"id": jid, "entrada": entrada, "monitorar": bool(dados.get("monitorar")), "status": "rodando",
         "criado_em": time.strftime("%Y-%m-%dT%H:%M:%S"), "config": {k: v for k, v in dados.items() if k != "entrada"}}
    salvar_meta(job_dir, m)
    executar(job_dir, args, "a")  # "a" (O_APPEND): a reaplicação escreve no mesmo log sem sobrescrever linhas
    return m


def executar(job_dir, args, modo_log, chave=None):
    """Roda recut.py em subprocesso com o log em log.txt. Sem `chave` é o job principal e o status é
    atualizado no fim; com `chave` (reaplicação) o status do job não é tocado."""
    jid = chave or job_dir.name
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    with lock:  # checar e registrar sob o mesmo lock: duas requisições juntas não disparam dois processos
        if jid in processos:
            raise ValueError("esse job já tem um processo desse tipo rodando; espere terminar")
        log = open(job_dir / "log.txt", modo_log, encoding="utf-8")
        p = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, cwd=RAIZ, env=env)
        processos[jid] = p

    def esperar():
        code = p.wait()
        log.close()
        if chave is None:
            m2 = meta(job_dir)
            if m2["status"] == "rodando":
                m2["status"] = "concluido" if code == 0 else "erro"
            salvar_meta(job_dir, m2)
        with lock:
            processos.pop(jid, None)

    threading.Thread(target=esperar, daemon=True).start()


def aplicar_template(job_dir, dados):
    """apply_template do cut.pro: renderiza de novo cortes prontos com outro template, sem chamar a IA."""
    tpl = recut.carregar_template(str(dados.get("template", "")))
    pedidos = dados.get("cortes")
    if pedidos is not None and not (isinstance(pedidos, list) and all(isinstance(x, str) for x in pedidos)):
        raise ValueError("cortes deve ser uma lista de arquivos .json")
    pedidos = pedidos or [f.relative_to(job_dir).as_posix() for f in job_dir.rglob(CORTES_GLOB)]
    arquivos = []
    for rel in pedidos:
        f = (job_dir / str(rel)).resolve()
        if not f.is_relative_to(job_dir.resolve()) or not f.is_file() or not re.search(r"_corte\d+\.json$", f.name):
            raise ValueError(f"corte inválido: {rel}")
        arquivos.append(str(f))
    if not arquivos:
        raise ValueError("esse job não tem cortes")
    executar(job_dir, [sys.executable, "-u", str(RAIZ / "recut.py"), *arquivos, "--reaplicar",
                       "--template", tpl["nome"]], "a", chave=job_dir.name + REAPLICANDO)
    return resumo(job_dir)


def listar_templates():
    lista = []
    for f in sorted(recut.TEMPLATES.glob("*.json")):
        try:
            lista.append(recut.carregar_template(f.stem))
        except (ValueError, json.JSONDecodeError) as e:
            print(f"template ignorado ({f.name}): {e}", file=sys.stderr)
    return lista


def salvar_template(dados):
    tpl = recut.normalizar_template(dados)
    logo = tpl["logo"]["arquivo"]
    if logo and not Path(logo).resolve().is_relative_to(UPLOADS.resolve()):
        raise ValueError("o logo precisa vir de um upload")
    recut.TEMPLATES.mkdir(exist_ok=True)
    (recut.TEMPLATES / f"{tpl['nome']}.json").write_text(json.dumps(tpl, ensure_ascii=False, indent=2) + "\n",
                                                        encoding="utf-8")
    return tpl


def excluir_video(job_dir):
    # sob o mesmo lock de executar(): nenhum processo começa nesse vídeo entre a checagem e a mudança de pasta
    with lock:
        if job_dir.name in processos or job_dir.name + REAPLICANDO in processos:
            raise ValueError("o vídeo ainda está sendo processado; pare o job antes de excluir")
        return lixeira.excluir_video(job_dir)


def excluir_corte(job_dir, dados):
    rel = dados.get("json")
    f = (job_dir / str(rel or "")).resolve()
    if not isinstance(rel, str) or not f.is_relative_to(job_dir.resolve()) or not f.is_file() \
            or not re.search(r"_corte\d+\.json$", f.name):
        raise ValueError(f"corte inválido: {rel}")
    try:
        with lock:  # a live pode seguir gerando cortes; só não dá para excluir no meio de uma reaplicação de template
            if job_dir.name + REAPLICANDO in processos:
                raise ValueError("há uma reaplicação de template rodando nesse vídeo; espere terminar")
            return lixeira.excluir_corte(f)
    finally:  # também quando o corte foi movido só em parte: o índice reflete o que está no disco
        recut.atualizar_indices(f.parent)


def restaurar(item_id):
    item = lixeira.restaurar(item_id)
    if item["tipo"] == "corte":
        recut.atualizar_indices(Path(item["destino"]))
    return item


def entrada_publica(entrada):
    """URL como está; arquivo local só pelo nome (a API não expõe caminhos do disco)."""
    return entrada if re.match(r"https?://", entrada or "") else Path(entrada or "").name


def item_publico(item):
    """Item da lixeira para a API: com a URL da miniatura, sem caminhos locais."""
    publico = {k: v for k, v in item.items() if k not in ("upload", "destino")}
    publico["thumb_url"] = f"/files/lixeira/{item['id']}/{item['thumb']}" if item.get("thumb") else None
    publico["entrada"] = entrada_publica(item["entrada"])
    return publico


def expirar_periodicamente():
    """A lixeira se limpa sozinha: na abertura do servidor e depois de hora em hora."""
    while True:
        for item_id in lixeira.expirar():
            print(f"lixeira: {item_id} passou do prazo e foi apagado de vez", file=sys.stderr)
        time.sleep(3600)


def parar_job(jid):
    with lock:
        p = processos.get(jid)
        reaplicacao = processos.get(jid + REAPLICANDO)
    if reaplicacao:
        reaplicacao.terminate()
    job_dir = JOBS / jid
    m = meta(job_dir)
    m["status"] = "parado"
    salvar_meta(job_dir, m)
    if p:
        p.terminate()
    return m


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(DIST), **kw)

    def log_message(self, *a):
        pass

    def json(self, dados, status=200):
        corpo = json.dumps(dados, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def corpo_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def job_dir(self, jid):
        d = JOBS / jid
        if not re.fullmatch(r"[\w-]+", jid) or not (d / "job.json").exists():
            raise FileNotFoundError(jid)
        return d

    def do_GET(self):
        url = urlparse(self.path)
        partes = url.path.strip("/").split("/")
        try:
            if url.path == "/api/jobs":
                dirs = sorted((d for d in JOBS.glob("*") if (d / "job.json").exists()), reverse=True)
                return self.json([resumo(d) for d in dirs])
            if partes[:2] == ["api", "jobs"] and len(partes) == 3:
                return self.json(resumo(self.job_dir(partes[2]), com_log=True))
            if url.path == "/api/estrategias":
                return self.json([{"nome": f.stem, "texto": f.read_text(encoding="utf-8").strip()}
                                  for f in sorted(recut.ESTRATEGIAS.glob("*.txt"))])
            if url.path == "/api/templates":
                return self.json(listar_templates())
            if url.path == "/api/templates/opcoes":
                return self.json({"proporcoes": list(recut.PROPORCOES), "enquadramentos": list(recut.ENQUADRAMENTOS),
                                  "animacoes": list(recut.ANIMACOES), "fontes": list(recut.FONTES),
                                  "posicoes_logo": list(recut.POSICOES_LOGO), "padrao": recut.TEMPLATE_PADRAO,
                                  "tipos_momento": list(recut.TIPOS_MOMENTO), "efeitos": list(recut.EFEITOS)})
            if url.path == "/api/efeitos/sons":
                return self.json(recut.listar_sons())
            if url.path == "/api/lixeira":
                return self.json({"retencao_dias": lixeira_mod.RETENCAO_DIAS,
                                  "itens": [item_publico(i) for i in lixeira.listar()]})
            if url.path == "/api/lixeira/registro":
                return self.json([{**h, "entrada": entrada_publica(h["entrada"])} for h in lixeira.historico()])
            if url.path == "/api/agentes":
                return self.json([nome for nome, _ in recut.agentes_disponiveis(os.getenv("RECUT_AGENTE", ""))])
            if partes[0] == "files":
                return self.arquivo(JOBS.parent / unquote("/".join(partes[1:])))
        except FileNotFoundError:
            return self.json({"erro": "não encontrado"}, 404)
        if not (DIST / url.path.lstrip("/")).is_file():
            self.path = "/index.html"  # rotas do SPA
        return super().do_GET()

    def arquivo(self, caminho):
        """Serve cortes com suporte a Range (o <video> do navegador precisa para avançar)."""
        caminho = caminho.resolve()
        permitido = caminho.is_relative_to(JOBS.resolve()) or caminho.is_relative_to(LIXEIRA.resolve())
        if not permitido or caminho.suffix.lower() not in ARQUIVOS_SERVIDOS or not caminho.is_file():
            raise FileNotFoundError(caminho)
        tamanho = caminho.stat().st_size
        ini, fim = 0, tamanho - 1
        faixa = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        if faixa and (faixa[1] or faixa[2]):
            ini = int(faixa[1]) if faixa[1] else tamanho - int(faixa[2])
            fim = min(int(faixa[2]), fim) if faixa[1] and faixa[2] else fim
        self.send_response(206 if faixa else 200)
        self.send_header("Content-Type", mimetypes.guess_type(caminho.name)[0] or "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(fim - ini + 1))
        if faixa:
            self.send_header("Content-Range", f"bytes {ini}-{fim}/{tamanho}")
        self.end_headers()
        with open(caminho, "rb") as f:
            f.seek(ini)
            restante = fim - ini + 1
            while restante > 0 and (bloco := f.read(min(1 << 20, restante))):
                self.wfile.write(bloco)
                restante -= len(bloco)

    def do_POST(self):
        url = urlparse(self.path)
        partes = url.path.strip("/").split("/")
        try:
            if url.path == "/api/jobs":
                return self.json(criar_job(self.corpo_json()), 201)
            if partes[:2] == ["api", "jobs"] and len(partes) == 4 and partes[3] == "aplicar_template":
                return self.json(aplicar_template(self.job_dir(partes[2]), self.corpo_json()))
            if url.path == "/api/templates":
                return self.json(salvar_template(self.corpo_json()), 201)
            if partes[:2] == ["api", "jobs"] and len(partes) == 4 and partes[3] == "excluir":
                return self.json(item_publico(excluir_video(self.job_dir(partes[2]))))
            if partes[:2] == ["api", "jobs"] and partes[3:] == ["cortes", "excluir"] and len(partes) == 5:
                return self.json(item_publico(excluir_corte(self.job_dir(partes[2]), self.corpo_json())))
            if partes[:2] == ["api", "lixeira"] and len(partes) == 4 and partes[3] == "restaurar":
                return self.json(item_publico(restaurar(partes[2])))
            if partes[:2] == ["api", "lixeira"] and len(partes) == 4 and partes[3] == "apagar":
                return self.json(item_publico(lixeira.apagar(partes[2])))
            if partes[:2] == ["api", "jobs"] and len(partes) == 4 and partes[3] == "parar":
                self.job_dir(partes[2])
                return self.json(parar_job(partes[2]))
            if url.path == "/api/estrategias":
                d = self.corpo_json()
                nome = recut.slug(d.get("nome", ""))
                if not d.get("texto", "").strip():
                    raise ValueError("a estratégia precisa de um texto")
                recut.ESTRATEGIAS.mkdir(exist_ok=True)
                (recut.ESTRATEGIAS / f"{nome}.txt").write_text(d["texto"].strip() + "\n", encoding="utf-8")
                return self.json({"nome": nome, "texto": d["texto"].strip()}, 201)
            if url.path == "/api/upload":
                return self.upload(url)
        except FileNotFoundError:
            return self.json({"erro": "não encontrado"}, 404)
        except (ValueError, json.JSONDecodeError) as e:
            return self.json({"erro": str(e)}, 400)
        except OSError as e:  # arquivo em uso no Windows e afins: resposta clara em vez de conexão quebrada
            return self.json({"erro": f"não deu para concluir agora ({e.strerror or e}); tente de novo"}, 409)
        return self.json({"erro": "rota inexistente"}, 404)

    def upload(self, url):
        """Corpo cru (fetch com o File no body); nome em ?nome=."""
        nome = Path(parse_qs(url.query).get("nome", ["video.mp4"])[0]).name
        n = int(self.headers.get("Content-Length") or 0)
        if not n or n > MAX_UPLOAD:
            raise ValueError("arquivo vazio ou maior que 20 GB")
        UPLOADS.mkdir(exist_ok=True)
        destino = UPLOADS / f"{uuid.uuid4().hex[:8]}-{re.sub(r'[^\w.-]', '_', nome)}"
        with open(destino, "wb") as f:
            while n > 0 and (bloco := self.rfile.read(min(1 << 20, n))):
                f.write(bloco)
                n -= len(bloco)
        return self.json({"caminho": str(destino)}, 201)


if __name__ == "__main__":
    JOBS.mkdir(exist_ok=True)
    threading.Thread(target=expirar_periodicamente, daemon=True).start()
    print(f"re-cut em http://localhost:{PORTA}")
    ThreadingHTTPServer(("127.0.0.1", PORTA), Handler).serve_forever()
