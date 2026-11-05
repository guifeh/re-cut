# Esteira automática: cortar, escolher e postar em YouTube Shorts, Reels e TikTok

Data: 2026-11-04 · Status: rascunho para aprovação

## Por quê

Cortar já é automático no re-cut. O trabalho que sobra para o usuário é **distribuir**: pegar cada corte bom, escrever
legenda e hashtags e postar à mão em três plataformas (uma conta dele em cada: YouTube Shorts, Instagram Reels e
TikTok), trocando de app e colando texto. A esteira faz isso: entra um vídeo ou uma live, saem os melhores cortes com
legenda e hashtags para ele escolher, e **um clique aprova e posta nas três**, devolvendo o link de cada post.

O usuário quer **ver** a esteira trabalhando: uma tela no estilo do editor do n8n, com nós ligados, animados enquanto
processam, e os vídeos passando de um nó para o outro.

## Objetivos

1. Uma aba **Esteira** com nós estilo n8n: Entrada → Baixar → Transcrever → IA escolhe momentos → Renderizar →
   Ranking + legenda/hashtags → Sua aprovação → Publicar (três saídas: YouTube Shorts, Instagram Reels, TikTok).
2. Animação que reflete o que está acontecendo de verdade no servidor (não enfeite): nó rodando com borda girando e
   progresso, ligações com contagem de itens, cartões de vídeo/corte deslizando entre nós, verde no sucesso,
   vermelho com "tentar de novo" no erro, laranja em "esperando você".
3. Feed ao vivo com horário e o que aconteceu, e um resumo do dia (cortes gerados, aprovados, postados, erros).
4. Cortes chegam à aprovação **ordenados pela nota viral (0–10) com o motivo** (já existe no re-cut).
5. Para cada corte, a IA sugere **3 opções de legenda** e uma lista de **hashtags**; o usuário escolhe uma legenda,
   marca as hashtags e pode editar.
6. **Aprovou = postado**: um clique publica na hora no YouTube Shorts e no Instagram Reels e mostra o link de cada
   post (também salvo no corte). O **TikTok é manual**: o nó do TikTok entrega o vídeo (QR code para abrir no
   celular e botão de baixar) e a legenda + hashtags com botão de copiar; o usuário posta no app e cola o link de
   volta, que fica salvo no corte como os outros.
7. Tela **Contas** para conectar YouTube e Instagram uma vez, com passo a passo, aviso de acesso vencendo e
   renovação automática quando a plataforma permitir.

## Fora desta versão (não-objetivos)

- Vigiar canais e pegar **vídeos novos** sozinho (a live já é vigiada hoje pelo modo "monitorar"). O usuário achou
  interessante, mas ainda não tem canais; fica para depois. Como funcionaria está registrado no fim deste documento.
- Agendar postagens ou espalhar ao longo do dia (o usuário quer na hora).
- Legenda diferente por plataforma (uma legenda só para as três).
- Editor visual de fluxos (montar/arrastar nós). A esteira é fixa; a tela só mostra.
- Mais de uma conta por plataforma, outras redes, analytics de desempenho dos posts.

## Antiobjetivos (seria um fracasso mesmo funcionando)

- Postar qualquer coisa sem o clique do usuário.
- Animação "de mentira" que não corresponde ao estado real (ex.: nó girando com o processo parado ou morto).
- Uma plataforma falhando derrubar ou repetir as outras (postar duas vezes no YouTube porque o TikTok falhou).
- Tokens/segredos das contas indo para o git, para o log ou para o frontend.
- Fechar o navegador parar a esteira.

## Restrições

- Tudo local: servidor stdlib Python (`server.py`) no PC do usuário, `http://localhost:8000`, um usuário só.
  Sem endereço público na internet.
- IA pela sessão local dos agentes CLI (claude/codex/gemini), sem API key — decisão já tomada no projeto.
- Frontend React/Vite/TS + Tailwind 4 + shadcn existente (`frontend/`).
- Repo privado; nunca commitar segredos. Arquivos de conta ficam fora do git.
- Regras das plataformas (pesquisa de 2026-11-04, ver Evidências):
  - **YouTube**: `videos.insert` (Data API v3), upload resumable do arquivo local; vertical ≤ 3 min vira Short; link
    `https://youtube.com/shorts/<id>` na hora. **Público sem auditoria**: desde 2026-11-02 vídeos de projetos não
    verificados não ficam mais presos em privado (revision history da Data API). Cota: 1 unidade no bucket
    "Video Uploads" por chamada (o custo caiu de ~1600 para ~100 unidades em 2025-12-04), folgado para um usuário.
    OAuth com app "Desktop" e redirect loopback em localhost. Com a tela de
    consentimento em "Testing" o refresh token vence em 7 dias → o passo a passo manda colocar em "In production".
  - **Instagram**: Instagram API com Instagram Login; conta **profissional** (Creator/Business); permissão
    `instagram_business_content_publish`; Standard Access basta para a própria conta (sem App Review). Container
    `media_type=REELS` com `upload_type=resumable` (arquivo local), polling do `status_code` até `FINISHED`,
    `media_publish`, depois `permalink`. Token longo de 60 dias, renovável. 100 posts/24h; legenda ≤ 2200, ≤ 30 hashtags.
  - **TikTok**: Content Posting API (Direct Post), `FILE_UPLOAD` em chunks. App **não auditado só posta como
    privado (SELF_ONLY)** e não devolve link. Além disso, **a conta inteira precisa estar privada no momento do
    envio** ("All user accounts using the API client to post must be set to private at the time of posting" —
    content-sharing-guidelines). Revisão não é caminho: as regras recusam ferramenta para postar nas próprias contas.
    App Desktop aceita redirect `http://localhost:<porta>` (PKCE com SHA256 em hex). ~15 posts/dia por criador; 6 req/min por token.

## Decisões do usuário (como ele decidiu)

- Visual **A** dos esboços: linha de nós estilo n8n com animação dos processos e feed ao vivo.
- Uma conta em cada plataforma, todas dele, todas recebem o mesmo corte.
- O usuário escolhe os cortes; a esteira para em "Sua aprovação". Aprovou = postado na hora nas três, com o link
  de cada plataforma de volta.
- **TikTok: manual**. Primeiro aceitou post privado via API; ao saber que a API também exige a conta inteira
  privada na hora do envio, decidiu: sem app do TikTok, postagem manual com o vídeo e a legenda prontos.
- **Apps de desenvolvedor**: o próprio usuário registra os dois (projeto no Google Cloud, app na Meta), guiado
  pelo passo a passo (`docs/contas-passo-a-passo.md`, base do texto da tela Contas). Sem serviço terceiro pago. (O cut.pro faz o mesmo como
  empresa: os clientes usam os apps já registrados e auditados dele.)
- Entrada continua como hoje (colar link, enviar arquivo, acompanhar live).

## Decisões minhas (o usuário pode trocar)

- **React Flow (`@xyflow/react`, MIT)** para os nós e ligações. O n8n usa Vue Flow (irmã) sob licença não-aberta:
  copiamos só o visual medido, nunca código. Referência visual medida no n8n: nó 96×96, raio 16, borda 1.5px;
  rodando = borda com `conic-gradient` coral `#ff6d5a` girando (1.5 s, `@property` animada); ok = borda verde 2px +
  ✓; erro = borda vermelha 2px; ligação Bézier 2px cinza, verde ao concluir, rótulo "N itens" no meio; fundo de
  pontos com gap 16.
- A tela é só uma janela: a esteira roda no servidor (jobs como subprocessos, como hoje). O frontend acompanha por
  polling do que já existe (`/api/jobs`), estendido com o estado por etapa; SSE só se o polling ficar feio.
- **Estado por etapa vem do próprio pipeline**: `recut.py` passa a emitir eventos estruturados (uma linha JSON por
  evento no log do job: etapa, início/fim, progresso, item, erro). A tela deriva tudo disso.
- A nota e o motivo continuam vindo da mesma chamada de IA que escolhe os cortes. As 3 legendas entram no mesmo
  esquema (`legendas: [3 strings]`), sem chamada extra; `hashtags` já existe.
- Título do YouTube = legenda escolhida cortada em 100 caracteres; descrição = legenda + hashtags.
- Publicar = um sub-job por plataforma, independente: falha de uma não afeta as outras; "tentar de novo" refaz só a
  que falhou e nunca repete uma que já deu certo (estado gravado antes de cada envio).
- O nó do TikTok fica laranja ("sua vez") até o usuário colar o link; isso não bloqueia o corte de aparecer como
  postado nas outras duas.
- Instagram: o link aparece 1–5 min depois; a esteira confere sozinha.
- Contas e tokens em `contas/` (no `.gitignore`), um JSON por plataforma, nunca expostos pela API (o frontend só vê
  "conectado como X, vence em N dias"). Renovação automática do token do Instagram antes de vencer.
- Chamadas às APIs das plataformas com `urllib` da stdlib (sem SDKs do Google/Meta), como o resto do projeto.
- **Tela por job**: a Esteira mostra um job por vez (seletor no topo, padrão = o job ativo mais recente), como
  no esboço; o resumo do dia soma todos os jobs.
- **Envio que caiu no meio**: nunca reenviar sozinho. Se o processo morrer entre enviar e receber a resposta, a
  plataforma fica "incerto — confira no app", com "já saiu (colar link)" e "enviar de novo". O Instagram dá para
  conferir pelo container antes; nas outras decide o usuário.
- Login do Instagram: a Meta exige redirect HTTPS, então o retorno vai para `callback.html` num GitHub Pages grátis,
  num repositório público separado (`re-cut-site`) que só mostra o código para colar no re-cut. Nada do re-cut vai para ele (o repo do re-cut continua
  privado; Pages em repo privado exige plano pago).
- Corte não aprovado: "Descartar" manda para a Lixeira que já existe.

## Deixado para quem construir

- Desenho exato do evento estruturado e de como o servidor agrega por job/corte.
- Layout fino dos nós (ícones, textos), duração das animações além da referência, cores do tema atual.
- Onde mora o estado de publicação de cada corte (no JSON do corte ou num arquivo ao lado), desde que gravado de
  forma atômica como o resto (`gravar_json`).
- Como o passo a passo da tela Contas guia cada OAuth (redirect loopback, colar código etc.), dentro das regras
  acima (YouTube: loopback em localhost; Instagram: callback HTTPS no GitHub Pages + colar o código).
- QR code do TikTok: o celular não alcança `localhost`, então o QR precisa apontar para o IP do PC na rede local.
  Não abrir o servidor inteiro para a rede: só um link de uso único/curta duração para aquele arquivo. Se isso
  ficar complicado, o botão de baixar basta e o QR fica para depois — avisar.
- Testes: seguir o padrão do repo (`test_recut.py`, `test_lixeira.py`), com as chamadas às plataformas simuladas.

## Para depois: vigiar canais (como funcionaria)

A cada ~5 min: feed público do canal no YouTube (`youtube.com/feeds/videos.xml?channel_id=…`, últimos 15 vídeos) ou
`yt-dlp` para Twitch/Kick; compara com a lista do que já foi visto (arquivo local); vídeo novo → fluxo de vídeo;
live → modo live existente. Ao adicionar um canal, só pega dali para frente. Push instantâneo do YouTube exigiria
endereço público, por isso polling.

## Evidências

- cut.pro (bundle público, 2026-11-04): publica em várias redes com conexão OAuth por conta
  (`api.profile.connections.post`), post imediato ou agendado (`api.posts.post({videos, scheduledAt, …})`), um item
  por rede com `ItemStatus` (pending|scheduled|rendering|publishing|retrying|completed|failed), `ItemPublishedUrl` e
  retry por item; legenda por IA (`api.posts.caption.post`); "Score viral 0-10 + motivo explicado"; "Maior nota
  primeiro".
- n8n (REA no iframe do `n8n-demo` + código em `packages/frontend/editor-ui/src/components/canvas/`): medidas e
  estados descritos em "Decisões minhas".
- Plataformas: https://developers.google.com/youtube/v3/docs/videos/insert ·
  https://developers.google.com/identity/protocols/oauth2 ·
  https://developers.facebook.com/docs/instagram-platform/content-publishing ·
  https://developers.tiktok.com/doc/content-posting-api-reference-direct-post ·
  https://developers.tiktok.com/doc/content-posting-api-reference-get-video-status
