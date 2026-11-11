import json

import publicar
import worker_social


def test_aprovacao_enfileira_e_worker_nao_reenvia(tmp_path):
    corte = tmp_path / "corte.json"
    corte.write_text(json.dumps({"arquivo": "corte.mp4"}), encoding="utf-8")
    corte.with_suffix(".mp4").touch()
    assert publicar.aprovar(corte, "Legenda", ["gta"], tmp_path, navegador=True) == ["youtube"]
    chamadas = []

    def postar(plataforma, video, texto, confirmar):
        chamadas.append((plataforma, video.name, texto))
        confirmar()
        if plataforma == "tiktok":
            raise RuntimeError("confirmação indisponível")

    worker_social.processar(tmp_path, postar)
    worker_social.processar(tmp_path, postar)
    assert chamadas == [
        ("instagram", "corte.mp4", "Legenda\n\n#gta"),
        ("tiktok", "corte.mp4", "Legenda\n\n#gta"),
    ]
    plataformas = publicar.ler_publicacao(corte, set())["plataformas"]
    assert plataformas["instagram"]["estado"] == "ok"
    assert plataformas["tiktok"]["estado"] == "incerto"
