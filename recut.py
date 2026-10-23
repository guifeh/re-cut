"""re-cut: cortes verticais automáticos de lives e vídeos (modelado no Live Clipper do cut.pro).

    python recut.py video.mp4                                   # arquivo local
    python recut.py https://www.youtube.com/watch?v=...         # VOD
    python recut.py https://www.twitch.tv/canal --monitorar     # espera ficar ao vivo e corta em lotes de 10 min
    python recut.py https://kick.com/canal --monitorar --dias 1,2,3,4,5 --horas 18,19,20,21,22,23 \
        --estrategia reacoes --limite-por-lote 3 --webhook https://meu.app/hook

A IA usa a sessão local de um agente CLI já logado (Claude Code, Codex ou Gemini CLI), sem API key.
RECUT_AGENTE=gemini (ou claude, codex) define o preferido; se um falhar, tenta os outros.

--estrategia aceita texto livre ou o nome de um arquivo em estrategias/<nome>.txt (salva uma vez, reusa sempre).
"""
import argparse
import datetime as dt
import functools
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request
from array import array
from pathlib import Path

try:  # ffmpeg estático do pip (já vem com libass/libx264); RECUT_FFMPEG sobrepõe
    import imageio_ffmpeg
    FFMPEG = os.getenv("RECUT_FFMPEG") or imageio_ffmpeg.get_ffmpeg_exe()
except ImportError:
    FFMPEG = os.getenv("RECUT_FFMPEG", "ffmpeg")
LOTE_SEG = 600  # "lotes de 10 minutos"
FIM_DE_VEZ_SEG = 300  # "termina de vez, alguns minutos depois de sair do ar"
AUDIO_HZ = 4000  # só para medir energia
PASSO_ROSTO = 0.5  # segundos entre amostras do tracking de rosto
ESTRATEGIAS = Path(__file__).with_name("estrategias")
AGENTES = ("claude", "codex", "gemini")  # CLIs com sessão local; RECUT_AGENTE escolhe o preferido

SISTEMA = """Você é editor de cortes para TikTok, Reels e Shorts.
Recebe a transcrição de um vídeo ou de um lote de live com marcação de tempo; cada linha traz a energia
do áudio relativa à mediana (2.0x = o dobro do volume típico).
Analise o trecho inteiro: picos de energia, reações, setup e payoff, dinâmica da fala. Não se limite a
palavras-chave. Escolha trechos que se sustentam sozinhos: uma história com começo e fim, uma opinião forte,
uma reação, uma explicação curta. Mudança de tom e pausa antes de uma frase forte são bons sinais.
Cada corte deve durar entre {dur_min} e {dur_max} segundos, começar no início de uma frase e terminar depois do payoff.
Dê a cada corte uma nota viral de 0 a 10 com o motivo explicado; seja exigente, nota 8+ é rara.
Escreva um título curto que prenda e a descrição do post a partir do que é falado no corte.
Use exatamente os tempos (em segundos) das linhas da transcrição."""

ESQUEMA = {
    "type": "object",
    "properties": {
        "cortes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "inicio": {"type": "number"},
                    "fim": {"type": "number"},
                    "titulo": {"type": "string"},
                    "descricao": {"type": "string"},
                    "nota": {"type": "number"},
                    "motivo": {"type": "string"},
                    "hashtags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["inicio", "fim", "titulo", "descricao", "nota", "motivo", "hashtags"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["cortes"],
    "additionalProperties": False,
}

ASS_CABECALHO = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,84,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,6,2,2,60,60,520,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


# ---------- funções puras (testadas em test_recut.py) ----------

def ts_ass(seg):
    cs = max(0, round(seg * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def legenda_ass(palavras, inicio, fim, por_linha=3):
    """Legenda no ritmo da fala: blocos de N palavras, tempos relativos ao início do corte."""
    ws = [w for w in palavras if w[0] >= inicio and w[1] <= fim]
    linhas = []
    for i in range(0, len(ws), por_linha):
        g = ws[i:i + por_linha]
        texto = " ".join(w[2] for w in g).upper().replace("{", "(").replace("}", ")")
        linhas.append(f"Dialogue: 0,{ts_ass(g[0][0] - inicio)},{ts_ass(g[-1][1] - inicio)},Default,,0,0,0,,{texto}")
    return ASS_CABECALHO + "\n".join(linhas) + "\n"


def recorte_vertical(centro_x, iw, ih):
    """(x, largura) do recorte 9:16 centrado no rosto, ou None se o vídeo já é vertical."""
    w = int(ih * 9 / 16) // 2 * 2
    if w >= iw:
        return None
    return int(min(max(centro_x - w / 2, 0), iw - w)), w


def suavizar_trajetoria(xs, padrao, janela=5, zona_morta=40.0, ganho=0.35):
    """Centros do rosto por amostra (None = sem rosto) -> trajetória de câmera estável.
    Mediana tira detecções falsas, zona morta segura o quadro parado e o ganho faz o pan suave."""
    if all(x is None for x in xs):
        return [padrao] * max(1, len(xs))
    ultimo, cheios = next(x for x in xs if x is not None), []
    for x in xs:  # sem rosto na amostra: mantém o último lugar conhecido
        ultimo = ultimo if x is None else x
        cheios.append(ultimo)
    m = janela // 2
    medianas = [statistics.median(cheios[max(0, i - m):i + m + 1]) for i in range(len(cheios))]
    cam, trajetoria = medianas[0], []
    for alvo in medianas:
        if abs(alvo - cam) > zona_morta:
            cam += (alvo - cam) * ganho
        trajetoria.append(cam)
    return trajetoria


def comandos_crop(trajetoria, passo, iw, w, hz=10):
    """Script do filtro sendcmd: x do recorte interpolado entre as amostras, preso dentro do quadro."""
    pts = trajetoria if len(trajetoria) > 1 else trajetoria * 2
    linhas = []
    for k in range(int((len(pts) - 1) * passo * hz) + 1):
        t = k / hz
        i = min(int(t / passo), len(pts) - 2)
        cx = pts[i] + (pts[i + 1] - pts[i]) * min(1.0, t / passo - i)
        linhas.append(f"{t:.2f} crop@rosto x {int(min(max(cx - w / 2, 0), iw - w))};")
    return "\n".join(linhas) + "\n"


def energia_relativa(rms, inicio, fim):
    mediana = statistics.median(rms) or 1
    trecho = rms[int(inicio):max(int(fim), int(inicio) + 1)] or [0]
    return statistics.fmean(trecho) / mediana


def aplicar_regra(cortes, duracao, nota_min, dur_min, dur_max, limite):
    """Regra do lote: limites de duração, nota mínima, ordem pela nota, limite por lote."""
    ok = []
    for c in cortes:
        c = {**c, "inicio": max(0.0, c["inicio"]), "fim": min(duracao, c["fim"])}
        if c["nota"] >= nota_min and dur_min <= c["fim"] - c["inicio"] <= dur_max:
            ok.append(c)
    return sorted(ok, key=lambda c: -c["nota"])[:limite]


def no_horario(agora, dias, horas):
    """dias: 1=seg..7=dom (ISO); horas: 0..23. Vazio = sempre."""
    return (not dias or agora.isoweekday() in dias) and (not horas or agora.hour in horas)


def carregar_estrategia(valor, pasta=ESTRATEGIAS):
    arquivo = pasta / f"{valor}.txt"
    return arquivo.read_text(encoding="utf-8").strip() if valor and arquivo.is_file() else valor


def slug(texto):
    return re.sub(r"[^a-z0-9]+", "-", texto.lower()).strip("-") or "canal"


# ---------- etapas com dependências externas ----------

def agentes_disponiveis(preferido="", which=shutil.which):
    """Agentes CLI instalados, o preferido primeiro."""
    ordem = [preferido, *[a for a in AGENTES if a != preferido]] if preferido in AGENTES else AGENTES
    return [(a, exe) for a in ordem if (exe := which(a))]


def extrair_json(texto):
    """Primeiro objeto JSON do texto, ignorando cercas ```json e prosa em volta."""
    return json.JSONDecoder().raw_decode(texto[texto.index("{"):])[0]


def evento(cfg, tipo, dados):
    """Gatilhos das automações do cut.pro: live_started, live_clips, live_ended."""
    print(f"* {tipo}: {dados.get('titulo') or dados.get('lote') or ''}")
    if cfg["webhook"]:
        corpo = json.dumps({"evento": tipo, **dados}, ensure_ascii=False).encode()
        req = urllib.request.Request(cfg["webhook"], corpo, {"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=10).close()
        except OSError as e:
            print(f"  webhook falhou: {e}", file=sys.stderr)


# ffmpeg do pacote (o do PATH pode faltar) e Node como runtime JS do YouTube (o padrão do yt-dlp é só deno).
YTDLP = {"quiet": True, "noprogress": True, "ffmpeg_location": FFMPEG, "js_runtimes": {"deno": {}, "node": {}}}


def baixar(url, saida):
    import yt_dlp
    opts = {**YTDLP, "outtmpl": str(saida / "fonte.%(ext)s"), "format": "bv*[height<=1080]+ba/b",
            "merge_output_format": "mp4"}
    with yt_dlp.YoutubeDL(opts) as ydl:
        return Path(ydl.extract_info(url)["requested_downloads"][0]["filepath"])


def ao_vivo(canal):
    """Info da live se o canal está no ar, senão None."""
    import yt_dlp
    try:
        info = yt_dlp.YoutubeDL({**YTDLP, "no_warnings": True}).extract_info(canal, download=False)
    except yt_dlp.utils.DownloadError:  # canal offline
        return None
    return info if info.get("is_live") else None


@functools.cache
def whisper():
    from faster_whisper import WhisperModel
    return WhisperModel(os.getenv("RECUT_WHISPER", "small"), compute_type="int8")


def transcrever(video):
    segmentos, _ = whisper().transcribe(str(video), word_timestamps=True, vad_filter=True)
    segs, palavras = [], []
    for s in segmentos:
        segs.append((s.start, s.end, s.text.strip()))
        palavras += [(w.start, w.end, w.word.strip()) for w in s.words]
    return segs, palavras


def rms_por_segundo(video):
    # ponytail: RMS em Python puro, ~20s para 3h de áudio; troque por numpy se pesar
    bruto = subprocess.run([FFMPEG, "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", str(AUDIO_HZ),
                            "-f", "s16le", "-"], capture_output=True, check=True).stdout
    a = array("h")
    a.frombytes(bruto[:len(bruto) // 2 * 2])
    return [math.sqrt(sum(x * x for x in a[i:i + AUDIO_HZ]) / AUDIO_HZ) for i in range(0, len(a), AUDIO_HZ)]


def rodar_agente(nome, exe, sistema, entrada, pasta):
    """Usa a sessão já logada do agente CLI; sem API key."""
    if nome == "claude":
        (pasta / "sistema.txt").write_text(sistema, encoding="utf-8")
        r = subprocess.run([exe, "-p", "--output-format", "json", "--tools", "", "--no-session-persistence",
                            "--system-prompt-file", "sistema.txt", "--json-schema", json.dumps(ESQUEMA)],
                           input=entrada, capture_output=True, text=True, encoding="utf-8", cwd=pasta, timeout=1800)
        d = json.loads(r.stdout)
        if d.get("is_error"):
            raise RuntimeError(d.get("result"))
        return d["structured_output"]
    if nome == "gemini":
        # Gemini CLI não tem flag de schema: o esquema vai no prompt e a resposta é extraída do texto
        instrucoes = (f"{sistema}\n\nResponda somente com um JSON válido neste esquema, sem comentários:\n"
                      f"{json.dumps(ESQUEMA)}\n\n<transcricao>\n{entrada}\n</transcricao>")
        r = subprocess.run([exe, "-p", "Siga as instruções da entrada padrão.", "--output-format", "json"],
                           input=instrucoes, capture_output=True, text=True, encoding="utf-8", cwd=pasta, timeout=1800)
        d = json.loads(r.stdout)
        if d.get("error"):
            raise RuntimeError(d["error"])
        return extrair_json(d["response"])
    (pasta / "esquema.json").write_text(json.dumps(ESQUEMA), encoding="utf-8")
    subprocess.run([exe, "exec", "--skip-git-repo-check", "--ephemeral", "--sandbox", "read-only",
                    "--output-schema", "esquema.json", "-o", "resposta.json", "-"],
                   input=f"{sistema}\n\n<transcricao>\n{entrada}\n</transcricao>", capture_output=True, text=True,
                   encoding="utf-8", cwd=pasta, timeout=1800, check=True)
    return json.loads((pasta / "resposta.json").read_text(encoding="utf-8"))


def escolher_cortes(transcricao, cfg):
    sistema = SISTEMA.format(dur_min=cfg["dur_min"], dur_max=cfg["dur_max"])
    if cfg["estrategia"]:
        sistema += f"\n\nEstratégia do criador (o que procurar e como escrever os títulos; siga-a):\n{cfg['estrategia']}"
    with tempfile.TemporaryDirectory() as tmp:  # cwd vazio: o agente não lê CLAUDE.md/AGENTS.md do projeto
        for nome, exe in agentes_disponiveis(os.getenv("RECUT_AGENTE", "")):
            try:
                return rodar_agente(nome, exe, sistema, transcricao, Path(tmp))["cortes"]
            except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as e:
                print(f"  {nome} falhou ({str(e)[:200]}); a sessão está ativa? tentando o próximo", file=sys.stderr)
    print("  nenhum agente respondeu; lote sem cortes", file=sys.stderr)
    return []


def trajetoria_do_rosto(video, inicio, fim, passo=PASSO_ROSTO):
    """Centro x do maior rosto a cada `passo` segundos (None quando não acha), lendo em sequência."""
    import cv2
    cap = cv2.VideoCapture(str(video))
    iw, ih = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    pular = max(1, round((cap.get(cv2.CAP_PROP_FPS) or 30) * passo))
    escala = min(1.0, 640 / iw)  # detectar em 640px é bem mais rápido e basta para rosto
    det = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    cap.set(cv2.CAP_PROP_POS_MSEC, inicio * 1000)
    xs = []
    for _ in range(int((fim - inicio) / passo) + 1):
        ok, frame = cap.read()
        for _ in range(pular - 1):  # grab() só avança, sem converter o quadro
            cap.grab()
        if not ok:
            break
        cinza = cv2.cvtColor(cv2.resize(frame, None, fx=escala, fy=escala), cv2.COLOR_BGR2GRAY)
        rostos = det.detectMultiScale(cinza, 1.2, 5, minSize=(40, 40))
        if len(rostos):
            x, _, w, _ = max(rostos, key=lambda r: r[2] * r[3])
            xs.append((x + w / 2) / escala)
        else:
            xs.append(None)
    cap.release()
    return xs, iw, ih


def renderizar(video, c, palavras, saida, nome):
    dur = c["fim"] - c["inicio"]
    xs, iw, ih = trajetoria_do_rosto(video, c["inicio"], c["fim"])
    rec = recorte_vertical(iw / 2, iw, ih)
    if rec:
        w = rec[1]
        trajetoria = suavizar_trajetoria(xs, iw / 2, zona_morta=0.06 * w)
        (saida / f"{nome}.cmd").write_text(comandos_crop(trajetoria, PASSO_ROSTO, iw, w), encoding="utf-8")
        x0 = recorte_vertical(trajetoria[0], iw, ih)[0]
        vf = f"sendcmd=f={nome}.cmd,crop@rosto={w}:{ih}:{x0}:0,scale=1080:1920"
    else:
        vf = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2"
    (saida / f"{nome}.ass").write_text(legenda_ass(palavras, c["inicio"], c["fim"]), encoding="utf-8")
    # cwd=saida: caminhos relativos nos filtros evitam o escape de "C:" no Windows
    subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", f"{c['inicio']:.2f}", "-t", f"{dur:.2f}",
                    "-i", str(Path(video).resolve()), "-vf", f"{vf},subtitles={nome}.ass",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", f"{nome}.mp4"],
                   cwd=saida, check=True)
    subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", f"{dur / 2:.2f}", "-i", f"{nome}.mp4",
                    "-frames:v", "1", f"{nome}.jpg"], cwd=saida, check=True)


def processar(video, saida, prefixo, cfg):
    """Um vídeo ou um lote de live -> cortes renderizados. Devolve os metadados dos cortes."""
    print(f"[{prefixo}] transcrevendo")
    segs, palavras = transcrever(video)
    if not segs:
        return []
    rms = rms_por_segundo(video)
    transcricao = "\n".join(f"[{s:.1f}-{e:.1f}] (energia {energia_relativa(rms, s, e):.1f}x) {t}" for s, e, t in segs)
    print(f"[{prefixo}] analisando {len(segs)} falas com a IA")
    cortes = aplicar_regra(escolher_cortes(transcricao, cfg), len(rms), cfg["nota_min"],
                           cfg["dur_min"], cfg["dur_max"], cfg["limite"])
    feitos = []
    for i, c in enumerate(cortes, 1):
        nome = f"{prefixo}_corte{i:02d}"
        print(f"[{prefixo}] {nome} nota {c['nota']:.1f}: {c['titulo']}")
        renderizar(video, c, palavras, saida, nome)
        c = {**c, "arquivo": f"{nome}.mp4", "thumbnail": f"{nome}.jpg", "lote": prefixo,
             "duracao": round(c["fim"] - c["inicio"], 1), "criado_em": dt.datetime.now().isoformat(timespec="seconds")}
        (saida / f"{nome}.json").write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")
        feitos.append(c)
    return feitos


def clipar_live(canal, info, saida, cfg):
    """Uma transmissão: grava em lotes de 10 min e corta cada lote assim que ele fecha."""
    pasta = saida / slug(info.get("uploader_id") or info.get("uploader") or canal) / time.strftime("%Y%m%d-%H%M%S")
    pasta.mkdir(parents=True)
    stream = {"titulo": info.get("description") or info.get("title"), "jogo": (info.get("categories") or [None])[0],
              "fonte": info.get("webpage_url") or canal, "inicio": dt.datetime.now().isoformat(timespec="seconds"),
              "pasta": str(pasta)}
    evento(cfg, "live_started", stream)
    todos, feitos = [], 0
    while info:
        # segment_start_number: se a live cair e voltar, os lotes continuam numerados na mesma pasta
        gravador = subprocess.Popen([FFMPEG, "-v", "error", "-i", info["url"], "-c", "copy", "-f", "segment",
                                     "-segment_time", str(LOTE_SEG), "-reset_timestamps", "1",
                                     "-segment_start_number", str(feitos), str(pasta / "lote_%04d.ts")])
        # ponytail: momentos que cruzam a borda de dois lotes se perdem; sobrepor lotes se isso incomodar
        while True:
            caiu = gravador.poll() is not None
            lotes = sorted(pasta.glob("lote_*.ts"))
            for lote in (lotes if caiu else lotes[:-1])[feitos:]:  # o último ainda está gravando
                novos = processar(lote, pasta, lote.stem, cfg)
                todos += novos
                feitos += 1
                indice = sorted(todos, key=lambda c: -c["nota"])
                (pasta / "cortes.json").write_text(json.dumps({**stream, "cortes": indice}, ensure_ascii=False,
                                                              indent=2), encoding="utf-8")
                evento(cfg, "live_clips", {**stream, "lote": lote.stem, "cortes": novos})
            if caiu:
                break
            time.sleep(15)
        info = None
        for _ in range(FIM_DE_VEZ_SEG // 30):  # caiu ou acabou? espera um pouco antes de dar como encerrada
            time.sleep(30)
            if info := ao_vivo(canal):
                break
    stream["fim"] = dt.datetime.now().isoformat(timespec="seconds")
    evento(cfg, "live_ended", {**stream, "total_cortes": len(todos)})


def monitorar(canal, saida, cfg):
    print(f"monitorando {canal} (Ctrl+C para parar)")
    while True:
        if no_horario(dt.datetime.now(), cfg["dias"], cfg["horas"]) and (info := ao_vivo(canal)):
            clipar_live(canal, info, saida, cfg)
        else:
            time.sleep(60)


def lista_int(s):
    return {int(x) for x in s.split(",") if x.strip()}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("entrada", help="arquivo, URL de vídeo ou URL do canal (Twitch, Kick, youtube.com/@canal/live)")
    p.add_argument("--monitorar", action="store_true", help="espera o canal entrar ao vivo e corta em lotes de 10 min")
    p.add_argument("--estrategia", default="", help="texto livre ou nome de estrategias/<nome>.txt")
    p.add_argument("--nota-min", type=float, default=6, help="descarta cortes abaixo desta nota (0-10)")
    p.add_argument("--limite-por-lote", type=int, default=10, help="máximo de cortes por vídeo ou lote")
    p.add_argument("--dur-min", type=int, default=15, help="duração mínima do corte (s)")
    p.add_argument("--dur-max", type=int, default=90, help="duração máxima do corte (s)")
    p.add_argument("--dias", type=lista_int, default=set(), help="dias para monitorar, 1=seg..7=dom (ex.: 1,2,3)")
    p.add_argument("--horas", type=lista_int, default=set(), help="horas para monitorar, 0-23 (ex.: 18,19,20)")
    p.add_argument("--webhook", default="", help="URL que recebe POST nos eventos live_started/live_clips/live_ended")
    p.add_argument("--saida", type=Path, default=Path("cortes"))
    a = p.parse_args()
    if not agentes_disponiveis():
        sys.exit("Nenhum agente de IA encontrado. Instale e faça login no Claude Code (claude), no Codex (codex login) ou no Gemini CLI (gemini).")
    a.saida.mkdir(parents=True, exist_ok=True)
    cfg = {"estrategia": carregar_estrategia(a.estrategia), "nota_min": a.nota_min, "limite": a.limite_por_lote,
           "dur_min": a.dur_min, "dur_max": a.dur_max, "dias": a.dias, "horas": a.horas, "webhook": a.webhook}
    if a.monitorar:
        monitorar(a.entrada, a.saida, cfg)
    else:
        fonte = Path(a.entrada) if Path(a.entrada).exists() else baixar(a.entrada, a.saida)
        cortes = processar(fonte, a.saida, fonte.stem, cfg)
        (a.saida / f"{fonte.stem}_cortes.json").write_text(json.dumps(cortes, ensure_ascii=False, indent=2),
                                                           encoding="utf-8")


if __name__ == "__main__":
    main()
