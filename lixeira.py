"""Lixeira (safe-delete) do re-cut.

Excluir nunca apaga: move o vídeo (job inteiro, com o original enviado) ou o corte para lixeira/<id>/, onde fica
RECUT_LIXEIRA_DIAS dias (padrão 30) podendo ser restaurado. Cada ação vai para lixeira/registro.jsonl com data,
hora e o vídeo afetado; o registro só recebe linhas novas, então serve de histórico.

Regra de ordem em toda operação: primeiro o que pode falhar sem estrago (gravar item.json, renomear pastas),
depois o resto; se algo falha no meio, desfaz o que já tinha movido. Nunca fica arquivo fora da lista.
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
APAGANDO = ".apagando-"  # pasta renomeada antes do rmtree; sobra só se algum arquivo estava aberto
IDADE_FANTASMA = dt.timedelta(minutes=1)  # item recém-gravado pode estar no meio de uma exclusão: não é fantasma


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
        with open(self.registro, "a+b") as f:
            f.seek(0, os.SEEK_END)
            if f.tell():  # uma escrita cortada deixa a última linha sem \n: começa numa nova para não grudar nela
                f.seek(-1, os.SEEK_END)
                inicio = b"" if f.read(1) == b"\n" else b"\n"
            else:
                inicio = b""
            f.write(inicio + (json.dumps(linha, ensure_ascii=False) + "\n").encode("utf-8"))

    def historico(self):
        """Mais recente primeiro; uma linha corrompida (queda no meio da escrita) é pulada, não derruba o resto."""
        if not self.registro.is_file():
            return []
        eventos = []
        for linha in self.registro.read_text(encoding="utf-8", errors="replace").splitlines()[-300:]:
            try:
                eventos.append(json.loads(linha))
            except ValueError:
                continue
        return eventos[::-1]

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
            self._salvar_item(item)  # antes de mover: se o processo cair no meio, o item já está na lista
            try:
                os.replace(job_dir, destino / "job")  # renomear a pasta: ou move tudo ou nada
            except OSError as e:
                self._tirar_da_lista(destino)  # só item.json lá dentro: o replace da pasta é tudo ou nada
                raise ValueError(f"não deu para mover o vídeo agora ({e.strerror or e}); feche o player e tente de novo")
            original = Path(job_meta.get("entrada", ""))
            # o arquivo enviado só vai junto se nenhum outro vídeo usa o mesmo upload (os cortes dele apontam para lá)
            if original.is_file() and original.resolve().is_relative_to(self.uploads.resolve()) \
                    and not self._upload_em_uso(job_meta.get("entrada")):
                try:
                    (destino / "upload").mkdir()
                    os.replace(original, destino / "upload" / original.name)
                    item["upload"] = str(original)  # onde volta ao restaurar
                    item["tamanho"] += (destino / "upload" / original.name).stat().st_size
                except OSError:
                    pass  # arquivo aberto por outro programa: fica em uploads/, o vídeo vai para a lixeira mesmo assim
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
            self._salvar_item(item)
            try:
                _mover_todos([(f, destino / f.name) for f in arquivos])
            except OSError as e:
                if any(destino.iterdir()):  # a devolução não foi completa: o item fica, com o que estiver na lixeira
                    self._registrar("excluido", item)
                    raise ValueError(f"o corte foi movido só em parte ({e.strerror or e}); ele está na Lixeira, "
                                     "restaure por lá quando o arquivo for liberado")
                self._tirar_da_lista(self.pasta / item["id"])  # nada ficou na lixeira
                raise ValueError(f"não deu para mover o corte agora ({e.strerror or e}); feche o player e tente de novo")
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
        if not re.fullmatch(r"[\w-]+", item_id) or item_id.startswith(APAGANDO) or not pasta.is_relative_to(self.pasta.resolve()) \
                or not (pasta / "item.json").is_file():
            raise FileNotFoundError(item_id)
        return pasta

    def item(self, item_id):
        return json.loads((self._pasta_item(item_id) / "item.json").read_text(encoding="utf-8"))

    def listar(self):
        self.expirar()
        itens = []
        for f in self._itens_json():
            try:
                item = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            with self.lock:  # nunca no meio de uma exclusão/restauração (elas seguram o mesmo lock)
                if self._fantasma(item, f.parent) and self._tirar_da_lista(f.parent):
                    continue
            itens.append(item)
        return sorted(itens, key=lambda i: i["excluido_em"], reverse=True)

    def _itens_json(self):
        return [f for f in self.pasta.glob("*/item.json") if not f.parent.name.startswith(APAGANDO)]

    def _fantasma(self, item, pasta):
        """item.json gravado mas o processo caiu antes de mover: os arquivos continuam no lugar original.
        Só é fantasma se não sobrou nada na pasta do item (um item parcial guarda a única cópia de algo)."""
        if agora() - dt.datetime.fromisoformat(item["excluido_em"]) < IDADE_FANTASMA:
            return False
        if item["tipo"] == "video":
            return not (pasta / "job").exists() and (self.jobs / item["job_id"]).is_dir()
        return all((self.jobs / item["pasta"] / n).exists() for n in item["arquivos"])

    def restaurar(self, item_id):
        with self.lock:
            pasta, item = self._pasta_item(item_id), self.item(item_id)
            if item["tipo"] == "video":
                destino = self.jobs / item["job_id"]
                movimentos = []
                if (pasta / "job").exists():  # num item parcial o job pode já ter voltado; falta só o upload
                    if destino.exists():
                        raise ValueError("já existe um vídeo com esse id fora da lixeira")
                    movimentos.append((pasta / "job", destino))
                upload, dono_do_upload = self._upload_para_restaurar(pasta, destino)
                if upload:
                    movimentos.append(upload)
                elif any((pasta / "upload").glob("*")):  # a cópia da lixeira não tem para onde voltar: não descarta
                    raise ValueError("já existe um arquivo enviado com o mesmo nome em uploads/")
            else:
                destino = self.jobs / item["pasta"]
                if not destino.is_dir():
                    raise ValueError("o vídeo deste corte também foi excluído; restaure o vídeo antes")
                na_lixeira = [n for n in item["arquivos"] if (pasta / "corte" / n).exists()]
                if any((destino / nome).exists() for nome in na_lixeira):
                    raise ValueError("já existe um corte com esse nome no vídeo")
                movimentos, dono_do_upload = [(pasta / "corte" / n, destino / n) for n in na_lixeira], None
            self.jobs.mkdir(parents=True, exist_ok=True)
            try:
                _mover_todos(movimentos)  # tudo ou nada: se um falha, os já movidos voltam para a lixeira
            except OSError as e:
                raise ValueError(f"não deu para restaurar agora ({e.strerror or e}); feche o player e tente de novo")
            if dono_do_upload and dono_do_upload.parent != pasta:  # o outro vídeo continua na lixeira, sem o arquivo
                outro = json.loads(dono_do_upload.read_text(encoding="utf-8"))
                dono_do_upload.write_text(json.dumps({**outro, "upload": None}, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
            self._registrar("restaurado", item)
            self._tirar_da_lista(pasta)
            return {**item, "restaurado_em": agora().isoformat(), "destino": str(destino)}

    def _upload_para_restaurar(self, pasta, destino):
        """((origem, destino), item.json de quem guarda) do arquivo enviado do vídeo, se ele não está em uploads/.
        Vem da própria pasta do item ou, quando dois vídeos usavam o mesmo upload, do outro vídeo excluído."""
        meta_job = pasta / "job" / "job.json" if (pasta / "job").exists() else destino / "job.json"
        meta = json.loads(meta_job.read_text(encoding="utf-8"))
        original = Path(meta.get("entrada", ""))
        if not original.name or original.exists() or not original.resolve().is_relative_to(self.uploads.resolve()):
            return None, None
        for f in [pasta / "item.json", *self._itens_json()]:
            try:
                dono = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            arquivo = f.parent / "upload" / original.name
            if dono.get("upload") == str(original) and arquivo.is_file():
                return (arquivo, original), f
        return None, None

    def apagar(self, item_id, acao="apagado"):
        """Apaga de vez. acao="expirado" quando é a limpeza automática dos itens vencidos."""
        with self.lock:
            pasta, item = self._pasta_item(item_id), self.item(item_id)
            fora = pasta.with_name(APAGANDO + pasta.name)
            try:
                os.replace(pasta, fora)  # sai da lista de uma vez; se algo está aberto, nada muda
            except OSError as e:
                raise ValueError(f"não deu para apagar agora ({e.strerror or e}); feche o player e tente de novo")
            self._registrar(acao, item)
            shutil.rmtree(fora, ignore_errors=True)  # já saiu da lista; sobra, se houver, a próxima limpeza tira
            return item

    def expirar(self, momento=None):
        """Apaga de vez o que passou do prazo da lixeira; devolve os ids apagados."""
        momento = momento or agora()
        for resto in self.pasta.glob(APAGANDO + "*"):  # sobras de um apagar com arquivo aberto
            shutil.rmtree(resto, ignore_errors=True)
        vencidos = []
        for f in self._itens_json():
            try:
                item = json.loads(f.read_text(encoding="utf-8"))
                if dt.datetime.fromisoformat(item["expira_em"]) <= momento:
                    self.apagar(item["id"], acao="expirado")
                    vencidos.append(item["id"])
            except (OSError, ValueError, KeyError, FileNotFoundError):
                continue  # item em uso agora: fica para a próxima limpeza
        return vencidos

    @staticmethod
    def _tirar_da_lista(pasta):
        """Tira da lista a pasta de um item que já não guarda nada (só item.json e pastas vazias).
        Regra de segurança: se sobrou QUALQUER arquivo, não mexe e devolve False. Só apagar() e a expiração
        apagam conteúdo da lixeira; todo o resto passa por aqui."""
        if any(f.is_file() and f.name != "item.json" for f in pasta.rglob("*")):
            return False
        fora = pasta.with_name(APAGANDO + pasta.name)
        try:
            os.replace(pasta, fora)
        except OSError:
            fora = pasta
            (pasta / "item.json").unlink(missing_ok=True)
        shutil.rmtree(fora, ignore_errors=True)
        return True


def _mover_todos(movimentos):
    """Move (origem, destino) em ordem; se um falha, tenta devolver todos os que já foram (sem parar no primeiro
    erro) e repassa o erro. Quem chama nunca pode apagar o que sobrou: pode ser a única cópia de um arquivo."""
    feitos = []
    try:
        for origem, destino in movimentos:
            Path(destino).parent.mkdir(parents=True, exist_ok=True)
            os.replace(origem, destino)
            feitos.append((origem, destino))
    except OSError:
        for origem, destino in reversed(feitos):
            try:
                os.replace(destino, origem)
            except OSError:
                pass  # fica onde está; o item continua listado e restaurável
        raise


def nome_entrada(entrada):
    """Nome amigável do vídeo: URL sem o esquema ou o nome do arquivo enviado sem o prefixo aleatório."""
    if re.match(r"https?://", entrada):
        return re.sub(r"^https?://(www\.)?", "", entrada)
    return re.sub(r"^[0-9a-f]{8}-", "", Path(entrada).name)


def tamanho(pasta):
    return sum(f.stat().st_size for f in Path(pasta).rglob("*") if f.is_file())
