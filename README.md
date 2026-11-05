# re-cut

Cortes verticais automáticos de lives e vídeos longos, com IA. Você aponta um vídeo (ou um canal ao vivo) e recebe clipes 9:16 legendados, cada um com nota viral de 0 a 10, motivo, título e descrição pronta para o post.

Inspirado no **Live Clipper do [cut.pro](https://cut.pro)**: o fluxo e o modelo de dados (monitoramento → transmissão → lotes de 10 min → cortes com nota) foram modelados a partir do que o próprio produto descreve publicamente.

## Como funciona

```
entrada ──► transcrição ──► análise ──► regra do lote ──► montagem
(URL,       (faster-whisper,  (agente de IA lê     (nota mínima,      (recorte 9:16 seguindo o
 arquivo,    tempo por         a transcrição +      duração, limite,   rosto, legenda no ritmo
 live)       palavra)          energia do áudio)    ordem pela nota)   da fala, thumbnail)
```

- **Lives:** espera o canal entrar ao vivo, grava em lotes de 10 minutos e corta cada lote assim que ele fecha, sem esperar a live terminar. Se a live cair e voltar em até 5 min, continua na mesma transmissão. Dá para limitar por dias da semana e horas.
- **Análise:** a IA procura picos de energia, reações, setup e payoff, histórias com começo e fim e opiniões fortes. Cada linha da transcrição vai com a energia do áudio relativa à mediana.
- **Templates de corte:** proporção (9:16, 1:1, 4:5, 16:9), enquadramento (seguir o rosto, rosto com câmera parada, centro ou vídeo inteiro sobre fundo desfocado), estilo da legenda (fonte, tamanho, cor, contorno ou caixa, maiúsculas, posição, palavras por vez, destaque da palavra falada, animação pop/fade), título de gancho, logo/marca d'água e velocidade. Escolhe-se um ao clipar (vídeo ou live) e dá para **reaplicar outro em cortes prontos** sem chamar a IA de novo. Modelado no editor do cut.pro (`AspectRatio`, `AutoCropping.FramingMode`, `SubtitleDisplayConfig`, `SubtitleSettings`, `HighlightStyle`, `Animation`, `Speed`). Vêm 5 prontos em `templates/`: `classico`, `destaque`, `caixa`, `podcast` e `impacto`.
- **Efeitos automáticos:** na mesma análise, a IA marca dentro de cada corte os momentos de `risada`, `reacao`, `enfase`, `punchline` e `virada` (com intensidade de 1 a 3 e um emoji). O template decide o que acontece em cada tipo: **zoom no rosto** (punch-in rápido mirando a altura do rosto), **som** (efeitos em `efeitos/`), **emoji** (figurinha que salta na tela) e **flash** (clarão de transição). No cut.pro isso aparece como recursos do template (`auto_zoom`, `emojis`, efeitos sonoros da biblioteca); aqui as regras por tipo de momento ficam visíveis e editáveis. A biblioteca de sons é organizada por categoria em `efeitos/<categoria>/<nome>.wav|mp3`, como a do cut.pro; os padrão (`transicao/whoosh`, `impacto/boom`, `cartoon/pop`, `interface/ding`, `comedia/ba-dum-tss`) são gerados pelo ffmpeg na primeira vez. Para usar os seus, crie uma pasta de categoria em `efeitos/` (nomes em minúsculas, números e hífen; arquivos soltos na raiz entram como "geral") e escolha no template. O zoom mira o rosto no instante do momento em qualquer enquadramento.
- **Lixeira (safe-delete):** excluir um corte ou um vídeo inteiro nunca apaga na hora: move para `lixeira/`, onde fica 30 dias (`RECUT_LIXEIRA_DIAS`) e pode ser restaurado. O vídeo vai com os cortes e com o arquivo enviado (se nenhum outro vídeo usar o mesmo upload). Cada ação (excluído, restaurado, apagado de vez, expirado) fica em `lixeira/registro.jsonl` com data, hora e o vídeo afetado, e aparece no histórico da aba Lixeira. Não dá para excluir um vídeo que ainda está processando.
- **Estratégias:** instruções em linguagem natural ("foque em dicas práticas de até 60s") salvas em `estrategias/<nome>.txt` e reutilizadas.
- **Enquadramento:** detecta o rosto a cada 0,5 s e move o recorte com suavização (mediana + zona morta + pan gradual).
- **Eventos:** webhook opcional recebe `live_started`, `live_clips` (a cada lote) e `live_ended`.

### IA sem API key

A análise usa a **sessão local de um agente CLI já logado** no computador, sem chave de API:

| Agente | Comando usado |
|---|---|
| Claude Code | `claude -p --output-format json --json-schema …` |
| Codex | `codex exec --output-schema … --sandbox read-only` |
| Gemini CLI | `gemini -p … --output-format json` |

Tenta na ordem acima (ou começa pelo de `RECUT_AGENTE`); se um falhar, tenta o próximo. É preciso ter pelo menos um instalado e logado.

## Esteira e publicação

A aba **Esteira** mostra o caminho de cada vídeo como nós ligados (estilo n8n): entrada, transcrição, análise, regra do lote, montagem, sua aprovação e publicação. O estado de cada nó é o **real**, lido do log do job (o nó que está rodando ganha a borda girando; erro e "aguardando você" aparecem no próprio nó). Cartões andam entre os nós, há um feed dos eventos e um resumo do dia.

- **Aprovação:** os cortes que chegam em "Sua aprovação" abrem um painel com nota, motivo, 3 legendas para escolher e hashtags. **Aprovar e postar** publica na hora no **YouTube Shorts** e no **Instagram Reels** e devolve os links. Cada plataforma tem seu estado em `<corte>.publicacao`.
- **TikTok é manual**, de propósito: apps da API do TikTok sem auditoria só postam em modo privado e exigem a conta inteira privada ([regras](https://developers.tiktok.com/doc/content-sharing-guidelines)). O painel entrega a legenda e o vídeo para você postar; QR code para o celular ainda não existe.
- **Estado "incerto":** se a resposta de uma plataforma se perde depois do envio (queda, timeout), o corte fica "incerto" porque o post pode ter saído. Nunca reenvia sozinho, para não duplicar; você confere na rede e cola o link ou manda tentar de novo.
- **Contas:** na aba **Contas** você conecta YouTube e Instagram (credenciais do app, conectar, reconectar, desconectar). Passo a passo em [docs/contas-passo-a-passo.md](docs/contas-passo-a-passo.md).
- **Segurança:** tokens e credenciais ficam só em `contas/` (no `.gitignore`) e a API nunca os devolve. O servidor só aceita `Host` 127.0.0.1/localhost e POST com JSON (o navegador de outro site não consegue disparar nada).

Desenho completo em `docs/superpowers/specs/2026-11-04-esteira-automatica-design.md`.

## Requisitos

- Python 3.12
- Node 20+ (para o frontend e para o yt-dlp resolver o desafio JS do YouTube)
- Um agente de IA logado: `claude`, `codex login` ou `gemini`

O ffmpeg vem pelo pacote `imageio-ffmpeg` (já com libass e libx264); `RECUT_FFMPEG` aponta para outro, se preferir.

## Instalação

```bash
python -m venv .venv
.venv\Scripts\activate            # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

cd frontend
npm install
npm run build
```

## Uso

### Interface web

```bash
python server.py                   # http://localhost:8000
```

Abas **Esteira** (veja acima), **Contas**, **Lixeira** (itens excluídos e histórico), **Cortar** (link, upload ou monitorar live, com a escolha do template), **Cortes** (grade ordenada pela nota, player, copiar descrição, baixar MP4, trocar o template do corte ou de todos do vídeo), **Templates** (galeria e editor com prévia animada) e **Estratégias**.

Para desenvolver o frontend com hot reload: `python server.py` em um terminal e `npm run dev` em `frontend/` (o Vite encaminha `/api` e `/files` para a porta 8000).

### Linha de comando

```bash
python recut.py video.mp4
python recut.py https://www.youtube.com/watch?v=...
python recut.py https://www.twitch.tv/canal --monitorar --dias 1,2,3,4,5 --horas 18,19,20,21,22,23 \
    --estrategia reacoes --limite-por-lote 3 --nota-min 7 --webhook https://meu.app/hook --template destaque

# trocar o template de cortes prontos (sem transcrever nem chamar a IA de novo)
python recut.py jobs/<id>/fonte_corte01.json jobs/<id>/fonte_corte02.json --reaplicar --template podcast
```

Saída: para cada corte, `.mp4` (1080×1920), `.jpg` (thumbnail), `.json` (nota, motivo, título, descrição, hashtags, tempos) e `.ass` (legenda). Em lives, `cortes/<canal>/<data-hora>/cortes.json` indexa a transmissão inteira.

### API

| Método | Rota | Descrição |
|---|---|---|
| `POST` | `/api/upload?nome=x.mp4` | corpo cru com o arquivo; devolve `{caminho}` |
| `POST` | `/api/jobs` | `{entrada, monitorar, estrategia, nota_min, limite, dur_min, dur_max, dias, horas, webhook}` |
| `GET` | `/api/jobs` · `/api/jobs/{id}` | status, cortes e log |
| `POST` | `/api/jobs/{id}/parar` | encerra o job |
| `GET`/`POST` | `/api/estrategias` | listar / salvar `{nome, texto}` |
| `GET`/`POST` | `/api/templates` | listar / salvar um template (validado; logo só vindo de upload) |
| `GET` | `/api/templates/opcoes` | proporções, enquadramentos, fontes, animações, tipos de momento, efeitos e o template padrão |
| `POST` | `/api/jobs/{id}/excluir` | move o vídeo inteiro para a lixeira |
| `POST` | `/api/jobs/{id}/cortes/excluir` | `{json}` move um corte para a lixeira |
| `GET` | `/api/lixeira` · `/api/lixeira/registro` | itens na lixeira / histórico com data e hora |
| `POST` | `/api/lixeira/{id}/restaurar` · `/api/lixeira/{id}/apagar` | restaura / apaga de vez |
| `GET` | `/api/efeitos/sons` | sons disponíveis em `efeitos/` (gera os padrão na primeira vez) |
| `POST` | `/api/jobs/{id}/aplicar_template` | `{template, cortes?}` renderiza de novo os cortes (todos, se `cortes` faltar) |
| `GET` | `/api/agentes` | agentes de IA disponíveis |
| `GET` | `/api/esteira/{id}` · `/api/esteira/resumo` | nós, cartões e feed de um job / resumo do dia |
| `POST` | `/api/jobs/{id}/cortes/aprovar` | `{json, legenda, hashtags}` aprova e posta no YouTube e Instagram |
| `POST` | `/api/jobs/{id}/cortes/publicacao` | `{json, plataforma, acao: tentar\|forcar\|link, link?}` tenta de novo, força o reenvio de um "incerto" ou registra o link colado (TikTok manual) |
| `GET` | `/api/contas` | contas sem segredos (só conectada ou não) |
| `POST` | `/api/contas/{youtube\|instagram}/configurar` · `conectar` · `codigo` · `desconectar` | credenciais do app, URL de autorização, código do Instagram, remover |
| `GET` | `/api/contas/youtube/retorno` | volta do OAuth do Google |
| `GET` | `/files/jobs/...` | vídeos e thumbnails (com suporte a Range) |

Cada job roda `recut.py` num subprocesso; a API só aceita arquivo local vindo de `/api/upload`.

## Testes

```bash
pip install pytest
python -m pytest test_recut.py test_lixeira.py test_esteira.py test_contas.py test_publicar.py test_server.py
```

Cobrem a lógica: legendas, recorte, regra do lote, horários, estratégias, escolha de agente, extração de JSON, tracking, lixeira, estado da Esteira, contas/OAuth, publicação e rotas do servidor.

## Limitações conhecidas

- Momentos que cruzam a borda entre dois lotes de 10 min podem se perder.
- O tracking segue o rosto, mas não remove sobreposições (ex.: tela compartilhada) quando a pessoa está na borda do quadro.
- Sem editor de cortes (trim, b-roll, elementos livres) nem publicação no TikTok (manual).
- Fontes dos templates: só as do sistema que o libass encontra (as do Windows na lista); uma fonte ausente vira Arial.
- Cortes gerados antes dos templates não guardam as palavras, então não dá para trocar o template deles; gere de novo.
- A prévia do editor é uma aproximação em CSS; o vídeo final é desenhado pelo ffmpeg/libass com as mesmas medidas.
- Emojis saem em uma cor só (o libass não desenha emoji colorido): viram figurinha amarela com contorno.
- Com zoom ativo o corte sai a 30 fps (o `zoompan` precisa de fps fixo).
- Sem memes/imagens de terceiros: os efeitos são zoom, flash, emoji e sons próprios.
- Corte só conteúdo sobre o qual você tem direitos.
