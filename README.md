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

Abas **Cortar** (link, upload ou monitorar live), **Cortes** (grade ordenada pela nota, player, copiar descrição, baixar MP4) e **Estratégias**.

Para desenvolver o frontend com hot reload: `python server.py` em um terminal e `npm run dev` em `frontend/` (o Vite encaminha `/api` e `/files` para a porta 8000).

### Linha de comando

```bash
python recut.py video.mp4
python recut.py https://www.youtube.com/watch?v=...
python recut.py https://www.twitch.tv/canal --monitorar --dias 1,2,3,4,5 --horas 18,19,20,21,22,23 \
    --estrategia reacoes --limite-por-lote 3 --nota-min 7 --webhook https://meu.app/hook
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
| `GET` | `/api/agentes` | agentes de IA disponíveis |
| `GET` | `/files/jobs/...` | vídeos e thumbnails (com suporte a Range) |

Cada job roda `recut.py` num subprocesso; a API só aceita arquivo local vindo de `/api/upload`.

## Testes

```bash
pip install pytest
python -m pytest test_recut.py
```

Cobrem as partes de lógica: legendas, recorte, regra do lote, horários, estratégias, escolha de agente, extração de JSON e suavização do tracking.

## Limitações conhecidas

- Momentos que cruzam a borda entre dois lotes de 10 min podem se perder.
- O tracking segue o rosto, mas não remove sobreposições (ex.: tela compartilhada) quando a pessoa está na borda do quadro.
- Um estilo de legenda só; sem editor de cortes nem publicação automática nas redes.
- Corte só conteúdo sobre o qual você tem direitos.
