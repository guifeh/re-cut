import json
from pathlib import Path
import datetime as dt

import pytest

import contas
from publicar import aprovar, colar_link, data_publicacao, enviar, ler_publicacao, preparar_envio, tentar_de_novo, texto_final

TOKEN = "TOKEN-SECRETO"


class Falso:
    """http falso: registra cada chamada e devolve as respostas prontas em ordem; (status, obj, cabeçalhos)."""
    def __init__(self, *respostas):
        self.respostas, self.chamadas = list(respostas), []

    def __call__(self, metodo, url, dados=None, cabecalhos=None, corpo=None, timeout=60):
        self.chamadas.append({"metodo": metodo, "url": url, "dados": dados, "cab": cabecalhos or {}, "corpo": corpo})
        status, obj, *cab = self.respostas.pop(0)
        return status, (cab[0] if cab else {}), json.dumps(obj).encode()


@pytest.fixture
def corte(tmp_path):
    job = tmp_path / "jobs" / "j1"
    job.mkdir(parents=True)
    (job / "fonte_corte01.mp4").write_bytes(b"v" * 1234)
    arq = job / "fonte_corte01.json"
    arq.write_text(json.dumps({"arquivo": "fonte_corte01.mp4", "titulo": "t", "legendas": ["a", "b", "c"]}))
    return arq


@pytest.fixture
def pasta(tmp_path):
    p = tmp_path / "contas"
    contas.salvar("youtube", {"access_token": TOKEN, "vence_em": "2999-01-01T00:00:00"}, p)
    contas.salvar("instagram", {"access_token": TOKEN, "vence_em": "2999-01-01T00:00:00", "user_id": "42"}, p)
    return p


def sem_contas(corte_json):
    """Pasta de contas vazia (no tmp): o default contas.PASTA leria a conta real do Telegram."""
    return corte_json.parent / "sem_contas"


def estados(corte_json):
    return {p: e["estado"] for p, e in ler_publicacao(corte_json, {(str(corte_json.resolve()), p) for p in
                                                                    ("youtube", "instagram")})["plataformas"].items()}


def youtube_ok(id_video="abc"):
    return [(200, {}, {"Location": "https://upload.example/sessao"}), (200, {"id": id_video})]


def test_aprovar_duas_vezes_nao_duplica(corte):
    assert aprovar(corte, "minha legenda", ["#a"], pasta_contas=sem_contas(corte)) == ["youtube", "instagram"]
    with pytest.raises(ValueError, match="já foi aprovado"):
        aprovar(corte, "outra", [], pasta_contas=sem_contas(corte))
    pub = json.loads(corte.with_suffix(".publicacao").read_text(encoding="utf-8"))
    assert pub["legenda"] == "minha legenda" and pub["aprovado_em"]
    assert estados(corte) == {"youtube": "enviando", "instagram": "enviando", "tiktok": "manual"}


def test_ler_sem_arquivo_e_vazio(corte):
    assert ler_publicacao(corte, set()) == {}


def test_enviar_destino_individual_preserva_telegram(corte, pasta):
    contas.salvar("telegram", {"token": "123:ABC", "chat_id": 42, "bot": "teste_bot"}, pasta)
    preparar_envio(corte, "telegram", pasta_contas=pasta)
    pub = json.loads(corte.with_suffix(".publicacao").read_text())
    assert set(pub["plataformas"]) == {"tiktok"}
    assert pub["plataformas"]["tiktok"]["estado"] == "manual"
    telegram_original = pub["telegram"]
    preparar_envio(corte, "youtube", pasta_contas=pasta)
    pub = json.loads(corte.with_suffix(".publicacao").read_text())
    assert pub["telegram"] == telegram_original
    assert set(pub["plataformas"]) == {"youtube", "tiktok"}
    colar_link(corte, "tiktok", "https://www.tiktok.com/@teste/video/123")


def test_agendar_youtube_usa_privado_com_data(corte, pasta):
    data = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).isoformat()
    preparar_envio(corte, "youtube", publish_at=data, pasta_contas=pasta)
    http = Falso(*youtube_ok())
    assert enviar(corte, "youtube", http, pasta_contas=pasta)["estado"] == "ok"
    dados = http.chamadas[0]["dados"]
    assert dados["status"] == {"privacyStatus": "private", "publishAt": data, "selfDeclaredMadeForKids": False}
    assert dados["snippet"]["title"] == "t"
    assert ler_publicacao(corte, set())["plataformas"]["youtube"]["publish_at"] == data


@pytest.mark.parametrize("data", ["2000-01-01T12:00:00Z", "2999-01-01T12:00:00", "invalida", "", 123])
def test_agendamento_invalido_nao_altera_estado(corte, pasta, data):
    with pytest.raises(ValueError, match="data futura"):
        preparar_envio(corte, "youtube", publish_at=data, pasta_contas=pasta)
    assert not corte.with_suffix(".publicacao").exists()


def test_data_publicacao_converte_fuso():
    assert data_publicacao("2999-01-01T10:30:00-03:00") == "2999-01-01T13:30:00+00:00"


def test_agendamento_vencido_antes_do_upload_nao_publica(corte, pasta):
    preparar_envio(corte, "youtube", publish_at="2999-01-01T10:30:00Z", pasta_contas=pasta)
    pub = json.loads(corte.with_suffix(".publicacao").read_text())
    pub["plataformas"]["youtube"]["publish_at"] = "2000-01-01T10:30:00Z"
    corte.with_suffix(".publicacao").write_text(json.dumps(pub))
    http = Falso()
    resultado = enviar(corte, "youtube", http, pasta_contas=pasta)
    assert resultado["estado"] == "erro"
    assert http.chamadas == []


def test_reenvio_exige_confirmacao_e_guarda_link(corte, pasta):
    preparar_envio(corte, "youtube", pasta_contas=pasta)
    with pytest.raises(ValueError, match="já está sendo enviado"):
        preparar_envio(corte, "youtube", forcar=True, pasta_contas=pasta)
    enviar(corte, "youtube", Falso(*youtube_ok("original")), pasta_contas=pasta)
    with pytest.raises(ValueError, match="confirme"):
        preparar_envio(corte, "youtube", pasta_contas=pasta)
    preparar_envio(corte, "youtube", forcar=True, pasta_contas=pasta)
    pub = json.loads(corte.with_suffix(".publicacao").read_text())
    assert pub["plataformas"]["youtube"]["historico"][0]["link"].endswith("/original")
    assert pub["plataformas"]["youtube"]["link"] is None


def test_reenvio_telegram_erro_parcial_preserva_video(corte, pasta):
    contas.salvar("telegram", {"token": "123:ABC", "chat_id": 42, "bot": "teste_bot"}, pasta)
    preparar_envio(corte, "telegram", pasta_contas=pasta)
    pub = json.loads(corte.with_suffix(".publicacao").read_text())
    pub["telegram"].update(estado="erro", mensagens=[123])
    corte.with_suffix(".publicacao").write_text(json.dumps(pub))
    preparar_envio(corte, "telegram", pasta_contas=pasta)
    assert json.loads(corte.with_suffix(".publicacao").read_text())["telegram"]["mensagens"] == [123]


def test_destino_desconectado_nao_grava_envio(corte):
    with pytest.raises(ValueError, match="conecte o Telegram"):
        preparar_envio(corte, "telegram", pasta_contas=sem_contas(corte))
    assert not corte.with_suffix(".publicacao").exists()


def test_aprovacao_depois_de_envio_individual_preserva_destinos(corte, pasta):
    contas.salvar("telegram", {"token": "123:ABC", "chat_id": 42, "bot": "teste_bot"}, pasta)
    preparar_envio(corte, "telegram", pasta_contas=pasta)
    preparar_envio(corte, "youtube", publish_at="2999-01-01T10:30:00Z", pasta_contas=pasta)
    antes = json.loads(corte.with_suffix(".publicacao").read_text())
    assert not antes.get("aprovado_em")
    assert aprovar(corte, "nova legenda", ["nova"], pasta_contas=pasta) == ["instagram"]
    depois = json.loads(corte.with_suffix(".publicacao").read_text())
    assert depois["telegram"] == antes["telegram"]
    assert depois["plataformas"]["youtube"] == antes["plataformas"]["youtube"]
    assert depois["aprovado_em"]


def test_enviando_sem_thread_vira_incerto(corte):
    aprovar(corte, "x", [], pasta_contas=sem_contas(corte))
    ativos = {(str(corte.resolve()), "youtube"), (str(corte.resolve()), "instagram")}
    assert ler_publicacao(corte, ativos)["plataformas"]["youtube"]["estado"] == "enviando"
    assert ler_publicacao(corte, set())["plataformas"]["youtube"]["estado"] == "incerto"
    assert ler_publicacao(corte, ativos)["plataformas"]["youtube"]["estado"] == "incerto"  # regravado


def test_incerto_so_reenvia_forcando(corte):
    aprovar(corte, "x", [], pasta_contas=sem_contas(corte))
    ler_publicacao(corte, set())
    with pytest.raises(ValueError):
        tentar_de_novo(corte, "youtube", forcar=False, pasta_contas=sem_contas(corte))
    tentar_de_novo(corte, "youtube", forcar=True, pasta_contas=sem_contas(corte))
    assert ler_publicacao(corte, {(str(corte.resolve()), "youtube")})["plataformas"]["youtube"]["estado"] == "enviando"


def test_ok_nunca_reenvia(corte, pasta):
    aprovar(corte, "x", [], pasta_contas=sem_contas(corte))
    enviar(corte, "youtube", http=Falso(*youtube_ok()), pasta_contas=pasta)
    for forcar in (False, True):
        with pytest.raises(ValueError, match="já foi postado"):
            tentar_de_novo(corte, "youtube", forcar=forcar, pasta_contas=sem_contas(corte))
    with pytest.raises(ValueError):  # e enviar de novo direto também não
        enviar(corte, "youtube", http=Falso(*youtube_ok()), pasta_contas=pasta)


def test_erro_volta_para_enviando(corte, pasta):
    aprovar(corte, "x", [], pasta_contas=sem_contas(corte))
    enviar(corte, "youtube", http=Falso((500, {"error": "x"})), pasta_contas=pasta)
    assert estados(corte)["youtube"] == "erro"
    tentar_de_novo(corte, "youtube", forcar=False, pasta_contas=sem_contas(corte))
    assert estados(corte)["youtube"] == "enviando"


def test_youtube_envia_publico_e_devolve_link_do_short(corte, pasta):
    aprovar(corte, "L" * 150, ["shorts"], pasta_contas=sem_contas(corte))
    http = Falso(*youtube_ok("vid9"))
    r = enviar(corte, "youtube", http=http, pasta_contas=pasta)
    assert r["estado"] == "ok" and r["link"] == "https://youtube.com/shorts/vid9"
    inicio, envio = http.chamadas
    assert inicio["url"].startswith("https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable")
    assert inicio["dados"]["snippet"]["title"] == "L" * 100
    assert inicio["dados"]["snippet"]["description"] == "L" * 150 + "\n\n#shorts"
    assert inicio["dados"]["status"] == {"privacyStatus": "public", "selfDeclaredMadeForKids": False}
    assert inicio["cab"]["Authorization"] == f"Bearer {TOKEN}"
    assert envio["metodo"] == "PUT" and envio["url"] == "https://upload.example/sessao"
    assert envio["cab"]["Content-Length"] == "1234" and hasattr(envio["corpo"], "read")  # em blocos, não na memória
    assert estados(corte)["youtube"] == "ok"


def test_queda_no_envio_do_video_fica_incerto(corte, pasta):
    aprovar(corte, "x", [], pasta_contas=sem_contas(corte))

    def cai(metodo, url, **kw):
        if metodo == "PUT":
            raise OSError("conexão caiu")
        return 200, {"Location": "https://upload.example/sessao"}, b"{}"
    r = enviar(corte, "youtube", http=cai, pasta_contas=pasta)
    assert r["estado"] == "incerto"  # pode ter saído: só reenvia forçando


def instagram(*status, publicar=(200, {"id": "m1"})):
    return [(200, {"id": "c1"}), (200, {"success": True}),
            *[(200, {"status_code": s}) for s in status], publicar,
            (200, {"permalink": "https://www.instagram.com/reel/XYZ/"})]


def test_instagram_espera_container_e_pega_permalink(corte, pasta):
    aprovar(corte, "legenda", ["a"], pasta_contas=sem_contas(corte))
    esperas = []
    http = Falso(*instagram("IN_PROGRESS", "IN_PROGRESS", "FINISHED"))
    r = enviar(corte, "instagram", http=http, esperar=esperas.append, pasta_contas=pasta)
    assert r["estado"] == "ok" and r["link"] == "https://www.instagram.com/reel/XYZ/" and r["container"] == "c1"
    assert esperas == [30, 30]
    criar, upload, *_, publicar, link = http.chamadas
    assert criar["url"] == "https://graph.instagram.com/v26.0/42/media"
    assert criar["dados"]["media_type"] == "REELS" and criar["dados"]["upload_type"] == "resumable"
    assert criar["dados"]["caption"] == "legenda\n\n#a"
    assert upload["url"] == "https://rupload.facebook.com/ig-api-upload/v26.0/c1"
    assert upload["cab"]["Authorization"] == f"OAuth {TOKEN}" and upload["cab"]["offset"] == "0"
    assert upload["cab"]["file_size"] == "1234" and hasattr(upload["corpo"], "read")
    assert publicar["url"] == "https://graph.instagram.com/v26.0/42/media_publish"
    assert publicar["dados"]["creation_id"] == "c1"
    assert link["url"].startswith("https://graph.instagram.com/v26.0/m1?fields=permalink")


def test_instagram_container_com_erro_marca_erro(corte, pasta):
    aprovar(corte, "x", [], pasta_contas=sem_contas(corte))
    http = Falso(*instagram("IN_PROGRESS", "ERROR")[:4])
    r = enviar(corte, "instagram", http=http, esperar=lambda s: None, pasta_contas=pasta)
    assert r["estado"] == "erro" and "ERROR" in r["erro"] and r["container"] == "c1"
    assert not any("media_publish" in c["url"] for c in http.chamadas)


def test_instagram_reenvio_nao_republica_container_ja_publicado(corte, pasta):
    aprovar(corte, "x", [], pasta_contas=sem_contas(corte))
    enviar(corte, "instagram", http=Falso(*instagram("ERROR")[:3]), esperar=lambda s: None, pasta_contas=pasta)
    tentar_de_novo(corte, "instagram", forcar=False, pasta_contas=sem_contas(corte))
    http = Falso((200, {"status_code": "PUBLISHED"}))
    r = enviar(corte, "instagram", http=http, esperar=lambda s: None, pasta_contas=pasta)
    assert r["estado"] == "erro" and "cole o link" in r["erro"] and len(http.chamadas) == 1


def test_conta_ausente_erra_so_ela(corte, pasta):
    (pasta / "instagram.json").unlink()
    aprovar(corte, "x", [], pasta_contas=sem_contas(corte))
    r = enviar(corte, "instagram", http=Falso(), pasta_contas=pasta)
    assert r["estado"] == "erro" and "aba Contas" in r["erro"]
    assert enviar(corte, "youtube", http=Falso(*youtube_ok()), pasta_contas=pasta)["estado"] == "ok"
    assert estados(corte) == {"youtube": "ok", "instagram": "erro", "tiktok": "manual"}


def test_erro_da_plataforma_nao_vaza_token(corte, pasta):
    aprovar(corte, "x", [], pasta_contas=sem_contas(corte))
    r = enviar(corte, "youtube", http=Falso((400, {"msg": f"token {TOKEN} inválido"})), pasta_contas=pasta)
    assert r["estado"] == "erro" and TOKEN not in r["erro"]
    assert TOKEN not in corte.with_suffix(".publicacao").read_text(encoding="utf-8")


def test_texto_final_limita_hashtags():
    assert texto_final("oi", ["#a", "b"]) == "oi\n\n#a #b"
    assert texto_final("oi", [f"t{i}" for i in range(40)]).count("#") == 30
    assert texto_final("oi", []) == "oi"
    assert len(texto_final("x" * 3000, ["a"])) == 2200 and texto_final("x" * 3000, ["a"]).endswith("\n\n#a")


def test_colar_link_valida_dominio(corte):
    aprovar(corte, "x", [], pasta_contas=sem_contas(corte))
    for ruim in ("https://evil.com/x", "http://www.tiktok.com/@x/video/1", "https://tiktok.com.evil.com/x"):
        with pytest.raises(ValueError):
            colar_link(corte, "tiktok", ruim)
    with pytest.raises(ValueError):  # youtube está enviando: não aceita link agora
        colar_link(corte, "youtube", "https://youtu.be/abc")
    colar_link(corte, "tiktok", "https://www.tiktok.com/@x/video/1")
    t = ler_publicacao(corte, set())["plataformas"]["tiktok"]
    assert t["estado"] == "ok" and t["link"] == "https://www.tiktok.com/@x/video/1"
    colar_link(corte, "youtube", "https://youtu.be/abc")  # incerto agora: aceita


def test_5xx_no_put_do_youtube_fica_incerto(corte, pasta):
    aprovar(corte, "x", [], pasta_contas=sem_contas(corte))
    r = enviar(corte, "youtube", http=Falso(youtube_ok()[0], (503, {"error": "x"})), pasta_contas=pasta)
    assert r["estado"] == "incerto"
    with pytest.raises(ValueError):
        tentar_de_novo(corte, "youtube", forcar=False, pasta_contas=sem_contas(corte))


def test_4xx_no_put_do_youtube_e_erro(corte, pasta):
    aprovar(corte, "x", [], pasta_contas=sem_contas(corte))
    assert enviar(corte, "youtube", http=Falso(youtube_ok()[0], (400, {})), pasta_contas=pasta)["estado"] == "erro"


def test_publicacao_some_no_meio_do_envio_nao_levanta(corte, pasta):
    aprovar(corte, "x", [], pasta_contas=sem_contas(corte))

    def lixeira_no_meio(metodo, url, **kw):
        corte.with_suffix(".publicacao").unlink(missing_ok=True)
        raise OSError("caiu")
    r = enviar(corte, "youtube", http=lixeira_no_meio, pasta_contas=pasta)
    assert r["estado"] == "erro" and not corte.with_suffix(".publicacao").exists()  # não recria o arquivo


@pytest.mark.parametrize("publicar", [OSError("caiu"), (200, {})])
def test_media_publish_sem_resposta_fica_incerto(corte, pasta, publicar):
    aprovar(corte, "x", [], pasta_contas=sem_contas(corte))
    falso = Falso(*instagram("FINISHED")[:3], (200, {}))

    def http(metodo, url, **kw):
        if "media_publish" in url:
            if isinstance(publicar, Exception):
                raise publicar
            falso.respostas.insert(0, publicar)
        return falso(metodo, url, **kw)
    r = enviar(corte, "instagram", http=http, esperar=lambda s: None, pasta_contas=pasta)
    assert r["estado"] == "incerto"


def test_permalink_falhando_depois_do_publish_fica_ok_sem_link(corte, pasta):
    aprovar(corte, "x", [], pasta_contas=sem_contas(corte))
    http = Falso(*instagram("FINISHED")[:-1], (500, {}))
    r = enviar(corte, "instagram", http=http, esperar=lambda s: None, pasta_contas=pasta)
    assert r["estado"] == "ok" and r["link"] is None


def test_ok_sem_link_aceita_colar_link_uma_vez(corte, pasta):
    aprovar(corte, "x", [], pasta_contas=sem_contas(corte))
    enviar(corte, "instagram", http=Falso(*instagram("FINISHED")[:-1], (500, {})), esperar=lambda s: None, pasta_contas=pasta)
    colar_link(corte, "instagram", "https://www.instagram.com/reel/abc/")
    assert ler_publicacao(corte, set())["plataformas"]["instagram"]["link"] == "https://www.instagram.com/reel/abc/"
    with pytest.raises(ValueError, match="não espera link"):  # ok com link: não troca
        colar_link(corte, "instagram", "https://www.instagram.com/reel/outro/")


def test_youtube_tira_sinais_de_menor_e_maior(corte, pasta):
    aprovar(corte, "<3 o melhor > tudo", ["a"], pasta_contas=sem_contas(corte))
    http = Falso(*youtube_ok())
    enviar(corte, "youtube", http=http, pasta_contas=pasta)
    snippet = http.chamadas[0]["dados"]["snippet"]
    assert snippet["title"] == "3 o melhor  tudo" and "<" not in snippet["description"] and ">" not in snippet["description"]


def test_plataforma_sem_estado_conta_como_ausente(corte):
    corte.with_suffix(".publicacao").write_text(json.dumps(
        {"aprovado_em": "2026-11-04T10:00:00", "plataformas": {"youtube": {"link": None}, "tiktok": {"estado": "manual"}}}))
    assert list(ler_publicacao(corte, set())["plataformas"]) == ["tiktok"]
    with pytest.raises(ValueError):
        tentar_de_novo(corte, "youtube", False, pasta_contas=sem_contas(corte))


# --- Telegram ---

def tg(result=None, status=200, **extra):
    """Resposta da Bot API no formato do Falso."""
    return (status, {"ok": True, "result": result} if status < 300 else {"ok": False, **extra})


@pytest.fixture
def pareado(pasta):
    contas.salvar("telegram", {"token": TOKEN, "bot": "meu_bot", "chat_id": 7, "nome": "Gui"}, pasta)
    return pasta


def tg_estado(corte_json):
    return ler_publicacao(corte_json, {(str(corte_json.resolve()), "telegram")})["telegram"]


def test_aprovar_com_telegram_pareado(corte, pareado):
    assert aprovar(corte, "x", [], pasta_contas=pareado) == ["youtube", "instagram", "telegram"]
    t = tg_estado(corte)
    assert t["estado"] == "enviando" and t["bot"] == "meu_bot" and t["chat_id"] == 7 and t["mensagens"] == []


def test_aprovar_sem_telegram_igual_a_hoje(corte, pasta):
    assert aprovar(corte, "x", [], pasta_contas=pasta) == ["youtube", "instagram"]
    assert "telegram" not in ler_publicacao(corte, set())


def test_telegram_envia_video_e_texto(corte, pareado):
    aprovar(corte, "a < b & c", ["x"], pasta_contas=pareado)
    http = Falso(tg({"message_id": 10}), tg({"message_id": 11}))
    r = enviar(corte, "telegram", http=http, pasta_contas=pareado)
    assert r["estado"] == "ok" and r["mensagens"] == [10, 11]
    video, texto = http.chamadas
    assert video["url"].endswith("/sendVideo") and b'name="caption"\r\n\r\nt\r\n' in video["corpo"]
    assert texto["url"].endswith("/sendMessage") and texto["dados"]["parse_mode"] == "HTML"
    assert texto["dados"]["chat_id"] == 7
    assert texto["dados"]["text"] == "<pre>a &lt; b &amp; c\n\n#x</pre>"
    assert tg_estado(corte)["mensagens"] == [10, 11]


def test_telegram_legenda_do_video_com_nota(corte, pareado):
    corte.write_text(json.dumps({"arquivo": "fonte_corte01.mp4", "titulo": "Gol", "nota": 8.5}))
    aprovar(corte, "x", [], pasta_contas=pareado)
    http = Falso(tg({"message_id": 10}), tg({"message_id": 11}))
    enviar(corte, "telegram", http=http, pasta_contas=pareado)
    assert "Gol · nota 8.5".encode() in http.chamadas[0]["corpo"]


def test_telegram_texto_falha_reenvia_so_texto(corte, pareado):
    aprovar(corte, "x", [], pasta_contas=pareado)
    http = Falso(tg({"message_id": 10}), tg(status=400, description="Bad Request: text is too long"))
    r = enviar(corte, "telegram", http=http, pasta_contas=pareado)
    assert r["estado"] == "erro" and "too long" in r["erro"] and r["mensagens"] == [10]
    tentar_de_novo(corte, "telegram", False, pasta_contas=pareado)
    http = Falso(tg({"message_id": 12}))
    r = enviar(corte, "telegram", http=http, pasta_contas=pareado)
    assert r["estado"] == "ok" and r["mensagens"] == [10, 12]
    assert [c["url"].rsplit("/", 1)[1] for c in http.chamadas] == ["sendMessage"]


def test_telegram_429_espera_e_repete(corte, pareado):
    aprovar(corte, "x", [], pasta_contas=pareado)
    esperas = []
    http = Falso(tg(status=429, description="Too Many Requests", parameters={"retry_after": 2}),
                 tg({"message_id": 10}), tg({"message_id": 11}))
    r = enviar(corte, "telegram", http=http, esperar=esperas.append, pasta_contas=pareado)
    assert esperas == [2] and r["estado"] == "ok" and r["mensagens"] == [10, 11]


def test_telegram_429_desiste_depois_de_3_repeticoes(corte, pareado):
    aprovar(corte, "x", [], pasta_contas=pareado)
    esperas = []
    http = Falso(*[tg(status=429, description="Too Many Requests", parameters={"retry_after": 1})] * 4)
    r = enviar(corte, "telegram", http=http, esperar=esperas.append, pasta_contas=pareado)
    assert esperas == [1, 1, 1] and r["estado"] == "erro"


def test_telegram_5xx_no_video_fica_incerto(corte, pareado):
    aprovar(corte, "x", [], pasta_contas=pareado)
    r = enviar(corte, "telegram", http=Falso(tg(status=502, description="Bad Gateway")), pasta_contas=pareado)
    assert r["estado"] == "incerto" and "confira no Telegram" in r["erro"]
    with pytest.raises(ValueError):
        tentar_de_novo(corte, "telegram", False, pasta_contas=pareado)


def test_telegram_video_grande_nao_tenta(corte, pareado, monkeypatch):
    import publicar
    monkeypatch.setattr(publicar, "LIMITE_TELEGRAM", 1000)
    aprovar(corte, "x", [], pasta_contas=pareado)
    http = Falso()
    r = enviar(corte, "telegram", http=http, pasta_contas=pareado)
    assert r["estado"] == "erro" and "aceita até 50 MB" in r["erro"] and http.chamadas == []


def test_telegram_video_grande_vai_comprimido(corte, pareado, monkeypatch):
    import publicar
    monkeypatch.setattr(publicar, "LIMITE_TELEGRAM", 1000)
    meta = json.loads(corte.read_text())
    corte.write_text(json.dumps({**meta, "duracao": 30}))

    def comprimir(video, duracao, pasta):
        assert duracao == 30
        leve = Path(pasta) / video.name
        leve.write_bytes(b"c" * 500)
        return leve
    monkeypatch.setattr(publicar, "_comprimir_para_telegram", comprimir)
    aprovar(corte, "x", [], pasta_contas=pareado)
    http = Falso(tg({"message_id": 1}), tg({"message_id": 2}))
    r = enviar(corte, "telegram", http=http, pasta_contas=pareado)
    assert r["estado"] == "ok" and b"c" * 500 in http.chamadas[0]["corpo"]
    assert (corte.parent / "fonte_corte01.mp4").read_bytes() == b"v" * 1234  # original intacto


def test_telegram_outro_bot_nao_reenvia(corte, pareado):
    aprovar(corte, "x", [], pasta_contas=pareado)
    enviar(corte, "telegram", http=Falso(tg(status=400, description="x")), pasta_contas=pareado)
    contas.salvar("telegram", {"token": "OUTRO", "bot": "velho", "chat_id": 7}, pareado)
    with pytest.raises(ValueError, match="outro bot"):
        tentar_de_novo(corte, "telegram", False, pasta_contas=pareado)
    assert tg_estado(corte)["estado"] == "erro"


def test_telegram_erro_nao_vaza_token(corte, pareado):
    aprovar(corte, "x", [], pasta_contas=pareado)
    r = enviar(corte, "telegram", http=Falso(tg(status=401, description=f"token {TOKEN} inválido")),
               pasta_contas=pareado)

    def cai(*a, **kw):
        raise OSError(f"falhou https://api.telegram.org/bot{TOKEN}/sendVideo")
    assert r["estado"] == "erro" and TOKEN not in r["erro"]
    tentar_de_novo(corte, "telegram", False, pasta_contas=pareado)
    r = enviar(corte, "telegram", http=cai, pasta_contas=pareado)
    assert r["estado"] == "incerto" and TOKEN not in r["erro"]
    assert TOKEN not in corte.with_suffix(".publicacao").read_text(encoding="utf-8")


def test_telegram_enviando_orfao_vira_incerto(corte, pareado):
    aprovar(corte, "x", [], pasta_contas=pareado)
    assert ler_publicacao(corte, set())["telegram"]["estado"] == "incerto"


def test_telegram_resposta_sem_message_id_fica_incerto(corte, pareado):
    """O vídeo saiu (200) mas não deu para ler/gravar o id: "erro" reenviaria sem forçar (post duplo)."""
    aprovar(corte, "x", [], pasta_contas=pareado)
    r = enviar(corte, "telegram", http=Falso(tg({})), pasta_contas=pareado)
    assert r["estado"] == "incerto"
    with pytest.raises(ValueError, match="pode ter saído"):
        tentar_de_novo(corte, "telegram", False, pasta_contas=pareado)


def test_aprovar_conta_telegram_corrompida_nao_trava(corte, pasta):
    (pasta / "telegram.json").write_text("{quebrado", encoding="utf-8")
    assert aprovar(corte, "x", [], pasta_contas=pasta) == ["youtube", "instagram"]
    assert "telegram" not in ler_publicacao(corte, set())
