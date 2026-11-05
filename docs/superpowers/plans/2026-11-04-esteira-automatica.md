# Esteira automática Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Aba "Esteira" estilo n8n que mostra o pipeline real rodando, aprovação dos cortes com legenda/hashtags e
publicação com um clique no YouTube Shorts e no Instagram Reels (TikTok manual), devolvendo o link de cada post.

**Architecture:** `recut.py` passa a gravar eventos estruturados no log do job; `esteira.py` (puro) deriva deles o
estado de cada nó. `contas.py` guarda credenciais/tokens em `contas/` e faz OAuth; `publicar.py` envia para cada
plataforma com `urllib`, gravando o estado de cada envio num arquivo ao lado do corte. `server.py` expõe tudo e roda
os envios em threads. Frontend: React Flow para os nós, polling a cada 2 s.

**Tech Stack:** Python 3.12 stdlib (+ libs já no `requirements.txt`), pytest; React 19 + Vite + TS + Tailwind 4 +
shadcn (Base UI) + `@xyflow/react` (MIT).

**Spec:** `docs/superpowers/specs/2026-11-04-esteira-automatica-design.md` · guia das contas:
`docs/contas-passo-a-passo.md`

## Global Constraints

- Tudo local: servidor em `127.0.0.1:8000`; nada de abrir o servidor principal para a rede.
- IA só pela sessão local dos agentes CLI (claude/codex/gemini), sem API key; sem chamada extra de IA para legendas.
- Chamadas a Google/Meta com `urllib` da stdlib, sem SDKs; sem dependência Python nova.
- Segredos (client secret, tokens) só em `contas/<plataforma>.json` (no `.gitignore`); nunca no log, na resposta da
  API, no frontend ou em commit.
- Postar só com o clique do usuário. Nunca reenviar sozinho; nunca repetir uma plataforma que já deu certo.
- Animação reflete estado real: job morto ⇒ nenhum nó "rodando".
- Gravações em disco atômicas (`recut.gravar_json`: temp + `os.replace`).
- YouTube: `privacyStatus` `public`, título ≤ 100 caracteres (legenda escolhida cortada), descrição = legenda +
  hashtags. Instagram: legenda ≤ 2200 caracteres, ≤ 30 hashtags. TikTok: manual (sem API).
- Textos da interface em português, no tom das telas existentes.

## Review Focus

- Servidor reinicia (ou cai) no meio de um envio → a plataforma aparece "incerto — confira no app", nunca reenvia
  sozinha (Task 4: `test_enviando_sem_thread_vira_incerto`).
- Agente devolve menos de 3 legendas, nenhuma, ou o campo nem vem (Gemini não tem schema forçado) → completa com a
  descrição/título, sem quebrar o lote (Task 1: `test_legendas_completa_e_corta`).
- Duplo clique em "Aprovar e postar" (ou duas abas) → um envio só por plataforma (Task 4:
  `test_aprovar_duas_vezes_nao_duplica`).
- Processo do job morre/é parado com uma etapa aberta → o nó não fica "rodando" (Task 2:
  `test_job_morto_nao_anima`).
- Conta não conectada ou token vencido/revogado → só aquela plataforma fica em erro com "reconecte a conta"; a outra
  segue (Task 4: `test_conta_ausente_erra_so_ela`).

---

### Task 1: Eventos estruturados e 3 legendas no pipeline

**Files:**
- Modify: `recut.py` (`SISTEMA`, `ESQUEMA`, `baixar`, `transcrever`, `processar`, `clipar_live`, `main`)
- Test: `test_recut.py`

**Interfaces:**
- Produces: `marcar(etapa: str, estado: str, item: str = "", **dados) -> None` imprime uma linha
  `@@ {"etapa": ..., "estado": ..., "item": ..., "t": "<iso segundos>", ...dados}` (JSON, `ensure_ascii=False`,
  `flush=True`). `etapa` ∈ `ETAPAS = ("entrada", "baixar", "transcrever", "ia", "renderizar", "ranking")`;
  `estado` ∈ `("inicio", "progresso", "fim", "erro")`; dados opcionais: `progresso` (0–1), `msg` (texto do feed),
  `n` (contagem), `corte` (nome do corte).
- Produces: `PREFIXO_EVENTO = "@@ "`.
- Produces: `limpar_legendas(c: dict) -> list[str]` — exatamente 3 strings não vazias, cada uma ≤ 2200 caracteres;
  completa com `descricao` e depois `titulo` quando faltar; o corte gravado ganha `legendas`.

- [ ] **Step 1: Write the failing tests**

```python
def test_marcar_emite_linha_json(capsys):
    marcar("transcrever", "progresso", "lote_0003", progresso=0.62, msg="Transcrevendo lote 3")
    linha = capsys.readouterr().out.strip()
    assert linha.startswith(PREFIXO_EVENTO)
    ev = json.loads(linha[len(PREFIXO_EVENTO):])
    assert ev["etapa"] == "transcrever" and ev["estado"] == "progresso" and ev["item"] == "lote_0003"
    assert ev["progresso"] == 0.62 and "t" in ev

def test_legendas_completa_e_corta():
    assert limpar_legendas({"legendas": ["a", "", "b", "c"], "descricao": "d", "titulo": "t"}) == ["a", "b", "c"]
    assert limpar_legendas({"descricao": "d", "titulo": "t"}) == ["d", "t", "t"]
    assert len(limpar_legendas({"legendas": ["x" * 3000], "descricao": "d", "titulo": "t"})[0]) == 2200
```

- [ ] **Step 2: Run to verify they fail** — `.venv/Scripts/python -m pytest test_recut.py -k "marcar or legendas" -v` → FAIL (ImportError).

- [ ] **Step 3: Implement**
  - `marcar` e `limpar_legendas` em `recut.py`.
  - `ESQUEMA`: novo campo obrigatório `legendas` (`array` de `string`, `minItems`/`maxItems` 3) e linha no
    `SISTEMA`: "Escreva 3 opções de legenda para o post (estilos diferentes: curiosidade, humor, direta), cada uma
    com até 150 caracteres, sem hashtags; as hashtags vão no campo próprio."
  - Pontos de emissão: `main` → `entrada` fim (msg com a entrada); `baixar` → inicio/progresso (yt-dlp
    `progress_hooks`, no máximo a cada 5%)/fim; `transcrever` → inicio/progresso (`s.end / info.duration`, a cada
    5%)/fim; `escolher_cortes` → `ia` inicio/fim (msg com agente e nº de cortes) ou erro quando nenhum agente
    responde; `processar` → `renderizar` inicio/fim por corte (`corte=nome`, `progresso=i/n`) e `ranking` fim
    (`n` cortes aprovados pela regra); `clipar_live` → `entrada` progresso por lote fechado. `item` = prefixo do
    vídeo ou nome do lote. Exceção não tratada em `main` → `marcar(<etapa atual>, "erro", msg=str(e))` antes de
    relançar; a etapa atual é a do último `marcar` (`ETAPA_ATUAL`, global do módulo).
  - `processar` grava `legendas = limpar_legendas(c)` no JSON do corte.

- [ ] **Step 4: Run all tests** — `.venv/Scripts/python -m pytest -q` → todos passam.

- [ ] **Step 5: Commit** — `git commit -am "Esteira: eventos estruturados no log e 3 legendas por corte"`

### Task 2: Estado da esteira derivado dos eventos

**Files:**
- Create: `esteira.py`
- Test: `test_esteira.py`

**Interfaces:**
- Consumes: formato `@@ {...}` da Task 1; o formato de `publicacao` da Task 4 (já embutido em cada corte pelo
  servidor — `esteira.py` não lê disco).
- Produces: `NOS = ("entrada", "baixar", "transcrever", "ia", "renderizar", "ranking", "aprovacao", "youtube",
  "instagram", "tiktok")`.
- Produces: `eventos(log: str) -> list[dict]` — só as linhas com o prefixo; linhas JSON inválidas são ignoradas.
- Produces: `estado(evs: list[dict], vivo: bool, cortes: list[dict]) -> dict` com
  `{"nos": {no: {"estado": "ocioso"|"rodando"|"ok"|"erro"|"esperando", "progresso": float|None, "itens": [str],
  "msg": str}}, "arestas": {"<origem>-<destino>": int}, "feed": [{"t", "etapa", "msg", "estado"}]}`.
  `cortes` = cortes do job já com `publicacao` (Task 4). `feed` = últimos 50, mais recente primeiro.
- Produces: `resumo_do_dia(cortes: list[dict], hoje: date) -> dict` → `{"cortes", "aprovados", "postados", "erros"}`.

Regras de `estado` (decididas aqui):
- Etapa com `inicio` sem `fim`/`erro` para o mesmo `item` → `rodando` se `vivo`, senão `erro` com msg
  "interrompido". `progresso` = último valor do item aberto.
- Último evento da etapa é `erro` → `erro`; teve `fim` e nada aberto → `ok`; sem eventos → `ocioso`.
- `itens` de uma etapa = itens cuja etapa mais recente é ela (os "cartões" que estão ali).
- `aprovacao`: `esperando` se há corte sem `publicacao.aprovado_em`; `itens` = esses cortes, ordenados por nota.
- `youtube`/`instagram`/`tiktok`: agregam o estado de cada corte aprovado (Task 4): algum `enviando` → `rodando`;
  algum `erro`/`incerto` → `erro`; `tiktok` com algum `manual` → `esperando`; todos `ok` → `ok`.
- `arestas[a-b]` = quantos itens já passaram de `a` para `b` (itens com `fim` em `a`).

- [ ] **Step 1: Write the failing tests** (`test_esteira.py`, eventos montados em memória com um helper `ev(...)`)

```python
def test_etapa_aberta_roda_so_com_job_vivo():
    evs = [ev("transcrever", "inicio", "v"), ev("transcrever", "progresso", "v", progresso=0.5)]
    assert estado(evs, vivo=True, cortes=[])["nos"]["transcrever"] == {"estado": "rodando", "progresso": 0.5, "itens": ["v"], "msg": ANY}

def test_job_morto_nao_anima():
    evs = [ev("ia", "inicio", "v")]
    no = estado(evs, vivo=False, cortes=[])["nos"]["ia"]
    assert no["estado"] == "erro" and "interrompido" in no["msg"]

def test_cartao_fica_na_etapa_mais_recente_e_aresta_conta():
    evs = [ev("baixar", "fim", "a"), ev("transcrever", "inicio", "a"), ev("baixar", "fim", "b")]
    s = estado(evs, vivo=True, cortes=[])
    assert s["nos"]["transcrever"]["itens"] == ["a"] and s["nos"]["baixar"]["itens"] == ["b"]
    assert s["arestas"]["baixar-transcrever"] == 2

def test_aprovacao_espera_e_ordena_por_nota():
    cortes = [{"nome": "c1", "nota": 7, "publicacao": {}}, {"nome": "c2", "nota": 9, "publicacao": {}}]
    no = estado([], vivo=False, cortes=cortes)["nos"]["aprovacao"]
    assert no["estado"] == "esperando" and no["itens"] == ["c2", "c1"]

def test_publicacao_agrega_por_plataforma():
    pub = {"aprovado_em": "2026-11-04T10:00:00", "plataformas": {"youtube": {"estado": "ok"}, "instagram": {"estado": "incerto"}, "tiktok": {"estado": "manual"}}}
    nos = estado([], vivo=False, cortes=[{"nome": "c", "nota": 8, "publicacao": pub}])["nos"]
    assert (nos["youtube"]["estado"], nos["instagram"]["estado"], nos["tiktok"]["estado"]) == ("ok", "erro", "esperando")

def test_linha_quebrada_no_log_e_ignorada():
    assert eventos('@@ {"etapa": "ia"\nlinha comum\n@@ {"etapa":"ia","estado":"fim","item":"x","t":"2026-11-04T10:00:00"}') == [ANY]

def test_resumo_do_dia():
    ...  # 2 cortes hoje (1 aprovado, youtube ok + instagram erro), 1 corte ontem → {"cortes": 2, "aprovados": 1, "postados": 1, "erros": 1}
```

- [ ] **Step 2: Run** — `.venv/Scripts/python -m pytest test_esteira.py -v` → FAIL (módulo não existe).
- [ ] **Step 3: Implement `esteira.py`** conforme as regras acima (funções puras, sem I/O).
- [ ] **Step 4: Run** — `.venv/Scripts/python -m pytest -q` → todos passam.
- [ ] **Step 5: Commit** — `git add esteira.py test_esteira.py && git commit -m "Esteira: estado dos nós derivado dos eventos"`

### Task 3: Contas (credenciais, OAuth e renovação)

**Files:**
- Create: `contas.py`
- Modify: `.gitignore` (adicionar `contas/`)
- Test: `test_contas.py`

**Interfaces:**
- Produces: `PLATAFORMAS = ("youtube", "instagram")`; `PASTA = Path(__file__).with_name("contas")`.
- Produces: `ler(plataforma, pasta=PASTA) -> dict` (vazio se não existe); `salvar(plataforma, dados, pasta=PASTA)`
  (atômico, via `recut.gravar_json`).
- Produces: `publico(plataforma, pasta=PASTA, agora=None) -> dict` → `{"plataforma", "configurada": bool,
  "conectada": bool, "nome": str|None, "vence_em": iso|None, "dias_restantes": int|None}` — **nunca** inclui
  `client_secret`, `access_token`, `refresh_token`.
- Produces: `configurar(plataforma, client_id, client_secret, pasta=PASTA)`.
- Produces: `url_autorizacao(plataforma, estado: str, pasta=PASTA) -> str`.
  - YouTube: `https://accounts.google.com/o/oauth2/v2/auth`, `redirect_uri=http://127.0.0.1:8000/api/contas/youtube/retorno`,
    `scope=https://www.googleapis.com/auth/youtube.upload`, `access_type=offline`, `prompt=consent`, PKCE S256
    (verifier guardado em `contas/youtube.json` junto do `estado`).
  - Instagram: `https://www.instagram.com/oauth/authorize`, `redirect_uri=https://guifeh.github.io/re-cut-site/callback.html`,
    `scope=instagram_business_basic,instagram_business_content_publish`, `response_type=code`.
- Produces: `concluir(plataforma, codigo: str, estado: str|None, http=None, pasta=PASTA) -> dict` (público).
  YouTube: confere `estado`, troca o código em `https://oauth2.googleapis.com/token`. Instagram: remove `#_` do fim
  do código, troca em `https://api.instagram.com/oauth/access_token`, depois token longo em
  `https://graph.instagram.com/access_token?grant_type=ig_exchange_token`, depois `GET /me?fields=user_id,username`.
- Produces: `token(plataforma, http=None, pasta=PASTA, agora=None) -> str` — access token válido; YouTube renova com
  o refresh token quando faltar < 5 min; erro claro `ValueError("conecte a conta do <plataforma> na aba Contas")`
  quando não há conta ou a renovação é recusada.
- Produces: `renovar_instagram(http=None, pasta=PASTA, agora=None) -> bool` — chama
  `https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token` quando faltam < 10 dias.
- `http` injetável: `http(metodo, url, dados=None, cabecalhos=None, corpo=None) -> (status, cabecalhos, bytes)`;
  padrão = wrapper de `urllib.request` definido aqui como `requisitar` e reaproveitado pela Task 4.

- [ ] **Step 1: Write the failing tests** (fake `http` que registra chamadas e devolve respostas prontas)

```python
def test_publico_nunca_expoe_segredos(tmp_path):
    salvar("youtube", {"client_id": "id", "client_secret": "S", "access_token": "A", "refresh_token": "R", "nome": "Canal", "vence_em": "2026-11-04T11:00:00"}, tmp_path)
    p = publico("youtube", tmp_path)
    assert p["conectada"] and "S" not in json.dumps(p) and "A" not in json.dumps(p) and "R" not in json.dumps(p)

def test_youtube_renova_token_vencendo(tmp_path): ...   # vence em 2 min → POST oauth2.googleapis.com/token com grant_type=refresh_token; token novo salvo
def test_youtube_estado_errado_recusa(tmp_path): ...    # concluir com estado diferente → ValueError, nada salvo
def test_instagram_codigo_tira_sufixo_e_pega_token_longo(tmp_path): ...  # "abc#_" → POST com code=abc; salva token longo, user_id, username, vence_em = agora + expires_in
def test_instagram_renova_so_perto_de_vencer(tmp_path): ...  # 30 dias → False sem chamada; 5 dias → True e vence_em atualizado
def test_token_sem_conta_pede_para_conectar(tmp_path):
    with pytest.raises(ValueError, match="aba Contas"):
        token("instagram", pasta=tmp_path)
```

- [ ] **Step 2: Run** — `.venv/Scripts/python -m pytest test_contas.py -v` → FAIL.
- [ ] **Step 3: Implement `contas.py`** e adicionar `contas/` ao `.gitignore`.
- [ ] **Step 4: Run** — `.venv/Scripts/python -m pytest -q` → todos passam.
- [ ] **Step 5: Commit** — `git add contas.py test_contas.py .gitignore && git commit -m "Esteira: contas do YouTube e Instagram (OAuth e tokens locais)"`

### Task 4: Publicação (estado por plataforma, YouTube, Instagram, TikTok manual)

**Files:**
- Create: `publicar.py`
- Modify: `lixeira.py` (`EXTENSOES_CORTE` ganha `.publicacao`)
- Test: `test_publicar.py`

**Interfaces:**
- Consumes: `contas.token`, `contas.ler` (para `user_id` do Instagram), `contas.requisitar`; `recut.gravar_json`.
- Produces: arquivo `<corte>.publicacao` (JSON; extensão escolhida para **não** casar com o glob
  `*_corte[0-9]*.json`) com `{"aprovado_em", "legenda", "hashtags": [str], "plataformas": {"youtube"|"instagram"|
  "tiktok": {"estado": "enviando"|"ok"|"erro"|"incerto"|"manual", "link": str|None, "erro": str|None, "em": iso,
  "container": str|None}}}`.
- Produces: `ler_publicacao(corte_json: Path, ativos: set[tuple[str, str]]) -> dict` — `enviando` sem
  `(str(corte_json), plataforma)` em `ativos` vira `incerto` (e é regravado).
- Produces: `texto_final(legenda: str, hashtags: list[str]) -> str` — legenda + linha em branco + hashtags com `#`,
  sem duplicar `#`, ≤ 30 hashtags, total ≤ 2200 caracteres.
- Produces: `aprovar(corte_json: Path, legenda: str, hashtags: list[str]) -> list[str]` — grava a escolha,
  `tiktok` = `manual`, `youtube`/`instagram` = `enviando`; devolve as plataformas a enviar. Se já existe
  `aprovado_em` → `ValueError("esse corte já foi aprovado")`.
- Produces: `enviar(corte_json: Path, plataforma: str, http=None, esperar=time.sleep) -> dict` — envia e grava
  `ok` + `link` ou `erro` + mensagem. Só roda a partir de `enviando`.
- Produces: `tentar_de_novo(corte_json, plataforma, forcar: bool) -> None` — `erro` → `enviando`; `incerto` só com
  `forcar=True`; `ok` → `ValueError("já foi postado")`.
- Produces: `colar_link(corte_json, plataforma, link) -> None` — aceita só `https://` do domínio da plataforma
  (`youtube.com`/`youtu.be`, `instagram.com`, `tiktok.com`); vale para `manual`, `incerto` e `erro`.
- YouTube (`enviar`): `POST https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status`
  com `{"snippet": {"title": <legenda[:100]>, "description": texto_final, "categoryId": "22"}, "status":
  {"privacyStatus": "public", "selfDeclaredMadeForKids": false}}`, `PUT` do arquivo no `Location`; link
  `https://youtube.com/shorts/<id>`.
- Instagram (`enviar`): `POST https://graph.instagram.com/v26.0/<user_id>/media` (`media_type=REELS`,
  `upload_type=resumable`, `caption`) → grava `container`; `POST https://rupload.facebook.com/ig-api-upload/v26.0/<container>`
  com `Authorization: OAuth <token>`, `offset: 0`, `file_size`; polling `GET /<container>?fields=status_code` a
  cada 30 s por até 10 min até `FINISHED` (`ERROR`/`EXPIRED` → erro); `POST /<user_id>/media_publish`
  (`creation_id`); `GET /<media_id>?fields=permalink`.

- [ ] **Step 1: Write the failing tests** (fake `http`; `esperar` no-op; corte de mentira em `tmp_path`)

```python
def test_aprovar_duas_vezes_nao_duplica(tmp_path): ...       # 2ª chamada → ValueError; plataformas continuam como na 1ª
def test_enviando_sem_thread_vira_incerto(tmp_path): ...     # arquivo com youtube=enviando, ativos=set() → "incerto"; com ativos → continua "enviando"
def test_incerto_so_reenvia_forcando(tmp_path): ...          # tentar_de_novo(forcar=False) → ValueError; forcar=True → "enviando"
def test_ok_nunca_reenvia(tmp_path): ...
def test_youtube_envia_publico_e_devolve_link_do_short(tmp_path): ...  # metadados: title cortado em 100, privacyStatus public; link youtube.com/shorts/<id>
def test_instagram_espera_container_e_pega_permalink(tmp_path): ...    # IN_PROGRESS, IN_PROGRESS, FINISHED → publish → permalink salvo
def test_instagram_container_com_erro_marca_erro(tmp_path): ...
def test_conta_ausente_erra_so_ela(tmp_path): ...            # sem contas/instagram.json: instagram "erro" com "aba Contas"; youtube segue "ok"
def test_texto_final_limita_hashtags():
    assert texto_final("oi", ["#a", "b"]) == "oi\n\n#a #b"
    assert texto_final("oi", [f"t{i}" for i in range(40)]).count("#") == 30
def test_colar_link_valida_dominio(tmp_path): ...            # tiktok manual + "https://www.tiktok.com/@x/video/1" → ok; "https://evil.com" → ValueError
def test_publicacao_vai_junto_para_a_lixeira(tmp_path): ...  # em test_lixeira.py: excluir_corte move também o .publicacao
```

- [ ] **Step 2: Run** — `.venv/Scripts/python -m pytest test_publicar.py test_lixeira.py -v` → FAIL.
- [ ] **Step 3: Implement `publicar.py`** e a extensão em `lixeira.py`. Toda mudança de estado grava o arquivo
  inteiro com `recut.gravar_json` **antes** da chamada de rede correspondente.
- [ ] **Step 4: Run** — `.venv/Scripts/python -m pytest -q` → todos passam.
- [ ] **Step 5: Commit** — `git add publicar.py test_publicar.py lixeira.py test_lixeira.py && git commit -m "Esteira: publicação no YouTube e Instagram com estado por plataforma"`

### Task 5: API da esteira, aprovação e contas no servidor

**Files:**
- Modify: `server.py`
- Test: `test_server.py` (novo; sobe o `ThreadingHTTPServer` numa porta livre com `JOBS`/`contas` em `tmp_path`
  via monkeypatch e chama com `urllib`)

**Interfaces:**
- Consumes: `esteira.eventos/estado/resumo_do_dia`, `publicar.*`, `contas.*`.
- Produces (rotas; erros seguem o padrão atual 400/404/409 com `{"erro"}`):
  - `GET /api/esteira/<job>` → `{"job": resumo(job), "esteira": estado(...)}`; `vivo` = job em `processos`; cada
    corte de `resumo` ganha `nome` (stem) e `publicacao` (via `ler_publicacao` com o conjunto `enviando_agora`).
  - `GET /api/esteira/resumo` → `resumo_do_dia` de todos os jobs.
  - `POST /api/jobs/<job>/cortes/aprovar` `{json, legenda, hashtags}` → valida `json` como `excluir_corte` faz,
    `publicar.aprovar`, dispara uma thread por plataforma (`enviar`) registrada em `enviando_agora` sob o `lock`.
  - `POST /api/jobs/<job>/cortes/publicacao` `{json, plataforma, acao: "tentar"|"forcar"|"link", link?}`.
  - `GET /api/contas` → `[contas.publico(p) for p in PLATAFORMAS]`.
  - `POST /api/contas/<p>/configurar` `{client_id, client_secret}`; `POST /api/contas/<p>/conectar` →
    `{"url": url_autorizacao(...)}`; `GET /api/contas/youtube/retorno?code&state` → `concluir` e redireciona
    (302) para `/?aba=contas`; `POST /api/contas/instagram/codigo` `{codigo}`; `POST /api/contas/<p>/desconectar`.
  - `expirar_periodicamente` também chama `contas.renovar_instagram()` (erros só no stdout, sem token).

- [ ] **Step 1: Write the failing tests**

```python
def test_esteira_de_job_parado_nao_tem_no_rodando(servidor): ...   # log com "@@ ia inicio" e job fora de processos → nó ia "erro"
def test_aprovar_dispara_envios_e_tiktok_fica_manual(servidor, monkeypatch): ...  # publicar.enviar trocado por fake; resposta 200; tiktok "manual"
def test_aprovar_corte_de_outro_job_e_400(servidor): ...           # json com ../ → 400
def test_api_contas_nao_vaza_segredo(servidor): ...                # contas/youtube.json com tokens → GET /api/contas sem tokens nem secret
def test_retorno_youtube_redireciona_para_aba_contas(servidor, monkeypatch): ...  # contas.concluir fake → 302 Location /?aba=contas
```

- [ ] **Step 2: Run** — `.venv/Scripts/python -m pytest test_server.py -v` → FAIL.
- [ ] **Step 3: Implement as rotas** em `server.py` (seguindo o estilo de `do_GET`/`do_POST`).
- [ ] **Step 4: Run** — `.venv/Scripts/python -m pytest -q` → todos passam.
- [ ] **Step 5: Commit** — `git add server.py test_server.py && git commit -m "Esteira: API de estado, aprovação, publicação e contas"`

### Task 6: Aba Esteira (nós estilo n8n com animação)

**Files:**
- Modify: `frontend/package.json` (`@xyflow/react`), `frontend/src/api.ts`, `frontend/src/App.tsx` (aba
  "Esteira" primeiro; aba vinda de `?aba=`), `frontend/src/index.css` (keyframes)
- Create: `frontend/src/esteira.tsx`

**Interfaces:**
- Consumes: `GET /api/esteira/<job>`, `GET /api/esteira/resumo`, `GET /api/jobs`.
- Produces (`api.ts`): tipos `EstadoNo`, `NoEsteira = {estado, progresso, itens, msg}`, `Esteira = {nos:
  Record<IdNo, NoEsteira>, arestas: Record<string, number>, feed: ItemFeed[]}`, `Publicacao`, `EstadoPlataforma`
  (espelham as Tasks 2 e 4); `Corte` ganha `nome`, `legendas: string[]`, `publicacao?: Publicacao`;
  `api.esteira(id)`, `api.resumoDoDia()`.
- Produces: `export function Esteira({ jobs }: { jobs: Job[] | null })` e
  `export function useEsteira(jobId: string | null)` (polling 2 s; para quando a aba não está visível).

Visual (do n8n medido; código nosso):
- Nó 96×96, raio 16, borda 1.5px neutra, ícone lucide no centro, nome embaixo (2 linhas máx.), subtítulo com `msg`
  ou `progresso` em %. Estados: `ok` borda 2px verde + ✓ no canto; `erro` borda 2px vermelha + "tentar de novo"
  quando for publicação; `esperando` borda laranja; `rodando` = pseudo-elemento `::after` (`inset: -3px`) com
  `conic-gradient(from var(--angulo), #ff6d5a 0 20%, #ff6d5a33 35% 65%, #ff6d5a 90%)` e `@property --angulo`
  animada 0→360deg em 1.5 s linear infinito; sem suporte a `@property` → `animate-spin` num wrapper.
- Ligações Bézier 2px cinza, verdes quando a origem está `ok`, rótulo "N itens" no meio (`EdgeLabelRenderer`).
- Fundo de pontos gap 16; canvas só leitura (`nodesDraggable={false}`, sem conectar), `fitView`.
- Cartões: um nó React Flow pequeno por item em `itens`, posicionado sob o nó onde está; CSS
  `transition: transform 600ms` no tipo de nó do cartão faz o deslize quando muda de etapa.
- Seletor de job no topo (padrão: job `rodando` mais recente, senão o mais recente); feed ao vivo (últimos 50) e
  resumo do dia embaixo, como no esboço A.
- Clique num nó abre um painel lateral com os itens dele; no nó `aprovacao` abre o painel da Task 7.

- [ ] **Step 1:** `cd frontend && npm install @xyflow/react` — instala sem erro.
- [ ] **Step 2:** Implementar `api.ts`, `esteira.tsx`, CSS e a aba em `App.tsx`.
- [ ] **Step 3:** `npm run build && npm run lint` → sem erros.
- [ ] **Step 4:** Verificar no navegador (Edge headless/CDP como nas features anteriores): job de teste com log
  sintético (eventos de todas as etapas, um nó rodando) → screenshot mostra borda girando no nó aberto, ✓ nos
  concluídos, "N itens" nas ligações e o feed; job parado → nada girando.
- [ ] **Step 5: Commit** — `git add frontend && git commit -m "Esteira: aba com nós estilo n8n animados pelo estado real"`

### Task 7: Painel de aprovação e publicação

**Files:**
- Create: `frontend/src/aprovacao.tsx`
- Modify: `frontend/src/api.ts`, `frontend/src/esteira.tsx`

**Interfaces:**
- Consumes: `POST /api/jobs/<job>/cortes/aprovar`, `POST /api/jobs/<job>/cortes/publicacao`,
  `POST /api/jobs/<job>/cortes/excluir` (existente → Lixeira).
- Produces: `api.aprovar(jobId, json, legenda, hashtags)`, `api.publicacao(jobId, json, plataforma, acao, link?)`;
  `export function PainelAprovacao({ job, cortes }: { job: Job; cortes: Corte[] })`.

Comportamento:
- Lista dos cortes esperando, maior nota primeiro: prévia 9:16 (`<video>`), nota + motivo, 3 legendas (radio,
  editável), hashtags como chips marcáveis (todas marcadas por padrão) + adicionar, prévia do texto final com
  contador (2200).
- "Aprovar e postar" desabilita na hora do clique (evita duplo envio) → toast; "Descartar" usa o `Confirmar` da
  Lixeira e o endpoint existente.
- Por corte aprovado, uma linha por plataforma: enviando (spinner), ok (link clicável + copiar), erro (mensagem +
  "Tentar de novo"), incerto ("Confira no app" + "Já saiu (colar link)" + "Enviar de novo" com confirmação).
- TikTok `manual`: botões "Baixar vídeo" (`video_url` com `download`), "Copiar legenda" (texto final) e campo
  "Colar link do TikTok". **QR code adiado** (o spec permite: exigiria um segundo servidor aberto na rede local e
  uma lib de QR); avisar o usuário na entrega.

- [ ] **Step 1:** Implementar.
- [ ] **Step 2:** `npm run build && npm run lint` → sem erros.
- [ ] **Step 3:** Verificar no navegador com um job real e as contas desconectadas: aprovar → YouTube e Instagram
  ficam em erro "conecte a conta…", TikTok mostra baixar/copiar/colar link; colar um link do TikTok → fica ok.
- [ ] **Step 4: Commit** — `git add frontend && git commit -m "Esteira: aprovação com legendas, hashtags e status por plataforma"`

### Task 8: Aba Contas

**Files:**
- Create: `frontend/src/contas.tsx`
- Modify: `frontend/src/api.ts`, `frontend/src/App.tsx`

**Interfaces:**
- Consumes: rotas `/api/contas*` da Task 5.
- Produces: `api.contas()`, `api.configurarConta(p, client_id, client_secret)`, `api.conectarConta(p)`,
  `api.codigoInstagram(codigo)`, `api.desconectarConta(p)`; `export function Contas()`.

Comportamento: um cartão por plataforma (YouTube, Instagram) com estado (não configurada → campos client id/secret;
configurada → "Conectar"; conectada → nome da conta, "vence em N dias", "Desconectar"); YouTube abre a URL de
autorização na mesma aba (volta por `/api/contas/youtube/retorno`); Instagram abre a URL em nova aba e mostra o campo
"Cole o código"; aviso quando faltam < 10 dias; cartão TikTok explicando que é manual (com o porquê em uma linha);
link para o guia `docs/contas-passo-a-passo.md` (texto resumido de cada passo no próprio cartão, colapsável).
O client secret é campo `password` e nunca volta da API.

- [ ] **Step 1:** Implementar.
- [ ] **Step 2:** `npm run build && npm run lint` → sem erros.
- [ ] **Step 3:** Verificar no navegador: configurar YouTube com valores falsos → "Conectar" leva à URL do Google
  com `redirect_uri` e `code_challenge`; `GET /api/contas` não contém o secret.
- [ ] **Step 4: Commit** — `git add frontend && git commit -m "Esteira: aba Contas"`

### Task 9: README e verificação ponta a ponta

**Files:**
- Modify: `README.md` (seção "Esteira e publicação": como funciona, contas, TikTok manual, onde ficam os tokens)

- [ ] **Step 1:** Atualizar o README.
- [ ] **Step 2:** `.venv/Scripts/python -m pytest -q` → todos passam; `cd frontend && npm run build` → ok.
- [ ] **Step 3:** Rodar `server.py`, cortar um vídeo curto de verdade e acompanhar a Esteira do começo ao fim
  (nós acendendo em ordem, cartões andando, cortes em "Sua aprovação"); screenshots para o usuário.
- [ ] **Step 4:** Varredura de segredos no diff (`git diff main --stat` + grep por `token|secret|client_`) e de
  arquivos gerados (`jobs/`, `uploads/`, `contas/`).
- [ ] **Step 5: Commit** — `git commit -am "Esteira: README"`

Depois: PR para a `main`, revisão `mattpocock-skills:code-review` (Standards + Spec) e merge só com as duas
aprovando, como nas features anteriores. A publicação real só é testada quando o usuário conectar as contas
seguindo o guia.
