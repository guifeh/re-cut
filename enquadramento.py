"""Enquadramento automático de transmissões com painel compartilhado e quatro câmeras."""
import json
import subprocess
import sys
from pathlib import Path

ASSETS = Path(__file__).resolve().parent / ".venv" / "asd"
PANELS = [(0, 92, 184, 278), (0, 279, 184, 461),
          (777, 92, 960, 278), (777, 279, 960, 461)]
TELA = (185, 92, 776, 462)
REVISAO = "6d6821479af485e251c4991487e40573b42181b4"
PESOS_SHA256 = "d985ddd07dca08864a28337726f5b7d91b6426bebc7327f0e9b21cf9ff1cc937"


def load(assets):
    import cv2
    import torch
    from loss import lossAV
    from model.talkNetModel import talkNetModel
    torch.set_num_threads(4)
    cv2.setNumThreads(2)
    net, head = talkNetModel().eval(), lossAV().eval()
    weights = torch.load(assets / "TalkSet.model", map_location="cpu", weights_only=True)
    weights = {k.removeprefix("module."): v for k, v in weights.items()}
    net.load_state_dict({k.removeprefix("model."): v for k, v in weights.items() if k.startswith("model.")})
    head.load_state_dict({k.removeprefix("lossAV."): v for k, v in weights.items() if k.startswith("lossAV.")})
    return net, head


def ffmpeg(source, executable, start, seconds, args):
    return subprocess.check_output([executable, "-v", "error", "-ss", str(start), "-i", str(source),
                                    "-t", str(seconds), *args, "-"])


def prepare(source, executable, start, seconds, panels):
    import cv2
    import numpy as np

    frames = np.frombuffer(ffmpeg(source, executable, start, seconds, ["-an", "-vf", "fps=25,scale=960:540",
                                                    "-pix_fmt", "gray", "-f", "rawvideo"]), np.uint8)
    frames = frames.reshape(-1, 540, 960)
    audio = np.frombuffer(ffmpeg(source, executable, start, seconds, ["-vn", "-ac", "1", "-ar", "16000", "-f", "s16le"]), "<i2")
    detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    crops, diagnostics = [], []
    for x0, y0, x1, y1 in panels:
        hits, locations = [], []
        for i, frame in enumerate(frames[::4]):
            boxes = detector.detectMultiScale(frame[y0:y1, x0:x1], scaleFactor=1.1, minNeighbors=4, minSize=(25, 25))
            if len(boxes):
                x, y, w, h = max(boxes, key=lambda b: b[2] * b[3])
                locations.append(i * 4)
                hits.append((x0 + x + w / 2, y0 + y + h / 2, max(w, h) / 2))
        if len(hits) < 4:
            crops.append(np.zeros((len(frames), 112, 112), dtype=np.uint8))
            diagnostics.append(False)
            continue
        sample = np.arange(len(frames))
        track = np.stack([np.interp(sample, locations, v) for v in np.asarray(hits).T], axis=1)
        face_frames = []
        for frame, (x, y, r) in zip(frames, track):
            # Crop do demo oficial: contexto assimétrico, resize 224 e miolo 112.
            crop = frame[max(0, int(y-r)):min(540, int(y+1.8*r)), max(0, int(x-1.4*r)):min(960, int(x+1.4*r))]
            face_frames.append(cv2.resize(crop, (224, 224))[56:168, 56:168])
        diagnostics.append(True)
        crops.append(np.stack(face_frames))
    return audio, np.stack(crops), diagnostics


def score(net, head, audio, crops):
    import numpy as np
    import torch
    from python_speech_features import mfcc

    features = mfcc(audio, 16000, numcep=13, winlen=0.025, winstep=0.010)
    length = min(len(features) // 4, crops.shape[1])
    scores = []
    for window in (75, 150):
        result = []
        for start in range(0, length, window):
            end = min(start + window, length)
            a = torch.from_numpy(features[start*4:end*4]).float().unsqueeze(0).repeat(len(crops), 1, 1)
            v = torch.from_numpy(crops[:, start:end]).float().contiguous()
            a = net.forward_audio_frontend(a)
            v = net.forward_visual_frontend(v)
            a, v = net.forward_cross_attention(a, v)
            output = net.forward_audio_visual_backend(a, v)
            result.append(head(output).reshape(len(crops), -1))
        scores.append(np.concatenate(result, axis=1))
    return np.mean(scores, axis=0)


def intervalos_painel(source, executable, start, duration):
    """Reconhece as duas faixas que delimitam o painel do layout validado."""
    import numpy as np

    raw = ffmpeg(source, executable, start, duration, ["-an", "-vf", "fps=2,scale=480:270",
                                                        "-pix_fmt", "bgr24", "-f", "rawvideo"])
    frames = np.frombuffer(raw, np.uint8).reshape(-1, 270, 480, 3)
    spans = []
    for i, frame in enumerate(frames):
        bands = frame[:, 94:385].astype(np.int16)
        b, g, r = np.moveaxis(bands, 2, 0)
        purple = ((b > g + 35) & (r > g + 25) & (r > 70)).mean(axis=1)
        if purple[39:47].max() < 0.75 or purple[229:239].max() < 0.75:
            continue
        a, b = i / 2, min((i + 1) / 2, duration)
        if spans and spans[-1][1] == a:
            spans[-1][1] = b
        else:
            spans.append([a, b])
    return [span for span in spans if span[1] - span[0] >= 1]


def analisar_painel(source, executable, start, duration, assets):
    import numpy as np

    spans = intervalos_painel(source, executable, start, duration)
    if not spans:
        return None
    import torch

    sys.path.insert(0, str(assets))
    model, head = load(assets)
    choices = []
    blocos = [(a + offset, min(a + offset + 12, b))
              for a, b in spans for offset in range(0, int(b - a + 0.999), 12)]
    for a, b in blocos:
        audio, faces, found = prepare(source, executable, start + a, b - a, PANELS)
        if sum(found) < 2 or len(audio) < 16000:
            continue
        with torch.inference_mode():
            scores = score(model, head, audio, faces)
        scores[~np.asarray(found, dtype=bool)] = -np.inf
        for i in range(0, scores.shape[1], 25):
            values = scores[:, i:i + 25].mean(axis=1)
            best, second = np.argsort(values)[-2:][::-1]
            if values[best] >= 0 and values[best] - values[second] >= 0.5:
                begin, end = a + i / 25, min(a + (i + 25) / 25, b)
                if choices and choices[-1][2] == best and abs(choices[-1][1] - begin) < 0.001:
                    choices[-1][1] = end
                else:
                    choices.append([begin, end, int(best)])
    return {"versao": 1, "tela": spans, "falantes": choices}


def analisar(video, inicio, fim, ffmpeg_path, assets=ASSETS):
    """Executa a análise em um Python separado do ambiente de transcrição."""
    python = assets / "venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not Path(video).is_file() or not python.is_file() or not (assets / "TalkSet.model").is_file():
        return None
    try:
        result = subprocess.run(
            [str(python), str(Path(__file__).resolve()), str(Path(video).resolve()), str(inicio),
             str(fim - inicio), str(ffmpeg_path), str(assets)],
            capture_output=True, text=True, encoding="utf-8", check=True, timeout=600)
        return json.loads(result.stdout)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"  enquadramento automático indisponível ({type(error).__name__})", file=sys.stderr)
        return None


def compor(fundo, plano, iw, ih, W, H):
    """Insere o painel na composição antes das legendas e demais efeitos do template."""
    def crop(box):
        x0, y0, x1, y1 = box
        x, y = int(x0 * iw / 960) // 2 * 2, int(y0 * ih / 540) // 2 * 2
        w = int((x1 - x0) * iw / 960) // 2 * 2
        h = int((y1 - y0) * ih / 540) // 2 * 2
        return f"crop={w}:{h}:{x}:{y}"

    def quando(spans):
        return "+".join(f"gte(t,{a:.3f})*lt(t,{b:.3f})" for a, b in spans) or "0"

    altura_tela = int(H * 0.66) // 2 * 2
    altura_cam = int(H * 0.21) // 2 * 2
    largura_cam = int(W * 0.46) // 2 * 2
    grafo = [f"{fundo}[auto_fundo]",
             f"[0:v]{crop(TELA)},scale={W}:{altura_tela}:force_original_aspect_ratio=decrease:"
             f"force_divisible_by=2,pad={W}:{H}:(ow-iw)/2:({altura_tela}-ih)/2,setsar=1[auto_tela]"]
    anterior = "auto_tela"
    aberto = f"not({quando([(a, b) for a, b, _ in plano['falantes']])})"
    for i, box in enumerate(PANELS):
        spans = [(a, b) for a, b, cam in plano["falantes"] if cam == i]
        mini = (W // 4) // 2 * 2
        for tipo, largura, posicao, enable in [
            ("mini", mini, i * mini, aberto), ("foco", largura_cam, (W - largura_cam) // 2, quando(spans)),
        ]:
            label = f"auto_{tipo}{i}"
            grafo.append(f"[0:v]{crop(box)},scale={largura}:{altura_cam}:force_original_aspect_ratio=decrease:"
                         f"force_divisible_by=2,setsar=1[{label}]")
            grafo.append(f"[{anterior}][{label}]overlay={posicao}:{H-altura_cam}:enable='{enable}'[{label}_out]")
            anterior = f"{label}_out"
    grafo.append(f"[auto_fundo][{anterior}]overlay=0:0:enable='{quando(plano['tela'])}'")
    return ";".join(grafo)


def preparar_ambiente():
    """Instala o modelo e seu ambiente isolado para uso pelo renderizador."""
    import hashlib
    import io
    import zipfile

    ASSETS.mkdir(parents=True, exist_ok=True)
    venv = ASSETS / "venv"
    python = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not python.is_file():
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    subprocess.run([str(python), "-m", "pip", "install", "torch==2.15.0",
                    "--index-url", "https://download.pytorch.org/whl/cpu"], check=True)
    subprocess.run([str(python), "-m", "pip", "install", "opencv-python-headless<5", "python_speech_features",
                    "scipy"], check=True)
    repo = f"https://codeload.github.com/TaoRuijie/TalkNet-ASD/zip/{REVISAO}"
    curl = ["curl", "--fail", "--location", "--silent", "--show-error", "--max-time", "90"]
    with zipfile.ZipFile(io.BytesIO(subprocess.check_output([*curl, repo]))) as archive:
        for name in ("loss.py", "LICENSE.md", "model/attentionLayer.py", "model/audioEncoder.py",
                     "model/talkNetModel.py", "model/visualEncoder.py"):
            dest = ASSETS / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(archive.read(f"TalkNet-ASD-{REVISAO}/{name}"))
    url = "https://drive.usercontent.google.com/download?id=1AbN9fCf9IexMxEKXLQY2KYBlb-IhSEea&export=download&confirm=t"
    data = subprocess.check_output([*curl, url])
    if hashlib.sha256(data).hexdigest() != PESOS_SHA256:
        raise ValueError("os pesos do TalkNet não correspondem à versão validada")
    temporario = ASSETS / "TalkSet.model.download"
    temporario.write_bytes(data)
    temporario.replace(ASSETS / "TalkSet.model")


if __name__ == "__main__":
    if sys.argv[1:] == ["--preparar"]:
        preparar_ambiente()
    else:
        video, inicio, duracao, executavel, pasta = sys.argv[1:]
        print(json.dumps(analisar_painel(video, executavel, float(inicio), float(duracao), Path(pasta))))
