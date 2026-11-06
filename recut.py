"""re-cut: cortes verticais automáticos de lives e vídeos (modelado no Live Clipper do cut.pro).

    python recut.py video.mp4                                   # arquivo local
    python recut.py https://www.youtube.com/watch?v=...         # VOD
    python recut.py https://www.twitch.tv/canal --monitorar     # espera ficar ao vivo e corta em lotes de 10 min
    python recut.py https://kick.com/canal --monitorar --dias 1,2,3,4,5 --horas 18,19,20,21,22,23 \
        --estrategia reacoes --limite-por-lote 3 --webhook https://meu.app/hook

A IA usa a sessão local de um agente CLI já logado (Claude Code, Codex ou Gemini CLI), sem API key.
RECUT_AGENTE=gemini (ou claude, codex) define o preferido; se um falhar, tenta os outros.

--estrategia aceita texto livre ou o nome de um arquivo em estrategias/<nome>.txt (salva uma vez, reusa sempre).
--template usa templates/<nome>.json (proporção, enquadramento, estilo da legenda, título, logo, velocidade).

    python recut.py jobs/x/fonte_corte01.json jobs/x/fonte_corte02.json --reaplicar --template destaque
"""
import argparse
import datetime as dt
import functools
import glob
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
import uuid
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
Escreva 3 opções de legenda para o post (estilos diferentes: curiosidade, humor, direta), cada uma com até 150
caracteres, sem hashtags; as hashtags vão no campo próprio.
Use exatamente os tempos (em segundos) das linhas da transcrição.

Em cada corte, marque também os momentos que pedem um efeito de edição:
- risada: alguém ri ou algo é claramente engraçado;
- reacao: surpresa, choque, grito, susto;
- enfase: frase de efeito, número marcante ou afirmação forte;
- punchline: o payoff de uma piada ou o desfecho de uma história;
- virada: mudança brusca de assunto ou reviravolta.
Para cada momento: t (segundo exato em que acontece, dentro do corte), tipo, intensidade de 1 a 3 e um emoji que
combine. No máximo um momento a cada 4 segundos; se nada pede efeito, deixe a lista vazia."""

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
                    "legendas": {"type": "array", "items": {"type": "string"}},  # 3 opções; limpar_legendas garante
                    "momentos": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "t": {"type": "number"},
                                "tipo": {"type": "string", "enum": ["risada", "reacao", "enfase", "punchline", "virada"]},
                                "intensidade": {"type": "integer"},
                                "emoji": {"type": "string"},
                            },
                            "required": ["t", "tipo", "intensidade", "emoji"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["inicio", "fim", "titulo", "descricao", "nota", "motivo", "hashtags", "legendas", "momentos"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["cortes"],
    "additionalProperties": False,
}

# Template de corte, no modelo do editor do cut.pro (Template -> AspectRatio, AutoCropping.FramingMode,
# SubtitleDisplayConfig, SubtitleSettings{Style, Layout.Position, HighlightStyle, Animation}, Elements, Speed).
TEMPLATES = Path(__file__).with_name("templates")
PROPORCOES = {"9:16": (1080, 1920), "1:1": (1080, 1080), "4:5": (1080, 1350), "16:9": (1920, 1080)}
ENQUADRAMENTOS = ("rosto", "rosto_fixo", "centro", "ajustar")  # track / track sem câmera / center / fit-slot
ANIMACOES = ("nenhuma", "pop", "fade")
# fontes que o libass acha no Windows via DirectWrite; uma fonte ausente vira Arial sem aviso
FONTES = ("Arial", "Arial Black", "Impact", "Segoe UI Black", "Verdana", "Georgia", "Comic Sans MS", "Trebuchet MS")
POSICOES_LOGO = ("topo-direita", "topo-esquerda", "base-direita", "base-esquerda")
# momentos marcados pela IA e o que o template pode fazer em cada um (no cut.pro: auto_zoom, sfx, emojis)
TIPOS_MOMENTO = ("risada", "reacao", "enfase", "punchline", "virada")
EFEITOS = ("zoom", "som", "emoji", "flash")
SONS = Path(__file__).with_name("efeitos")
ID_SOM = r"[a-z0-9-]{1,40}(/[a-z0-9-]{1,40})?"  # "nome" (categoria geral) ou "categoria/nome"
# sons padrão gerados pelo próprio ffmpeg (sem arquivo de terceiros); os seus vão em efeitos/<categoria>/<nome>.wav|mp3
SONS_PADRAO = {  # "<categoria>/<nome>": fonte lavfi; vira efeitos/<categoria>/<nome>.wav
    "transicao/whoosh": "anoisesrc=d=0.6:c=pink:a=0.7,highpass=f=400,lowpass=f=4000,afade=t=in:d=0.3,afade=t=out:st=0.3:d=0.3,volume=4",
    "impacto/boom": "aevalsrc='0.7*sin(2*PI*(90-55*t)*t)*exp(-4.5*t)+0.25*(random(0)*2-1)*exp(-30*t)':d=0.9",
    "cartoon/pop": "aevalsrc='0.8*sin(2*PI*(1200-5000*t)*t)*exp(-28*t)':d=0.15",
    "interface/ding": "aevalsrc='0.5*sin(2*PI*1320*t)*exp(-3.5*t)+0.25*sin(2*PI*2640*t)*exp(-5*t)':d=1.2",
    "comedia/ba-dum-tss": ("aevalsrc='if(lt(t\\,0.15)\\,0.9*sin(2*PI*130*t)*exp(-22*t)\\,0)"
               "+if(between(t\\,0.18\\,0.36)\\,0.9*sin(2*PI*95*(t-0.18))*exp(-22*(t-0.18))\\,0)"
               "+if(gt(t\\,0.42)\\,0.45*(random(0)*2-1)*exp(-7*(t-0.42))\\,0)':d=1.1"),
}
TEMPLATE_PADRAO = {
    "nome": "classico",
    "descricao": "",
    "proporcao": "9:16",
    "enquadramento": "rosto",
    "velocidade": 1.0,
    "legenda": {
        "ativa": True, "palavras_por_grupo": 3, "pausa_max": 0.5, "respeitar_pontuacao": True,
        "fonte": "Arial", "tamanho": 84, "negrito": True, "italico": False, "maiusculas": True,
        "cor": "#FFFFFF", "contorno_cor": "#000000", "contorno": 6, "sombra": 2,
        "fundo": False, "fundo_cor": "#000000", "fundo_opacidade": 70,
        "destaque": False, "destaque_cor": "#FFD700",
        "posicao_y": 73, "animacao": "nenhuma",
    },
    "titulo": {"ativo": False, "segundos": 3, "tamanho": 60, "cor": "#000000", "fundo_cor": "#FFFFFF", "posicao_y": 14},
    "logo": {"arquivo": "", "largura": 18, "posicao": "topo-direita"},
    "efeitos": {
        "ativo": False,
        "intensidade_min": 2,
        "zoom": 1.3,
        "regras": {"risada": ["emoji", "som"], "reacao": ["zoom", "emoji"], "enfase": ["zoom"],
                   "punchline": ["zoom", "som"], "virada": ["flash", "som"]},
        "sons": {"risada": "comedia/ba-dum-tss", "reacao": "cartoon/pop", "enfase": "cartoon/pop",
                 "punchline": "impacto/boom", "virada": "transicao/whoosh"},
    },
}
_ASS_FORMATO = ("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
                "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
                "Alignment, MarginL, MarginR, MarginV, Encoding")


# ---------- funções puras (testadas em test_recut.py) ----------

def ts_ass(seg):
    cs = max(0, round(seg * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def normalizar_template(dados):
    """Mescla sobre o padrão e valida; levanta ValueError com a mensagem para o usuário."""
    t = json.loads(json.dumps(TEMPLATE_PADRAO))
    for k, v in (dados or {}).items():
        if k == "efeitos" and isinstance(v, dict) and isinstance(v.get("sons"), dict):
            v = {**v, "sons": {**t["efeitos"]["sons"], **v["sons"]}}
        if isinstance(t.get(k), dict) and isinstance(v, dict):
            t[k].update({kk: vv for kk, vv in v.items() if kk in t[k]})
        elif k in t:
            t[k] = v
    t["nome"] = slug(str(t["nome"]))
    t["descricao"] = str(t["descricao"])[:300]
    leg, tit, logo, efe = t["legenda"], t["titulo"], t["logo"], t["efeitos"]
    # (dict, campo, tipo, mínimo, máximo): o valor convertido substitui o enviado, então "6,0\nDialogue..."
    # não passa como número nem entra cru na linha Style do ASS
    numeros = [(t, "velocidade", float, 0.5, 2), (leg, "palavras_por_grupo", int, 1, 12), (leg, "pausa_max", float, 0, 5),
               (leg, "tamanho", int, 20, 200), (leg, "contorno", int, 0, 20), (leg, "sombra", int, 0, 10),
               (leg, "fundo_opacidade", int, 0, 100), (leg, "posicao_y", float, 0, 100), (tit, "segundos", float, 0, 60),
               (tit, "tamanho", int, 20, 200), (tit, "posicao_y", float, 0, 100), (logo, "largura", float, 5, 60),
               (efe, "intensidade_min", int, 1, 3), (efe, "zoom", float, 1.05, 2)]
    for d, campo, tipo, minimo, maximo in numeros:
        valor = d[campo]
        if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not minimo <= valor <= maximo:
            raise ValueError(f"{campo.replace('_', ' ')} deve ser um número entre {minimo} e {maximo}")
        d[campo] = tipo(valor)
    for d, campo in [(leg, "ativa"), (leg, "respeitar_pontuacao"), (leg, "negrito"), (leg, "italico"),
                     (leg, "maiusculas"), (leg, "fundo"), (leg, "destaque"), (tit, "ativo"), (efe, "ativo")]:
        if not isinstance(d[campo], bool):
            raise ValueError(f"{campo.replace('_', ' ')} deve ser verdadeiro ou falso")
    cores = (leg["cor"], leg["contorno_cor"], leg["fundo_cor"], leg["destaque_cor"], tit["cor"], tit["fundo_cor"])
    regras = [
        (t["proporcao"] in PROPORCOES, f"proporção deve ser uma de {', '.join(PROPORCOES)}"),
        (t["enquadramento"] in ENQUADRAMENTOS, f"enquadramento deve ser um de {', '.join(ENQUADRAMENTOS)}"),
        (leg["fonte"] in FONTES, f"fonte deve ser uma de {', '.join(FONTES)}"),
        (leg["animacao"] in ANIMACOES, f"animação deve ser uma de {', '.join(ANIMACOES)}"),
        (all(isinstance(c, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", c) for c in cores), "cores no formato #RRGGBB"),
        (logo["posicao"] in POSICOES_LOGO, "posição do logo inválida"),
        (isinstance(logo["arquivo"], str), "arquivo do logo inválido"),
        (isinstance(efe["regras"], dict) and set(efe["regras"]) <= set(TIPOS_MOMENTO) and all(
            isinstance(v, list) and set(v) <= set(EFEITOS) for v in efe["regras"].values()),
         f"efeitos: regras por tipo ({', '.join(TIPOS_MOMENTO)}) com efeitos entre {', '.join(EFEITOS)}"),
        (isinstance(efe["sons"], dict) and set(efe["sons"]) <= set(TIPOS_MOMENTO) and all(
            isinstance(v, str) and re.fullmatch(ID_SOM, v) for v in efe["sons"].values()),
         "efeitos: som deve ser 'categoria/nome' de um arquivo em efeitos/ (minúsculas, números e hífen)"),
    ]
    for ok, msg in regras:
        if not ok:
            raise ValueError(msg)
    return t


def carregar_template(nome):
    """Template salvo em templates/<nome>.json; vazio = padrão (o visual de antes dos templates)."""
    if not nome:
        return normalizar_template({})
    arquivo = TEMPLATES / f"{slug(nome)}.json"
    if not arquivo.is_file():
        raise ValueError(f"template '{nome}' não encontrado")
    return normalizar_template(json.loads(arquivo.read_text(encoding="utf-8")))


def limpar_momentos(momentos, inicio, fim, espaco=2.0):
    """Momentos válidos dentro do corte, intensidade 1-3, sem dois colados (fica o mais intenso)."""
    bons = []
    for m in momentos or []:
        try:
            t, tipo, inten = float(m["t"]), m["tipo"], int(m["intensidade"])
        except (KeyError, TypeError, ValueError):
            continue
        if tipo in TIPOS_MOMENTO and inicio <= t <= fim:
            emoji = re.sub(r"[{}\\\n\r]", "", str(m.get("emoji", "")))[:8]
            bons.append({"t": round(t, 2), "tipo": tipo, "intensidade": min(3, max(1, inten)), "emoji": emoji})
    finais = []
    for m in sorted(bons, key=lambda m: (-m["intensidade"], m["t"])):
        if all(abs(m["t"] - f["t"]) >= espaco for f in finais):
            finais.append(m)
    return sorted(finais, key=lambda m: m["t"])


def plano_efeitos(momentos, tpl, inicio):
    """(t relativo ao corte, efeito, momento) que o template manda aplicar."""
    efe = tpl["efeitos"]
    if not efe["ativo"]:
        return []
    return [(round(m["t"] - inicio, 2), efeito, m) for m in momentos if m["intensidade"] >= efe["intensidade_min"]
            for efeito in efe["regras"].get(m["tipo"], [])]


def palavras_do_corte(palavras, inicio, fim):
    return [w for w in palavras if w[0] >= inicio and w[1] <= fim]


def cor_ass(hexa, opacidade=100):
    """#RRGGBB -> &HAABBGGRR do ASS (alfa invertido: 00 = opaco)."""
    r, g, b = hexa[1:3], hexa[3:5], hexa[5:7]
    return f"&H{round(255 * (100 - opacidade) / 100):02X}{b}{g}{r}".upper()


def agrupar_palavras(ws, por_grupo, pausa_max, pontuacao):
    """Blocos de legenda: até N palavras, quebrando em pausa longa ou fim de frase (SubtitleDisplayConfig)."""
    grupos, atual = [], []
    for w in ws:
        if atual and (len(atual) >= por_grupo or w[0] - atual[-1][1] > pausa_max):
            grupos.append(atual)
            atual = []
        atual.append(w)
        if pontuacao and re.search(r"[.!?…,;:]$", w[2]):
            grupos.append(atual)
            atual = []
    return grupos + ([atual] if atual else [])


def legenda_ass(palavras, inicio, fim, tpl=None, titulo="", plano=()):
    """Legenda, título e figurinhas de emoji do corte no estilo do template; tempos relativos ao corte e
    ajustados à velocidade. `plano` vem de plano_efeitos (tempos já relativos ao corte)."""
    tpl = tpl or normalizar_template({})
    W, H = PROPORCOES[tpl["proporcao"]]
    leg, tit, vel = tpl["legenda"], tpl["titulo"], tpl["velocidade"]
    caixa = leg["fundo"]  # BorderStyle 3: caixa opaca atrás do texto em vez de contorno
    borda = cor_ass(leg["fundo_cor"], leg["fundo_opacidade"]) if caixa else cor_ass(leg["contorno_cor"])
    estilos = [
        f"Style: Legenda,{leg['fonte']},{leg['tamanho']},{cor_ass(leg['cor'])},{cor_ass(leg['cor'])},{borda},"
        f"{cor_ass('#000000', 60)},{-1 if leg['negrito'] else 0},{-1 if leg['italico'] else 0},0,0,100,100,0,0,"
        f"{3 if caixa else 1},{12 if caixa else leg['contorno']},{0 if caixa else leg['sombra']},5,60,60,0,1",
        f"Style: Titulo,{leg['fonte']},{tit['tamanho']},{cor_ass(tit['cor'])},{cor_ass(tit['cor'])},"
        f"{cor_ass(tit['fundo_cor'])},{cor_ass(tit['fundo_cor'])},-1,0,0,0,100,100,0,0,3,14,0,5,80,80,0,1",
        # o libass desenha emoji em uma cor só: vira figurinha amarela com contorno grosso
        f"Style: Emoji,Segoe UI Emoji,{round(min(W, H) * 0.2)},{cor_ass('#FFD43B')},{cor_ass('#FFD43B')},"
        f"{cor_ass('#000000')},{cor_ass('#000000', 50)},0,0,0,0,100,100,0,0,1,7,3,5,0,0,0,1",
    ]

    def t(seg):
        return ts_ass((seg - inicio) / vel)

    def pos(y):
        return f"\\an5\\pos({W // 2},{round(H * float(y) / 100)})"

    def limpar(txt):
        return (txt.upper() if leg["maiusculas"] else txt).replace("{", "(").replace("}", ")")

    anim = {"nenhuma": "", "pop": "\\fscx70\\fscy70\\t(0,90,\\fscx100\\fscy100)", "fade": "\\fad(120,0)"}[leg["animacao"]]
    eventos = []
    if tit["ativo"] and titulo:
        fim_tit = fim if not tit["segundos"] else min(fim, inicio + float(tit["segundos"]) * vel)
        eventos.append(f"Dialogue: 1,{t(inicio)},{t(fim_tit)},Titulo,,0,0,0,,{{{pos(tit['posicao_y'])}}}{limpar(titulo)}")
    emojis = [(rel, m["emoji"]) for rel, efeito, m in plano if efeito == "emoji" and m["emoji"]]
    for k, (rel, emoji) in enumerate(emojis):  # alterna os lados para não cobrir sempre o mesmo ponto
        x, giro = (round(W * 0.76), -12) if k % 2 == 0 else (round(W * 0.24), 12)
        eventos.append(f"Dialogue: 2,{ts_ass(rel / vel)},{ts_ass((rel + 1.3) / vel)},Emoji,,0,0,0,,"
                       f"{{\\an5\\pos({x},{round(H * 0.3)})\\frz{giro}\\fscx40\\fscy40"
                       f"\\t(0,140,\\fscx115\\fscy115)\\t(140,240,\\fscx100\\fscy100)\\fad(0,200)}}{emoji}")
    if leg["ativa"]:
        ws = palavras_do_corte(palavras, inicio, fim)
        grupos = agrupar_palavras(ws, int(leg["palavras_por_grupo"]), float(leg["pausa_max"]), leg["respeitar_pontuacao"])
        for n, g in enumerate(grupos):
            # segura o bloco até o próximo quando a pausa é curta, para a legenda não piscar entre frases
            prox = grupos[n + 1][0][0] if n + 1 < len(grupos) else None
            fim_g = prox if prox is not None and prox - g[-1][1] <= float(leg["pausa_max"]) else g[-1][1]
            if not leg["destaque"]:
                texto = " ".join(limpar(w[2]) for w in g)
                eventos.append(f"Dialogue: 0,{t(g[0][0])},{t(fim_g)},Legenda,,0,0,0,,"
                               f"{{{pos(leg['posicao_y'])}{anim}}}{texto}")
                continue
            # HighlightStyle: um evento por palavra falada, com ela pintada na cor de destaque
            for i, w in enumerate(g):
                fim_w = g[i + 1][0] if i + 1 < len(g) else fim_g
                partes = [f"{{\\c{cor_ass(leg['destaque_cor'])}}}{limpar(x[2])}{{\\c{cor_ass(leg['cor'])}}}" if j == i
                          else limpar(x[2]) for j, x in enumerate(g)]
                eventos.append(f"Dialogue: 0,{t(w[0])},{t(fim_w)},Legenda,,0,0,0,,"
                               f"{{{pos(leg['posicao_y'])}{anim if i == 0 else ''}}}{' '.join(partes)}")
    return (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {W}\nPlayResY: {H}\nWrapStyle: 0\n\n"
            f"[V4+ Styles]\n{_ASS_FORMATO}\n" + "\n".join(estilos) +
            "\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n" +
            "\n".join(eventos) + "\n")


def recorte_vertical(centro_x, iw, ih, ar=9 / 16):
    """(x, largura) do recorte na proporção `ar` (largura/altura) centrado no rosto, ou None se não cabe cortar."""
    w = int(ih * ar) // 2 * 2
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


def ancora_zoom(t, xs, ys, passo, iw, ih, W, H, modo, crop_x=None):
    """(ax, ay) de 0 a 1 no quadro final para onde o zoom do instante t (relativo ao corte) deve mirar:
    a amostra de rosto mais próxima, convertida pelo enquadramento. Sem rosto perto: centro, um pouco acima."""
    perto = sorted((abs(i * passo - t), i) for i, x in enumerate(xs) if x is not None and abs(i * passo - t) <= 1.5)
    if not perto:
        return 0.5, 0.45
    i = perto[0][1]
    fx, fy = xs[i], ys[i] * ih
    if modo == "ajustar":  # vídeo inteiro encaixado no meio do quadro
        k = min(W / iw, H / ih)
        ox, oy = (W - iw * k) / 2, (H - ih * k) / 2
        ax, ay = (ox + fx * k) / W, (oy + fy * k) / H
    elif crop_x is not None:  # recorte da largura (altura inteira)
        ax, ay = (fx - crop_x) / (int(ih * W / H) // 2 * 2), fy / ih  # mesma largura par de recorte_vertical
    else:  # fonte mais estreita que o destino: recorte da altura, centralizado
        h = iw * H / W
        ax, ay = fx / iw, (fy - (ih - h) / 2) / h
    return round(min(1, max(0, ax)), 3), round(min(1, max(0, ay)), 3)


def expr_por_momento(zooms, indice, padrao):
    """Expressão que vale zooms[i][indice] perto de cada momento e `padrao` fora deles (momentos ficam 2s+ apart)."""
    termos = "".join(f"{z[indice] - padrao:+.3f}*between(it\\,{z[0] - 0.15:.2f}\\,{z[0] + 1.2:.2f})" for z in zooms)
    return f"{padrao}{termos}"


def expr_zoom(tempos, fator):
    """Expressão do zoompan: entra rápido no momento (punch-in de 80 ms), segura e sai em 200 ms."""
    termos = "+".join(f"clip((it-{t - 0.06:.2f})/0.08\\,0\\,1)*clip(({t + 0.9:.2f}-it)/0.2\\,0\\,1)" for t in tempos)
    return f"1+{fator - 1:.3f}*min(1\\,{termos})"


def filtro_video(tpl, iw, ih, nome, x=None, seguir=False, com_logo=False, zooms=(), flashes=(), com_emoji=False):
    """filter_complex do ffmpeg para o template. x: posição do recorte (None = centro); com seguir=True
    ele é só o primeiro quadro e o resto vem do arquivo <nome>.cmd via sendcmd. zooms: (t, ax, ay) com t em
    segundos relativos ao corte e (ax, ay) o rosto no quadro final (ancora_zoom); flashes: segundos."""
    W, H = PROPORCOES[tpl["proporcao"]]
    modo = tpl["enquadramento"]
    rec = recorte_vertical(iw / 2, iw, ih, W / H)
    if modo == "ajustar":  # fit-slot: vídeo inteiro sobre o próprio vídeo desfocado
        v = (f"[0:v]split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=20:2[bg];"
             f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")
    elif rec is None:  # fonte mais estreita que o destino: corta a altura, centralizado
        h = int(iw * H / W) // 2 * 2
        v = f"[0:v]crop={iw}:{h}:0:{(ih - h) // 2},scale={W}:{H}"
    elif seguir:
        v = f"[0:v]sendcmd=f={nome}.cmd,crop@rosto={rec[1]}:{ih}:{rec[0] if x is None else x}:0,scale={W}:{H}"
    else:
        v = f"[0:v]crop={rec[1]}:{ih}:{rec[0] if x is None else x}:0,scale={W}:{H}"
    if zooms:  # fps=30 antes: o zoompan gera 1 quadro por quadro de entrada no fps pedido; fixar evita mudar a duração
        ax, ay = expr_por_momento(zooms, 1, 0.5), expr_por_momento(zooms, 2, 0.45)
        z = expr_zoom([t for t, _, _ in zooms], tpl["efeitos"]["zoom"])
        v += (f",fps=30,zoompan=z='{z}'"
              f":x='max(0\\,min(iw-iw/zoom\\,iw*({ax})-iw/zoom/2))'"
              f":y='max(0\\,min(ih-ih/zoom\\,ih*({ay})-ih/zoom/2))':d=1:s={W}x{H}:fps=30")
    for t in flashes:  # transição de "virada": clarão branco rápido
        v += (f",drawbox=x=0:y=0:w=iw:h=ih:color=white@0.8:t=fill:enable='between(t\\,{t:.2f}\\,{t + 0.06:.2f})'"
              f",drawbox=x=0:y=0:w=iw:h=ih:color=white@0.35:t=fill:enable='between(t\\,{t + 0.06:.2f}\\,{t + 0.18:.2f})'")
    if tpl["velocidade"] != 1:
        v += f",setpts=PTS/{tpl['velocidade']}"
    if tpl["legenda"]["ativa"] or tpl["titulo"]["ativo"] or com_emoji:
        v += f",subtitles={nome}.ass"
    if not com_logo:
        return v + "[out]"
    lw = round(W * float(tpl["logo"]["largura"]) / 100)
    m = 40
    x, y = {"topo-direita": (f"W-w-{m}", m), "topo-esquerda": (m, m),
            "base-direita": (f"W-w-{m}", f"H-h-{m}"), "base-esquerda": (m, f"H-h-{m}")}[tpl["logo"]["posicao"]]
    return f"{v}[v];[1:v]scale={lw}:-1[lg];[v][lg]overlay={x}:{y}[out]"


def filtro_audio(tempos, primeiro_indice, velocidade):
    """Mixa os efeitos sonoros no áudio do corte. tempos: segundos relativos ao corte, um input do ffmpeg
    por som a partir de `primeiro_indice`. None quando não há som (o áudio segue direto)."""
    if not tempos:
        return None
    partes = ["[0:a]aresample=44100[a0]"]
    for k, t in enumerate(tempos):
        ms = max(0, round(t * 1000))
        partes.append(f"[{primeiro_indice + k}:a]aresample=44100,adelay={ms}:all=1,volume=0.9[s{k}]")
    entradas = "[a0]" + "".join(f"[s{k}]" for k in range(len(tempos)))
    tempo = f",atempo={velocidade}" if velocidade != 1 else ""
    partes.append(f"{entradas}amix=inputs={len(tempos) + 1}:normalize=0:duration=first{tempo},alimiter=limit=0.95[aout]")
    return ";".join(partes)


def energia_relativa(rms, inicio, fim):
    mediana = statistics.median(rms) or 1
    trecho = rms[int(inicio):max(int(fim), int(inicio) + 1)] or [0]
    return statistics.fmean(trecho) / mediana


def resumo_da_regra(sugeridos, cortes, duracao, cfg):
    """Quantos cortes a IA sugeriu e por que cada um ficou de fora (nota baixa, duração, limite)."""
    nota = sum(c["nota"] < cfg["nota_min"] for c in sugeridos)
    dur = sum(c["nota"] >= cfg["nota_min"] and not cfg["dur_min"] <= min(duracao, c["fim"]) - max(0.0, c["inicio"]) <= cfg["dur_max"]
              for c in sugeridos)
    limite = len(sugeridos) - nota - dur - len(cortes)
    fora = [f"{n} {motivo}" for n, motivo in [(nota, f"com nota abaixo de {cfg['nota_min']:g}"),
            (dur, f"fora de {cfg['dur_min']}-{cfg['dur_max']}s"), (limite, f"acima do limite de {cfg['limite']}")] if n]
    return f"IA sugeriu {len(sugeridos)} cortes, ficaram {len(cortes)}" + (f" (descartados: {', '.join(fora)})" if fora else "")


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


ETAPAS = ("entrada", "baixar", "transcrever", "ia", "renderizar", "ranking")
PREFIXO_EVENTO = "@@ "  # linhas do log que a interface lê para animar a esteira
ETAPA_ATUAL, ITEM_ATUAL = "entrada", ""


def marcar(etapa, estado, item="", **dados):
    """Evento estruturado no log: `@@ {json}`; dados opcionais: progresso (0-1), msg, n, corte."""
    global ETAPA_ATUAL, ITEM_ATUAL
    ETAPA_ATUAL, ITEM_ATUAL = etapa, item
    ev = {"etapa": etapa, "estado": estado, "item": item, "t": dt.datetime.now().isoformat(timespec="seconds"), **dados}
    print(PREFIXO_EVENTO + json.dumps(ev, ensure_ascii=False), flush=True)


def marcar_erro(e):
    """Fecha com `erro` o (etapa, item) que ficou aberto no último marcar."""
    marcar(ETAPA_ATUAL, "erro", ITEM_ATUAL, msg=str(e))


def limpar_legendas(c):
    """Exatamente 3 legendas não vazias (<= 2200 caracteres); completa com descrição e título."""
    cand = [*(c.get("legendas") or []), c.get("descricao"), c.get("titulo")]
    ls = [x.strip()[:2200] for x in cand if isinstance(x, str) and x.strip()][:3]
    while len(ls) < 3:  # ponytail: sem texto nenhum sobra legenda vazia; o corte já exige título
        ls.append(ls[-1] if ls else "")
    return ls


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
    ultimo = [0.0]

    def hook(d):
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        if d["status"] == "downloading" and total:
            p = d["downloaded_bytes"] / total
            if p - ultimo[0] >= 0.05:  # no máximo a cada 5%
                ultimo[0] = p
                marcar("baixar", "progresso", "fonte", progresso=round(p, 2), msg=f"Baixando {p:.0%}")

    opts = {**YTDLP, "outtmpl": str(saida / "fonte.%(ext)s"), "format": "bv*[height<=1080]+ba/b",
            "merge_output_format": "mp4", "progress_hooks": [hook]}
    marcar("baixar", "inicio", "fonte", msg=f"Baixando {url}")
    with yt_dlp.YoutubeDL(opts) as ydl:
        arq = Path(ydl.extract_info(url)["requested_downloads"][0]["filepath"])
    marcar("baixar", "fim", "fonte", msg="Download concluído")
    return arq


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
    item = Path(video).stem
    marcar("transcrever", "inicio", item, msg=f"Transcrevendo {item}")
    segmentos, info = whisper().transcribe(str(video), word_timestamps=True, vad_filter=True)
    segs, palavras, ultimo = [], [], 0.0
    for s in segmentos:
        segs.append((s.start, s.end, s.text.strip()))
        palavras += [(w.start, w.end, w.word.strip()) for w in s.words]
        p = s.end / info.duration if info.duration else 0
        if p - ultimo >= 0.05:  # no máximo a cada 5%
            ultimo = p
            marcar("transcrever", "progresso", item, progresso=round(min(p, 1), 2), msg=f"Transcrevendo {p:.0%}")
    marcar("transcrever", "fim", item, n=len(segs), msg=f"{len(segs)} falas transcritas")
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


def escolher_cortes(transcricao, cfg, item=""):
    sistema = SISTEMA.format(dur_min=cfg["dur_min"], dur_max=cfg["dur_max"])
    if cfg["estrategia"]:
        sistema += f"\n\nEstratégia do criador (o que procurar e como escrever os títulos; siga-a):\n{cfg['estrategia']}"
    marcar("ia", "inicio", item, msg="Escolhendo cortes com a IA")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:  # cwd vazio: o agente não lê CLAUDE.md/AGENTS.md do projeto
        for nome, exe in agentes_disponiveis(os.getenv("RECUT_AGENTE", "")):
            try:
                cortes = rodar_agente(nome, exe, sistema, transcricao, Path(tmp))["cortes"]
                marcar("ia", "fim", item, n=len(cortes), msg=f"{nome} sugeriu {len(cortes)} cortes")
                return cortes
            except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as e:
                print(f"  {nome} falhou ({str(e)[:200]}); a sessão está ativa? tentando o próximo", file=sys.stderr)
    print("  nenhum agente respondeu; lote sem cortes", file=sys.stderr)
    marcar("ia", "erro", item, msg="Nenhum agente respondeu")
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
    xs, ys = [], []
    for _ in range(int((fim - inicio) / passo) + 1):
        ok, frame = cap.read()
        for _ in range(pular - 1):  # grab() só avança, sem converter o quadro
            cap.grab()
        if not ok:
            break
        cinza = cv2.cvtColor(cv2.resize(frame, None, fx=escala, fy=escala), cv2.COLOR_BGR2GRAY)
        rostos = det.detectMultiScale(cinza, 1.2, 5, minSize=(40, 40))
        if len(rostos):
            x, y, w, h = max(rostos, key=lambda r: r[2] * r[3])
            xs.append((x + w / 2) / escala)
            ys.append((y + h / 2) / escala / ih)
        else:
            xs.append(None)
            ys.append(None)
    cap.release()
    return xs, ys, iw, ih


def garantir_sons():
    """Cria efeitos/<categoria>/ com os sons padrão (gerados pelo ffmpeg) na primeira vez."""
    for som_id, fonte in SONS_PADRAO.items():
        destino = SONS / f"{som_id}.wav"
        if not destino.is_file():
            destino.parent.mkdir(parents=True, exist_ok=True)
            tmp = destino.with_name(f".{destino.stem}.{uuid.uuid4().hex}.wav")  # único por chamada (threads do servidor)
            subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", fonte, "-ar", "44100", str(tmp)],
                           check=True)
            os.replace(tmp, destino)


def listar_sons():
    """Biblioteca de sons por categoria: efeitos/<categoria>/<nome>.wav|mp3; soltos na raiz = 'geral'."""
    garantir_sons()
    sons = []
    for f in sorted([*SONS.glob("*.*"), *SONS.glob("*/*.*")]):
        som_id = f.relative_to(SONS).with_suffix("").as_posix()
        if f.suffix.lower() in (".wav", ".mp3") and re.fullmatch(ID_SOM, som_id):
            categoria = som_id.split("/")[0] if "/" in som_id else "geral"
            sons.append({"id": som_id, "categoria": categoria, "nome": f.stem})
    return sons


def arquivo_som(som_id):
    """Caminho do som pelo id, só dentro de efeitos/ (o id já é validado no template)."""
    if not re.fullmatch(ID_SOM, som_id or ""):
        return None
    for f in (SONS / f"{som_id}.wav", SONS / f"{som_id}.mp3"):
        if f.is_file() and f.resolve().is_relative_to(SONS.resolve()):
            return f
    return None


def tem_audio(video):
    """O vídeo tem trilha de áudio? (o ffmpeg lista os streams no stderr ao abrir o arquivo)"""
    r = subprocess.run([FFMPEG, "-hide_banner", "-i", str(video)], capture_output=True, text=True, errors="replace")
    return re.search(r"Stream #\d+:\d+.*: Audio:", r.stderr) is not None


def tamanho_video(video):
    import cv2
    cap = cv2.VideoCapture(str(video))
    iw, ih = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return iw, ih


def renderizar(video, c, palavras, saida, nome, tpl=None):
    tpl = tpl or normalizar_template({})
    W, H = PROPORCOES[tpl["proporcao"]]
    dur, vel = c["fim"] - c["inicio"], tpl["velocidade"]
    modo = tpl["enquadramento"]
    x, seguir = None, False
    plano = plano_efeitos(c.get("momentos", []), tpl, c["inicio"])
    por_efeito = {e: [(rel, m) for rel, efeito, m in plano if efeito == e] for e in EFEITOS}
    tempos_zoom = [rel for rel, _ in por_efeito["zoom"]]
    if modo in ("rosto", "rosto_fixo") or tempos_zoom:  # o zoom mira o rosto em qualquer enquadramento
        xs, ys, iw, ih = trajetoria_do_rosto(video, c["inicio"], c["fim"])
    else:
        (iw, ih), xs, ys = tamanho_video(video), [], []
    rec = recorte_vertical(iw / 2, iw, ih, W / H)
    trajetoria = suavizar_trajetoria(xs, iw / 2, zona_morta=0.06 * rec[1]) if rec and xs else []
    if modo in ("rosto", "rosto_fixo") and rec:
        seguir = modo == "rosto"
        if seguir:
            (saida / f"{nome}.cmd").write_text(comandos_crop(trajetoria, PASSO_ROSTO, iw, rec[1]), encoding="utf-8")
        # rosto: x do primeiro quadro; rosto_fixo (DisableCameraMotion): onde o rosto mais ficou
        x = recorte_vertical(trajetoria[0] if seguir else statistics.median(trajetoria), iw, ih, W / H)[0]

    def crop_x_em(t):  # x do recorte no instante t, do jeito que o filtro vai cortar
        if modo == "ajustar" or not rec:
            return None
        if seguir:
            return recorte_vertical(trajetoria[min(round(t / PASSO_ROSTO), len(trajetoria) - 1)], iw, ih, W / H)[0]
        return rec[0] if x is None else x

    zooms = [(t, *ancora_zoom(t, xs, ys, PASSO_ROSTO, iw, ih, W, H, modo, crop_x_em(t))) for t in tempos_zoom]
    logo = tpl["logo"]["arquivo"]
    com_logo = bool(logo) and Path(logo).is_file()
    if logo and not com_logo:
        print(f"  logo não encontrado ({logo}); seguindo sem logo", file=sys.stderr)
    (saida / f"{nome}.ass").write_text(legenda_ass(palavras, c["inicio"], c["fim"], tpl, c.get("titulo", ""), plano),
                                       encoding="utf-8")
    sons, pedidos_som = [], por_efeito["som"]
    if pedidos_som and not tem_audio(video):  # sem trilha não há onde mixar ([0:a] não existiria)
        print("  vídeo sem áudio; seguindo sem os sons de efeito", file=sys.stderr)
        pedidos_som = []
    if pedidos_som:
        garantir_sons()
    for rel, m in pedidos_som:
        arq = arquivo_som(tpl["efeitos"]["sons"].get(m["tipo"], ""))
        if arq:
            sons.append((rel, arq))
        else:
            print(f"  som de '{m['tipo']}' não encontrado em efeitos/; seguindo sem ele", file=sys.stderr)
    args = [FFMPEG, "-v", "error", "-y", "-ss", f"{c['inicio']:.2f}", "-t", f"{dur:.2f}", "-i", str(Path(video).resolve())]
    if com_logo:
        args += ["-i", str(Path(logo).resolve())]
    for _, arq in sons:
        args += ["-i", str(arq.resolve())]
    grafo = filtro_video(tpl, iw, ih, nome, x, seguir, com_logo,
                         zooms=zooms, flashes=[rel for rel, _ in por_efeito["flash"]], com_emoji=bool(por_efeito["emoji"]))
    audio = filtro_audio([rel for rel, _ in sons], 2 if com_logo else 1, vel)
    if audio:
        args += ["-filter_complex", f"{grafo};{audio}", "-map", "[out]", "-map", "[aout]"]
    else:
        args += ["-filter_complex", grafo, "-map", "[out]", "-map", "0:a?"]
        if vel != 1:
            args += ["-af", f"atempo={vel}"]
    # cwd=saida: caminhos relativos nos filtros evitam o escape de "C:" no Windows
    subprocess.run(args + ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", f"{nome}.mp4"],
                   cwd=saida, check=True)
    subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", f"{dur / vel / 2:.2f}", "-i", f"{nome}.mp4",
                    "-frames:v", "1", f"{nome}.jpg"], cwd=saida, check=True)


def reaplicar(arquivos, tpl):
    """Renderiza de novo cortes prontos com outro template (apply_template do cut.pro), sem chamar a IA."""
    for arq in map(Path, arquivos):
        c = json.loads(arq.read_text(encoding="utf-8"))
        if "palavras" not in c or not Path(c.get("fonte", "")).is_file():
            print(f"[{arq.stem}] sem palavras ou vídeo de origem salvos; gere o corte de novo", file=sys.stderr)
            continue
        print(f"[{arq.stem}] aplicando template {tpl['nome']}")
        renderizar(Path(c["fonte"]), c, [tuple(w) for w in c["palavras"]], arq.parent, arq.stem, tpl)
        c["template"] = tpl["nome"]
        c["duracao"] = round((c["fim"] - c["inicio"]) / tpl["velocidade"], 1)
        gravar_json(arq, c)
        atualizar_indices(arq.parent)


def publico(c):
    """O corte sem os campos internos (caminho local do vídeo e transcrição), para índices e webhook."""
    return {k: v for k, v in c.items() if k not in ("fonte", "palavras")}


def cortes_da_pasta(pasta, prefixo=""):
    """Os cortes como estão no disco (fonte da verdade), sem campos internos, pela nota."""
    padrao = f"{glob.escape(prefixo)}_corte[0-9]*.json" if prefixo else "*_corte[0-9]*.json"
    cortes = (publico(json.loads(f.read_text(encoding="utf-8"))) for f in pasta.glob(padrao))
    return sorted(cortes, key=lambda c: -c["nota"])


def gravar_json(arquivo, dados):
    """Grava num temporário e troca de uma vez: quem lê nunca pega o arquivo pela metade."""
    tmp = arquivo.with_name(f".{arquivo.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    for espera in (0.05, 0.1, 0.2, 0.4):  # Windows: o replace falha se outro processo está lendo o destino
        try:
            return os.replace(tmp, arquivo)
        except PermissionError:
            time.sleep(espera)
    os.replace(tmp, arquivo)


def atualizar_indices(pasta, cabecalho_live=None):
    """Refaz os índices da pasta (cortes.json da live, <fonte>_cortes.json do vídeo) a partir do disco.
    A live e a reaplicação podem escrever ao mesmo tempo; como os dois reconstroem do disco em vez de
    editar a lista, nenhum apaga o corte que o outro acabou de gravar. É melhor esforço: o índice é
    derivado dos .json dos cortes, então uma falha aqui não pode derrubar a live."""
    # ponytail: sem lock entre processos; sobra uma janela de milissegundos em que um índice pode sair
    # sem o corte gravado no mesmo instante, e o próximo lote ou reaplicação conserta
    try:
        live = pasta / "cortes.json"
        if cabecalho_live is not None or live.is_file():
            cabecalho = cabecalho_live if cabecalho_live is not None else json.loads(live.read_text(encoding="utf-8"))
            gravar_json(live, {**cabecalho, "cortes": cortes_da_pasta(pasta)})
        for idx in pasta.glob("*_cortes.json"):
            gravar_json(idx, cortes_da_pasta(pasta, idx.name.removesuffix("_cortes.json")))
    except (OSError, ValueError) as e:  # ValueError inclui JSONDecodeError
        print(f"  índice não atualizado agora ({e}); o próximo lote ou reaplicação refaz", file=sys.stderr)


def processar(video, saida, prefixo, cfg):
    """Um vídeo ou um lote de live -> cortes renderizados. Devolve os metadados dos cortes."""
    print(f"[{prefixo}] transcrevendo")
    segs, palavras = transcrever(video)
    if not segs:
        return []
    rms = rms_por_segundo(video)
    transcricao = "\n".join(f"[{s:.1f}-{e:.1f}] (energia {energia_relativa(rms, s, e):.1f}x) {t}" for s, e, t in segs)
    print(f"[{prefixo}] analisando {len(segs)} falas com a IA")
    sugeridos = escolher_cortes(transcricao, cfg, prefixo)
    cortes = aplicar_regra(sugeridos, len(rms), cfg["nota_min"], cfg["dur_min"], cfg["dur_max"], cfg["limite"])
    print(f"[{prefixo}] {resumo_da_regra(sugeridos, cortes, len(rms), cfg)}")
    feitos = []
    if cortes:
        marcar("renderizar", "inicio", prefixo, n=len(cortes), msg=f"Renderizando {len(cortes)} cortes")
    for i, c in enumerate(cortes, 1):
        nome = f"{prefixo}_corte{i:02d}"
        c["momentos"] = limpar_momentos(c.get("momentos"), c["inicio"], c["fim"])
        print(f"[{prefixo}] {nome} nota {c['nota']:.1f}: {c['titulo']}")
        renderizar(video, c, palavras, saida, nome, cfg["template"])
        marcar("renderizar", "progresso", prefixo, corte=nome, progresso=round(i / len(cortes), 2), msg=f"{nome} pronto")
        c = {**c, "legendas": limpar_legendas(c), "arquivo": f"{nome}.mp4", "thumbnail": f"{nome}.jpg", "lote": prefixo, "template": cfg["template"]["nome"],
             "duracao": round((c["fim"] - c["inicio"]) / cfg["template"]["velocidade"], 1),
             "criado_em": dt.datetime.now().isoformat(timespec="seconds"),
             # fonte + palavras permitem reaplicar outro template depois sem transcrever de novo
             "fonte": str(Path(video).resolve()),
             "palavras": palavras_do_corte(palavras, c["inicio"], c["fim"])}
        gravar_json(saida / f"{nome}.json", c)
        feitos.append(publico(c))
    if cortes:
        marcar("renderizar", "fim", prefixo, n=len(cortes), msg=f"{len(cortes)} cortes renderizados")
    # depois de renderizar: o cartão do item termina em Ranking, e Ranking só fica verde com os cortes prontos
    marcar("ranking", "fim", prefixo, n=len(cortes), msg=f"{len(cortes)} cortes aprovados pela regra")
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
                marcar("entrada", "progresso", n=feitos, msg=f"Lote {lote.stem} processado")
                # índice lido do disco, não da memória: preserva templates reaplicados durante a live
                atualizar_indices(pasta, stream)
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
    p.add_argument("--template", default="", help="nome de templates/<nome>.json (padrão: legenda clássica)")
    p.add_argument("--reaplicar", action="store_true",
                   help="entrada = um ou mais .json de cortes prontos; renderiza de novo com --template")
    p.add_argument("--saida", type=Path, default=Path("cortes"))
    a, extras = p.parse_known_args()
    try:
        tpl = carregar_template(a.template)
    except ValueError as e:
        sys.exit(str(e))
    if a.reaplicar:
        if desconhecidos := [x for x in extras if x.startswith("-")]:
            p.error(f"argumentos não reconhecidos: {' '.join(desconhecidos)}")
        return reaplicar([a.entrada, *extras], tpl)
    if extras:
        p.error(f"argumentos não reconhecidos: {' '.join(extras)}")
    if not agentes_disponiveis():
        sys.exit("Nenhum agente de IA encontrado. Instale e faça login no Claude Code (claude), no Codex (codex login) ou no Gemini CLI (gemini).")
    a.saida.mkdir(parents=True, exist_ok=True)
    cfg = {"estrategia": carregar_estrategia(a.estrategia), "nota_min": a.nota_min, "limite": a.limite_por_lote,
           "dur_min": a.dur_min, "dur_max": a.dur_max, "dias": a.dias, "horas": a.horas, "webhook": a.webhook,
           "template": tpl}
    marcar("entrada", "fim", msg=f"Entrada: {a.entrada}")
    try:
        if a.monitorar:
            monitorar(a.entrada, a.saida, cfg)
        else:
            fonte = Path(a.entrada) if Path(a.entrada).exists() else baixar(a.entrada, a.saida)
            processar(fonte, a.saida, fonte.stem, cfg)
            # do disco, não da memória: uma reaplicação feita enquanto os outros cortes renderizavam vale
            gravar_json(a.saida / f"{fonte.stem}_cortes.json", cortes_da_pasta(a.saida, fonte.stem))
    except Exception as e:
        marcar_erro(e)
        raise


if __name__ == "__main__":
    main()
