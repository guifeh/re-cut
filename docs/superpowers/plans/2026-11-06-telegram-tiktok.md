# Telegram para o TikTok — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** aprovar um corte também o envia (vídeo + texto) ao Telegram do usuário, e a resposta com o link do TikTok volta para o corte.

**Architecture:** módulo novo `telegram.py` (conta do bot, chamadas à Bot API, escuta por long polling e tratamento
das mensagens). `publicar.py` guarda o estado do envio na chave `telegram` do `.publicacao` e o envia pelas mesmas
regras das plataformas (enviando → ok/erro/incerto). `server.py` dispara o envio na aprovação, expõe as rotas da
conta e roda a thread de escuta. Frontend: card na aba Contas e linha no painel de aprovação.

**Tech Stack:** Python 3.12 stdlib (urllib via `contas.requisitar`), pytest; React + TS + Vite + shadcn.

**Spec:** `docs/superpowers/specs/2026-11-06-telegram-tiktok-design.md` (ler inteira antes de cada tarefa).

## Global Constraints

- Base da API: `https://api.telegram.org/bot<token>/<método>`; nada de webhook, só `getUpdates` (long polling, `timeout=50`).
- Vídeo por bot: até 50 MB (`50 * 1024 * 1024` bytes); acima disso não tenta e grava `erro` "o vídeo tem N MB e o Telegram aceita até 50 MB: use o Baixar".
- `429` = não enviado: espera `parameters.retry_after` e repete o mesmo passo, até 3 vezes.
- O token nunca aparece em log, mensagem de erro, resposta da API, frontend ou commit (trocar por `***`).
- Contas em `contas/telegram.json` (pasta já no `.gitignore`); trocar o token zera o arquivo; desconectar apaga.
- `contas.PLATAFORMAS` continua `("youtube", "instagram")`; `esteira.PLATAFORMAS` não ganha "telegram" (sem nó novo).
- Estado gravado antes de cada passo de rede; nunca reenviar sozinho; `enviando` órfão vira `incerto`.
- Testes sem rede (http falso como o `Falso` de `test_publicar.py`); comandos: `.venv/Scripts/python -m pytest -q`.
- Português nos nomes e mensagens, comentários curtos, só stdlib no backend, como o resto do repo.

## Review Focus

1. Reply com link a uma mensagem de corte enviada por **outro bot/chat** (token trocado): não grava em corte nenhum e responde pedindo para colar na tela.
2. `/start` com código errado, ou de outro chat depois de pareado: ignorado; o `chat_id` não muda.
3. Vídeo saiu e o texto falhou: `mensagens` guarda o vídeo; "tentar de novo" manda só o texto.
4. Servidor reiniciado com update não processado: o `offset` persistido evita processar a mesma resposta duas vezes (link já salvo → nenhuma escrita nova, bot responde o erro do `colar_link`).
5. Corte aprovado com o Telegram desconectado: sem chave `telegram`, linha não aparece, aprovação igual a hoje.

Cada item tem teste na tarefa dona (marcado com **RF n**).

---

### Task 1: conta do bot e chamadas à Bot API (`telegram.py`)

**Files:**
- Create: `telegram.py`, `test_telegram.py`
- Modify: `contas.py` (`_validar` aceita também `"telegram"`; `PLATAFORMAS` intacto)

**Interfaces:**
- Produces:
  - `class Recusado(ValueError)` com atributos `status: int`, `retry_after: int | None` (4xx da Bot API; mensagem = `description`).
  - `chamar(token: str, metodo: str, dados: dict | None = None, arquivo: tuple[str, Path] | None = None, http=None, timeout: int = 60) -> object` — POST; com `arquivo=(campo, caminho)` monta multipart (stdlib, corpo em memória) com os `dados` como campos; devolve `result`; 4xx → `Recusado`; 5xx → `ValueError`; rede → `OSError`. Token nunca na mensagem.
  - `publico(pasta=contas.PASTA) -> dict` com chaves `plataforma="telegram", configurada, conectada, nome, bot, link_pareamento` (spec, "Estado público").
  - `configurar(token: str, http=None, pasta=contas.PASTA) -> dict` — `getMe`, grava `{token, bot, pareamento}` (zera o resto se o token mudou), devolve `publico`.
  - `desconectar(pasta=contas.PASTA) -> dict`.
  - `conta(pasta=contas.PASTA) -> dict` (o JSON cru, para os outros módulos).

- [ ] **Step 1: testes que falham** em `test_telegram.py` (http falso devolvendo `{"ok": true, "result": ...}`):
  - `test_configurar_valida_token_e_gera_pareamento`: `getMe` → `{"username": "meu_bot"}`; `publico` = `{"configurada": True, "conectada": False, "bot": "meu_bot", "link_pareamento": "https://t.me/meu_bot?start=<pareamento>"}`; a URL chamada termina em `/getMe`.
  - `test_token_invalido_e_400_sem_vazar`: `getMe` → 401 `{"ok": false, "description": "Unauthorized"}`; `ValueError` cuja mensagem contém "Unauthorized" e não contém o token; nada gravado.
  - `test_trocar_token_zera_chat`: conta pareada (`chat_id`), configurar outro token → `conectada False`, `chat_id` ausente.
  - `test_desconectar_apaga_arquivo`.
  - `test_chamar_429_traz_retry_after`: 429 `{"parameters": {"retry_after": 3}}` → `Recusado` com `retry_after == 3`.
  - `test_chamar_multipart`: `arquivo=("video", mp4)` → `Content-Type` `multipart/form-data; boundary=...`, corpo contém o nome do arquivo, os bytes e o campo `chat_id`.
  - `test_publico_nunca_tem_token`: `"token"` não aparece em `json.dumps(publico(...))`.
- [ ] **Step 2:** rodar `.venv/Scripts/python -m pytest test_telegram.py -q` → falham (módulo não existe).
- [ ] **Step 3:** implementar em `telegram.py`; gravação por `contas.salvar("telegram", ...)`/`contas.ler("telegram", ...)`; pareamento `secrets.token_urlsafe(6)`.
- [ ] **Step 4:** rodar a suíte inteira → passa.
- [ ] **Step 5:** commit `Telegram: conta do bot (token, pareamento) e chamadas à Bot API`.

### Task 2: envio do corte aprovado (`publicar.py`)

**Files:**
- Modify: `publicar.py`, `test_publicar.py`

**Interfaces:**
- Consumes: `telegram.conta`, `telegram.chamar`, `telegram.Recusado`.
- Produces:
  - `aprovar(corte_json, legenda, hashtags, pasta_contas=contas.PASTA) -> list[str]` — se a conta do Telegram estiver pareada, grava também `pub["telegram"] = {"estado": "enviando", "erro": None, "em": ..., "mensagens": [], "bot": ..., "chat_id": ...}` e devolve `["youtube", "instagram", "telegram"]`; senão igual a hoje.
  - `enviar(corte_json, "telegram", http=None, esperar=time.sleep, pasta_contas=...)` — mesma entrada que o servidor já chama; delega ao envio do Telegram.
  - `tentar_de_novo(corte_json, "telegram", forcar, pasta_contas=contas.PASTA)` — mesmas regras; recusa com "enviado por outro bot: cole o link do TikTok na tela" se `bot`/`chat_id` do registro ≠ conta atual.
  - `ler_publicacao` também vira `incerto` o `telegram` `enviando` sem `(chave, "telegram")` em `ativos`.
- Envio: legenda do vídeo `f"{titulo} · nota {nota:g}"` (sem nota: só o título); texto `"<pre>" + html.escape(texto_final(...), quote=False) + "</pre>"` com `parse_mode=HTML`; passos já presentes em `mensagens` (índice 0 vídeo, 1 texto) são pulados; cada `message_id` gravado assim que volta.

- [ ] **Step 1: testes que falham** (conta pareada salva em `pasta` com `token`, `bot="meu_bot"`, `chat_id=7`):
  - `test_aprovar_com_telegram_pareado`: devolve as três; `pub["telegram"]` com `estado "enviando"`, `bot "meu_bot"`, `chat_id 7`.
  - `test_aprovar_sem_telegram_igual_a_hoje` (**RF 5**): sem conta → `["youtube", "instagram"]` e sem chave `telegram`.
  - `test_telegram_envia_video_e_texto`: http falso → `sendVideo` `{"message_id": 10}`, `sendMessage` `{"message_id": 11}`; estado `ok`, `mensagens == [10, 11]`; o texto enviado começa com `<pre>` e tem `&lt;` para um `<` da legenda.
  - `test_telegram_texto_falha_reenvia_so_texto` (**RF 3**): `sendMessage` 400 → `erro`, `mensagens == [10]`; `tentar_de_novo` + `enviar` com só `sendMessage` na fila → `ok`, `[10, 12]`.
  - `test_telegram_429_espera_e_repete`: 429 `retry_after 2` e depois 200; `esperar` chamado com 2; estado `ok`.
  - `test_telegram_5xx_no_video_fica_incerto`.
  - `test_telegram_video_grande_nao_tenta`: monkeypatch do limite para 1000 bytes (constante `LIMITE_TELEGRAM` em `publicar.py`) → `erro` com "aceita até 50 MB" e nenhuma chamada.
  - `test_telegram_outro_bot_nao_reenvia` (**RF 1**, parte do reenvio): registro com `bot "velho"` → `tentar_de_novo` levanta com "outro bot".
  - `test_telegram_erro_nao_vaza_token`.
- [ ] **Step 2:** rodar → falham.
- [ ] **Step 3:** implementar (um `_mudar_telegram` análogo a `_mudar`, sob `_trava`).
- [ ] **Step 4:** suíte inteira passa.
- [ ] **Step 5:** commit `Publicação: corte aprovado vai também para o Telegram (vídeo + texto), com reenvio só do que faltou`.

### Task 3: escuta das mensagens (`telegram.py`)

**Files:**
- Modify: `telegram.py`, `test_telegram.py`

**Interfaces:**
- Consumes: `publicar.colar_link` (importar `publicar` dentro de `processar`: `publicar` importa `telegram` no topo, e o import no topo dos dois lados seria circular); `telegram.chamar`.
- Produces:
  - `achar_corte(jobs: Path, bot: str, chat_id: int, message_id: int) -> Path | None` — varre `jobs.glob("**/*.publicacao")`; casa quando `telegram.bot`, `telegram.chat_id` batem e `message_id in telegram.mensagens`; devolve o `.json` do corte. Comentário `# ponytail: varre os .publicacao; índice em contas/telegram.json se ficar lento`.
  - `processar(update: dict, jobs: Path, http=None, pasta=contas.PASTA) -> None` — regras da spec ("Respostas com link"); textos do bot: pareou → "Pronto, os cortes aprovados vão chegar aqui"; link salvo → f"✓ link salvo em {titulo}"; sem reply / reply desconhecida → "Responda (arrastar para o lado) à mensagem do corte com o link"; erro do `colar_link` → a mensagem dele. Link = primeiro `https://...` do texto cujo host é `tiktok.com` ou subdomínio.
  - `ouvir(jobs: Path, http=None, pasta=contas.PASTA, dormir=time.sleep, continuar=lambda: True) -> None` — enquanto `continuar()`: sem token → `dormir(5)`; com token → `getUpdates(offset, timeout=50, allowed_updates=["message"])` (timeout da chamada 60 s), `processar` cada um e grava `offset = update_id + 1` após cada update; exceção → log só com o tipo e `dormir` com backoff 1, 2, 4… até 60 s, zera ao dar certo.

- [ ] **Step 1: testes que falham:**
  - `test_start_com_codigo_pareia`: conta com `pareamento "abc"`, update `/start abc` do chat 7 (first_name "Gui") → `chat_id 7`, `nome "Gui"`, `pareamento` ausente, bot respondeu "Pronto…".
  - `test_start_errado_ou_outro_chat_ignorado` (**RF 2**): `/start xyz` → nada gravado, nenhuma chamada; já pareado com 7, `/start abc` do chat 8 → `chat_id` continua 7, nenhuma chamada.
  - `test_reply_com_link_salva_no_corte`: corte com `telegram.mensagens [10, 11]`, `bot`/`chat_id` atuais, tiktok `manual` → reply a 11 com "olha https://www.tiktok.com/@eu/video/1" → `plataformas.tiktok.estado "ok"` e link salvo; bot respondeu "✓ link salvo em t".
  - `test_reply_de_outro_bot_nao_salva` (**RF 1**): registro com `bot "velho"` → link não gravado; resposta pede a mensagem do corte.
  - `test_link_sem_reply_pede_reply`.
  - `test_link_repetido_responde_erro_do_colar_link` (**RF 4**): tiktok já `ok` com link → arquivo não muda; bot respondeu "essa plataforma não espera link agora".
  - `test_ouvir_grava_offset_e_volta_apos_erro`: http falso: `OSError`, depois `getUpdates` com `update_id 5`; `continuar` para após 2 voltas; `offset == 6`; `dormir` chamado com 1.
- [ ] **Step 2:** rodar → falham.
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** suíte inteira passa.
- [ ] **Step 5:** commit `Telegram: pareamento pelo /start e link do TikTok respondido no chat volta para o corte`.

### Task 4: servidor, esteira e documentação

**Files:**
- Modify: `server.py`, `esteira.py`, `test_server.py`, `test_esteira.py`, `docs/contas-passo-a-passo.md`, `README.md`

**Interfaces:**
- Consumes: `telegram.publico/configurar/desconectar/ouvir`, `publicar.aprovar(..., pasta_contas)`.
- Produces:
  - `GET /api/contas` devolve os itens atuais + `telegram.publico(contas.PASTA)`.
  - `POST /api/contas/telegram/configurar` `{"token"}` e `POST /api/contas/telegram/desconectar` `{}` (Task 1; erros → 400 como as outras rotas).
  - `aprovar_corte` registra as chaves de `("youtube", "instagram", "telegram")` em `_disparar` (as não devolvidas por `aprovar` saem na hora, como já faz).
  - `mudar_publicacao` aceita `plataforma "telegram"` só com `acao` `tentar`/`forcar` (`link` → 400 "o Telegram não recebe link").
  - `__main__` inicia `threading.Thread(target=telegram.ouvir, args=(JOBS,), kwargs={"pasta": contas.PASTA}, daemon=True)`.
  - `esteira._feed_publicacao`: linhas "Enviado ao Telegram · <nome>" (`ok`) e "Telegram: <erro> · <nome>" (`erro`/`incerto`), `etapa "tiktok"`.

- [ ] **Step 1: testes que falham:**
  - `test_contas_lista_telegram_sem_token`: `GET /api/contas` tem item `plataforma "telegram"`; nenhum valor de token no corpo.
  - `test_aprovar_dispara_telegram_quando_pareado`: com `envio_falso` + conta pareada → chamadas incluem `telegram` com estado `enviando` no disco.
  - `test_publicacao_telegram_link_e_400`.
  - `test_feed_mostra_envio_ao_telegram` (em `test_esteira.py`).
- [ ] **Step 2:** rodar → falham.
- [ ] **Step 3:** implementar; docs: seção "Telegram" no passo a passo (BotFather `/newbot` → token → aba Contas → botão "Abrir no Telegram" → Começar; responder à mensagem com o link) e uma linha no README em "Esteira e publicação".
- [ ] **Step 4:** suíte inteira passa.
- [ ] **Step 5:** commit `Servidor: rotas do Telegram, envio na aprovação, escuta em segundo plano; feed e passo a passo`.

### Task 5: telas (Contas e painel de aprovação)

**Files:**
- Modify: `frontend/src/api.ts`, `frontend/src/contas.tsx`, `frontend/src/aprovacao.tsx`, `frontend/src/plataformas.ts` (se o nome/cor ficar lá)

**Interfaces:**
- Consumes: rotas da Task 4.
- Produces:
  - `api.ts`: `Conta` aceita `plataforma: 'telegram'` com `bot?: string | null`, `link_pareamento?: string | null`; `Publicacao.telegram?: { estado: 'enviando' | 'ok' | 'erro' | 'incerto'; erro: string | null; em: string; mensagens: number[] }`; `api.configurarTelegram(token)`; a ação de publicação aceita `plataforma 'telegram'`.
  - Card Telegram (spec, "Telas"): sem token → campo de token (type password) + link para o passo a passo; aguardando → botão "Abrir no Telegram" (`link_pareamento`, nova aba) e recarrega `/api/contas` a cada 3 s até `conectada`; conectado → "Conectado como <nome> (@bot)", Trocar token, Desconectar.
  - Linha "Telegram" abaixo do TikTok no painel quando `publicacao.telegram` existe: estado com a cor do mapa de estados, erro, "tentar de novo" (erro) / "enviar mesmo assim" (incerto). Toast da aprovação: "o TikTok foi para o seu Telegram" quando a resposta tem `telegram`.

- [ ] **Step 1:** implementar.
- [ ] **Step 2:** `cd frontend && npm run build` → sem erro de tipo.
- [ ] **Step 3:** subir `server.py` e conferir no navegador a aba Contas (card do Telegram sem token) e o painel de um corte aprovado sem Telegram (linha ausente).
- [ ] **Step 4:** commit `Frontend: card do Telegram na aba Contas e linha do envio no painel de aprovação`.
