import numpy as np
import pytest

import enquadramento
import recut


def test_painel_reconhece_entrada_e_saida_da_tela(monkeypatch):
    frames = np.zeros((8, 270, 480, 3), dtype=np.uint8)
    frames[2:6, 42, 94:385] = (180, 50, 155)
    frames[2:6, 233, 94:385] = (180, 50, 155)
    frames[6:, 42, 94:385] = (180, 50, 155)  # Uma faixa só não identifica o painel.
    monkeypatch.setattr(enquadramento, "ffmpeg", lambda *args: frames.tobytes())
    assert enquadramento.intervalos_painel("video.mp4", "ffmpeg", 10, 4) == [[1, 3]]


@pytest.mark.parametrize("template", ["classico", "podcast"])
def test_enquadramento_automatico_mantem_legendas_do_template(template):
    tpl = recut.carregar_template(template)
    plano = {"versao": 1, "tela": [[0, 10]], "falantes": [[0, 2, 0], [3, 10, 2]]}
    grafo = recut.filtro_video(tpl, 1920, 1080, "amostra", foco=plano)
    assert "auto_fundo" in grafo and "auto_foco2" in grafo
    assert grafo.index("[auto_fundo][auto_foco3_out]overlay") < grafo.index("subtitles=amostra.ass")
