# Telegram: o corte aprovado chega no celular pronto para postar no TikTok

Data: 2026-11-06 · Status: rascunho para aprovação

## Por quê

O TikTok é manual no re-cut (a API não auditada só posta privado e exige a conta inteira privada; ver a spec da
esteira, `2026-11-04-esteira-automatica-design.md`). Hoje, para postar um corte aprovado, o usuário baixa o MP4 no
PC, manda para si mesmo pelo WhatsApp Web, baixa no celular, copia a legenda e as hashtags à mão, posta e depois
volta ao PC para colar o link no re-cut. É o pedaço mais trabalhoso do fluxo.

Com esta feature: **aprovou → o corte chega no Telegram do usuário** (vídeo + texto pronto para copiar). No celular
ele salva o vídeo, abre o TikTok, cola o texto e posta; depois **responde à mensagem do corte no Telegram com o link
do TikTok** e o re-cut salva o link sozinho.

## Objetivos

1. Na aprovação de um corte (o mesmo clique que posta no YouTube e no Instagram), o re-cut envia para o chat do
   usuário no Telegram, por um bot dele:
   - mensagem 1: o vídeo do corte (MP4), com legenda curta de identificação (título do corte e nota);
   - mensagem 2: o texto do post (`publicar.texto_final(legenda, hashtags)`, o mesmo que vai para o Instagram) num
     bloco que copia com um toque.
2. O usuário responde (reply) a qualquer uma das duas mensagens com o link do TikTok → o re-cut grava o link no
   corte como se tivesse sido colado na tela (`publicar.colar_link(corte, "tiktok", link)`) e o bot confirma.
3. O envio para o Telegram aparece no painel de aprovação como uma linha com estado (enviando / enviado / erro /
   incerto) e "tentar de novo", como as plataformas.
4. Card **Telegram** na aba Contas para ligar o bot uma vez, com passo a passo; seção no
   `docs/contas-passo-a-passo.md`.

## Fora desta versão

- Receber vídeos ou links **pelo** Telegram para cortar (o sentido é só re-cut → celular).
- WhatsApp (a AraraHQ é BSP pago da Meta; bibliotecas não oficiais tipo Baileys arriscam banir o número).
- Mandar para mais de um chat, grupos ou canais.
- Mandar cortes que não foram aprovados, ou reenviar cortes aprovados antes desta feature (dá para usar o
  "tentar de novo" só se o corte já tiver o registro do Telegram; ver Decisões).
- Servidor local da Bot API (para passar de 50 MB).

## Antiobjetivos

- Token do bot no git, no log, nas respostas da API ou no frontend.
- Outra pessoa conseguir ligar o bot ao chat dela ou gravar link em corte (o bot é de quem tem o código de pareamento).
- Telegram falhando atrapalhar ou repetir YouTube/Instagram.
- Mandar o mesmo corte duas vezes sem o usuário pedir.
- Link respondido no Telegram cair no corte errado.

## Restrições

- Tudo local, como o resto: servidor stdlib Python, sem endereço público. Por isso o bot recebe as respostas por
  **long polling** (`getUpdates`), nunca por webhook.
- Bot API oficial (`https://api.telegram.org/bot<token>/<método>`), grátis. Limites relevantes:
  - envio de arquivo por bot: **até 50 MB** (multipart);
  - texto de mensagem: até 4096 caracteres; legenda de mídia: até 1024 (por isso o texto vai em mensagem separada);
  - ~1 mensagem/s por chat; ao exceder, `429` com `parameters.retry_after` (segundos). 429 = não foi enviado.
- Chamadas com `contas.requisitar` (urllib), sem SDK, como YouTube/Instagram.
- O usuário cria o bot no @BotFather (dá o token). Ele não tem outro custo nem aprovação.

## Contratos

### Arquivo da conta: `contas/telegram.json` (fora do git)

```json
{"token": "123:ABC...", "bot": "meu_recut_bot", "chat_id": 123456789, "nome": "Guilherme",
 "pareamento": "k3J9xQ", "offset": 845120001}
```

- `token`: do BotFather. Nunca sai deste arquivo (nem em erro: substituir por `***` como `contas.SEGREDOS`).
- `bot`: `username` vindo de `getMe` ao salvar o token (valida o token).
- `pareamento`: código aleatório (`secrets.token_urlsafe(6)`) gerado ao salvar o token; some quando o chat é
  pareado. `chat_id` + `nome` (first_name) só são gravados quando chega `/start <pareamento>` exato.
- `offset`: último `update_id + 1` processado (persistido para não reprocessar após reiniciar).
- Trocar o token zera tudo (outro bot); "Desconectar" apaga o arquivo.

### Estado público da conta (`GET /api/contas` ganha um item)

```json
{"plataforma": "telegram", "configurada": true, "conectada": true, "nome": "Guilherme", "bot": "meu_recut_bot",
 "link_pareamento": null}
```

- `configurada` = tem token; `conectada` = tem `chat_id`.
- `link_pareamento` = `https://t.me/<bot>?start=<pareamento>` enquanto configurada e não conectada (o botão
  "Abrir no Telegram" usa esse link; o `/start` com o código vai sozinho). Não é segredo: só serve uma vez e
  some ao parear.

### Rotas

| Método e rota | Corpo | Faz |
|---|---|---|
| `POST /api/contas/telegram/configurar` | `{"token": "..."}` | `getMe`; grava token, bot, novo pareamento; devolve o estado público. Token inválido → 400 com mensagem sem o token. |
| `POST /api/contas/telegram/desconectar` | `{}` | apaga `contas/telegram.json`; devolve o estado público. |
| `POST /api/jobs/<job>/cortes/publicacao` | `{"json", "plataforma": "telegram", "acao": "tentar" \| "forcar"}` | reenvio, mesmas regras das plataformas (ok → recusa; incerto só com `forcar`). |

As demais rotas não mudam. `aprovar` passa a disparar também o Telegram quando a conta está conectada.

### `.publicacao` do corte (chave nova `telegram`, ao lado de `plataformas`)

```json
{"aprovado_em": "...", "legenda": "...", "hashtags": [...], "plataformas": {...},
 "telegram": {"estado": "ok", "erro": null, "em": "2026-11-06T10:20:00", "mensagens": [5012, 5013],
              "bot": "meu_recut_bot", "chat_id": 123456789}}
```

- Só existe se o Telegram estava conectado na hora da aprovação (conectar depois não envia os já aprovados).
- Estados: `enviando` → `ok` | `erro` | `incerto`, com as regras de `publicar` (estado gravado antes de cada envio;
  `enviando` órfão vira `incerto` em `ler_publicacao`; nunca reenviar sozinho).
- `mensagens`: `message_id` do vídeo e do texto, gravados assim que cada um volta. São a chave para achar o corte
  quando o usuário responde.
- `bot` + `chat_id`: a conversa por onde saiu (gravados ao marcar `enviando`). O Telegram numera mensagens por
  conversa, então depois de trocar de bot ou de chat os `message_id` se repetem: reply e "tentar de novo" só valem
  quando os dois batem com a conta atual. Corte enviado por um bot/chat antigo não aceita reply nem reenvio (a tela
  mostra "enviado por outro bot: cole o link aqui").
- Fica fora de `plataformas` de propósito: não é um destino de post, não vira nó da esteira nem conta em "posts".

### Envio (`publicar.enviar_telegram(corte_json, ...)`, numa thread como as plataformas)

1. `sendVideo` (multipart: `chat_id`, `video`, `caption` = `"<título> · nota <n>"`, `supports_streaming=true`).
2. `sendMessage` (`parse_mode=HTML`, texto em `<pre>`, com `&`, `<`, `>` escapados).
3. Arquivo > 50 MB: não tenta; `erro` = "o vídeo tem N MB e o Telegram aceita até 50 MB: use o Baixar".
4. `429`: espera `retry_after` e repete o mesmo passo (até 3 vezes; seguro porque 429 = não enviado).
5. Outro 4xx → `erro` com a `description` do Telegram. 5xx ou falha de rede depois de começar o upload de um passo
   → `incerto` ("confira no Telegram se chegou"). Passo 1 ok e passo 2 falhou: `mensagens` já tem o vídeo; o
   "tentar de novo" manda só o que falta.

### Respostas com link (thread `telegram.ouvir()` no servidor)

- Roda enquanto houver token; `getUpdates?timeout=50&offset=<offset>&allowed_updates=["message"]`; grava o offset
  depois de processar cada lote. Erro de rede: espera e tenta de novo (backoff até 60 s), sem derrubar o servidor.
- Para cada mensagem:
  - de chat ≠ `chat_id` (depois de pareado): ignora em silêncio;
  - `/start <pareamento>` com o código certo (antes de parear): grava `chat_id` e `nome`, responde
    "Pronto, os cortes aprovados vão chegar aqui";
  - reply (`reply_to_message.message_id`) a uma mensagem listada em `mensagens` de algum corte com o mesmo
    `bot` e `chat_id` da conta atual, com um link do
    TikTok no texto: `colar_link(corte, "tiktok", link)` → responde "✓ link salvo em <título>"; se `colar_link`
    recusar, responde com a mensagem do erro;
  - link do TikTok sem reply, ou reply a mensagem que não é de corte: responde "responda (arrastar para o lado) à
    mensagem do corte com o link";
  - qualquer outra coisa: ignora.
- Achar o corte pelo `message_id`: varrer os `.publicacao` dos jobs (são poucos). `ponytail:` deixar o comentário
  com o teto (índice em `contas/telegram.json` se ficar lento).

## Telas

- **Contas**: card Telegram. Sem token: campo do token + link para o passo a passo. Com token sem chat: "Abra o bot
  e toque em Começar" com botão para `link_pareamento`, atualizando sozinho quando parear. Conectado:
  "Conectado como <nome> (@bot)", Trocar token, Desconectar.
- **Painel de aprovação**: abaixo da linha do TikTok, uma linha "Telegram" com o estado, o erro e
  "tentar de novo"/"enviar mesmo assim" (incerto), igual às plataformas. Sem Telegram conectado, a linha não aparece.
  O toast da aprovação passa a dizer "o TikTok foi para o seu Telegram" quando for o caso.
- **Esteira**: sem nó novo. O feed ganha "Enviado ao Telegram" e "Telegram: <erro>".

## Decisões do usuário

- Telegram, não WhatsApp (grátis e oficial; Arara é paga e via Meta).
- Sentido: re-cut → celular, para facilitar a postagem manual no TikTok.
- Dispara na aprovação, junto com YouTube/Instagram, sem botão separado.
- Formato: vídeo numa mensagem, legenda + hashtags em outra, fácil de copiar.
- O link do TikTok volta respondendo à mensagem no próprio Telegram.

## Decisões minhas (o usuário pode trocar)

- Pareamento por código de uso único no `/start` (deep link), para ninguém mais ligar o bot ao próprio chat.
- Só um chat; mensagens de outros chats são ignoradas sem resposta.
- Texto em `<pre>` (toque copia tudo no Telegram).
- Telegram fora de `plataformas` no `.publicacao` e sem nó na esteira.
- Conectar o Telegram depois não reenvia cortes já aprovados.
- Registro do Telegram no corte amarrado ao bot e ao chat: trocar de bot/chat não deixa link cair em corte errado.
- 429 respeita `retry_after` e repete; demais falhas seguem a regra erro/incerto da esteira.

## Deixado para quem construir

- Onde mora o código: módulo novo `telegram.py` (conta, envio, escuta) ou divisão entre `contas.py`/`publicar.py`,
  desde que os contratos acima valham e `contas.PLATAFORMAS` (YouTube/Instagram, OAuth) não mude de sentido.
- Detalhes do multipart (stdlib) e do escape HTML.
- Texto exato das mensagens do bot e da tela.
- Testes: padrão do repo, com a Bot API simulada (sem rede), cobrindo pareamento, envio ok/erro/incerto/429/50 MB,
  reply com link (corte certo, corte desconhecido, chat estranho) e token fora de logs e respostas.
