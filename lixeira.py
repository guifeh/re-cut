"""Lixeira (safe-delete) do re-cut.

Excluir nunca apaga: move o vídeo (job inteiro, com o original enviado) ou o corte para lixeira/<id>/, onde fica
RECUT_LIXEIRA_DIAS dias (padrão 30) podendo ser restaurado. Cada ação vai para lixeira/registro.jsonl com data,
hora e o vídeo afetado; o registro só recebe linhas novas, então serve de histórico.
"""
import datetime as dt
import json
import os
import re
import shutil
import threading
import uuid
from pathlib import Path

RETENCAO_DIAS = int(os.getenv("RECUT_LIXEIRA_DIAS", "30"))
EXTENSOES_CORTE = (".mp4", ".jpg", ".json", ".ass", ".cmd")  # tudo que renderizar() gera para um corte


def agora():
    return dt.datetime.now().replace(microsecond=0)


class Lixeira:
    def __init__(self, pasta, jobs, uploads):
        self.pasta, self.jobs, self.uploads = Path(pasta), Path(jobs), Path(uploads)
        self.registro = self.pasta / "registro.jsonl"
        self.lock = threading.Lock()  # uma operação de lixeira por vez: mover, restaurar e apagar mexem nas mesmas pastas

    # ---------- registro (histórico com data e hora) ----------

    def _registrar(self, acao, item):
        linha = {"em": agora().isoformat(), "acao": acao, "tipo": item["tipo"], "item": item["id"],
                 "titulo": item["titulo"], "entrada": item["entrada"], "job_id": item["job_id"]}
        self.pasta.mkdir(parents=True, exist_ok=True)
        with open(self.registro, "a", encoding="utf-8") as f:
            f.write(json.dumps(linha, ensure_ascii=False) + "\n")

    def historico(self, limite=300):
        if not self.registro.is_file():
            return []
        linhas = self.registro.read_text(encoding="utf-8").splitlines()
        return [json.loads(l) for l in reversed(linhas[-limite:]) if l.strip()]

    # ---------- excluir ----------

    def _novo_item(self, tipo, job_meta, titulo, **extra):
        quando = agora()
        item = {"id": f"{quando:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}", "tipo": tipo, "job_id": job_meta["id"],
                "titulo": titulo, "entrada": job_meta.get("entrada", ""), "excluido_em": quando.isoformat(),
                "expira_em": (quando + dt.timedelta(days=RETENCAO_DIAS)).isoformat(), **extra}
        (self.pasta / item["id"]).mkdir(parents=True)
        return item

    def _salvar_item(self, item):
        (self.pasta / item["id"] / "item.json").write_text(json.dumps(item, ensure_ascii=False, indent=2),
                                                         encoding="utf-8")

    def excluir_video(self, job_dir):
        """Move o job inteiro (cortes, log, vídeo baixado) e o arquivo enviado, se houver, para a lixeira."""
        with self.lock:
            job_meta = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
            cortes = sorted(job_dir.rglob("*_corte[0-9]*.json"),
                            key=lambda f: -json.loads(f.read_text(encoding="utf-8")).get("nota", 0))
            capa = cortes[0].with_suffix(".jpg") if cortes else None
            item = self._novo_item("video", job_meta, nome_entrada(job_meta.get("entrada", "")),
                                   cortes=len(cortes), tamanho=tamanho(job_dir),
                                   thumb=f"job/{capa.relative_to(job_dir).as_posix()}" if capa and capa.is_file() else None,
                                   upload=None)
            destino = self.pasta / item["id"]
            try:
                os.replace(job_dir, destino / "job")  # renomear a pasta: ou move tudo ou nada
            except OSError as e:
                shutil.rmtree(destino, ignore_errors=True)
                raise ValueError(f"não deu para mover o vídeo agora ({e.strerror or e}); feche o player e tente de novo")
            original = Path(job_meta.get("entrada", ""))
            # o arquivo enviado só vai junto se nenhum outro vídeo usa o mesmo upload (os cortes dele apontam para lá)
            if original.is_file() and original.resolve().is_relative_to(self.uploads.resolve()) \
                    and not self._upload_em_uso(job_meta.get("entrada")):
                (destino / "upload").mkdir()
                os.replace(original, destino / "upload" / original.name)
                item["upload"] = str(original)  # onde volta ao restaurar
                item["tamanho"] += (destino / "upload" / original.name).stat().st_size
            self._salvar_item(item)
            self._registrar("excluido", item)
            return item

    def excluir_corte(self, arquivo_json):
        """Move os arquivos de um corte (.mp4, .jpg, .json, .ass, .cmd) para a lixeira."""
        with self.lock:
            arquivo_json = Path(arquivo_json)
            job_dir = self._job_do_arquivo(arquivo_json)
            job_meta = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
            corte = json.loads(arquivo_json.read_text(encoding="utf-8"))
            arquivos = [f for f in (arquivo_json.with_suffix(ext) for ext in EXTENSOES_CORTE) if f.is_file()]
            item = self._novo_item("corte", job_meta, corte.get("titulo") or arquivo_json.stem,
                                   nota=corte.get("nota"), duracao=corte.get("duracao"),
                                   pasta=arquivo_json.parent.relative_to(self.jobs).as_posix(),
                                   arquivos=[f.name for f in arquivos], tamanho=sum(f.stat().st_size for f in arquivos),
                                   thumb=f"corte/{arquivo_json.with_suffix('.jpg').name}"
                                   if arquivo_json.with_suffix(".jpg").is_file() else None)
            destino = self.pasta / item["id"] / "corte"
            destino.mkdir()
            movidos = []
            try:
                for f in arquivos:
                    os.replace(f, destino / f.name)
                    movidos.append(f)
            except OSError as e:  # volta o que já tinha movido: o corte não fica pela metade
                for f in movidos:
                    os.replace(destino / f.name, f)
                shutil.rmtree(self.pasta / item["id"], ignore_errors=True)
                raise ValueError(f"não deu para mover o corte agora ({e.strerror or e}); feche o player e tente de novo")
            self._salvar_item(item)
            self._registrar("excluido", item)
            return item

    def _upload_em_uso(self, entrada):
        for f in self.jobs.glob("*/job.json"):
            try:
                if json.loads(f.read_text(encoding="utf-8")).get("entrada") == entrada:
                    return True
            except (OSError, ValueError):
                return True  # na dúvida, não leva o arquivo
        return False

    def _job_do_arquivo(self, arquivo):
        for pai in arquivo.parents:
            if pai.parent == self.jobs:
                return pai
        raise ValueError("o corte não está dentro de um job")

    # ---------- listar, restaurar, apagar ----------

    def _pasta_item(self, item_id):
        pasta = (self.pasta / item_id).resolve()
        if not re.fullmatch(r"[\w-]+", item_id) or not pasta.is_relative_to(self.pasta.resolve()) \
                or not (pasta / "item.json").is_file():
            raise FileNotFoundError(item_id)
        return pasta

    def item(self, item_id):
        return json.loads((self._pasta_item(item_id) / "item.json").read_text(encoding="utf-8"))

    def listar(self):
        self.expirar()
        itens = []
        for f in self.pasta.glob("*/item.json"):
            try:
                itens.append(json.loads(f.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return sorted(itens, key=lambda i: i["excluido_em"], reverse=True)

    def restaurar(self, item_id):
        with self.lock:
            pasta, item = self._pasta_item(item_id), self.item(item_id)
            if item["tipo"] == "video":
                destino = self.jobs / item["job_id"]
                if destino.exists():
                    raise ValueError("já existe um vídeo com esse id fora da lixeira")
                if item.get("upload") and Path(item["upload"]).exists():
                    raise ValueError("já existe um arquivo enviado com o mesmo nome em uploads/")
                self.jobs.mkdir(parents=True, exist_ok=True)
                os.replace(pasta / "job", destino)
                if item.get("upload"):
                    Path(item["upload"]).parent.mkdir(parents=True, exist_ok=True)
                    os.replace(pasta / "upload" / Path(item["upload"]).name, item["upload"])
            else:
                destino = self.jobs / item["pasta"]
                if not destino.is_dir():
                    raise ValueError("o vídeo deste corte também foi excluído; restaure o vídeo antes")
                if any((destino / nome).exists() for nome in item["arquivos"]):
                    raise ValueError("já existe um corte com esse nome no vídeo")
                for nome in item["arquivos"]:
                    os.replace(pasta / "corte" / nome, destino / nome)
            shutil.rmtree(pasta)
            self._registrar("restaurado", item)
            return {**item, "restaurado_em": agora().isoformat(), "destino": str(destino)}

    def apagar(self, item_id, acao="apagado"):
        """Apaga de vez. acao="expirado" quando é a limpeza automática dos itens vencidos."""
        with self.lock:
            pasta, item = self._pasta_item(item_id), self.item(item_id)
            shutil.rmtree(pasta)
            self._registrar(acao, item)
            return item

    def expirar(self, momento=None):
        """Apaga de vez o que passou do prazo da lixeira; devolve os ids apagados."""
        momento = momento or agora()
        vencidos = []
        for f in list(self.pasta.glob("*/item.json")):
            try:
                item = json.loads(f.read_text(encoding="utf-8"))
                if dt.datetime.fromisoformat(item["expira_em"]) <= momento:
                    self.apagar(item["id"], acao="expirado")
                    vencidos.append(item["id"])
            except (OSError, ValueError, KeyError, FileNotFoundError):
                continue  # item em uso agora: fica para a próxima limpeza
        return vencidos


def nome_entrada(entrada):
    """Nome amigável do vídeo: URL sem o esquema ou o nome do arquivo enviado sem o prefixo aleatório."""
    if re.match(r"https?://", entrada):
        return re.sub(r"^https?://(www\.)?", "", entrada)
    return re.sub(r"^[0-9a-f]{8}-", "", Path(entrada).name)


def tamanho(pasta):
    return sum(f.stat().st_size for f in Path(pasta).rglob("*") if f.is_file())
