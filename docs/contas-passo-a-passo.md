# Contas: passo a passo para ligar YouTube e Instagram ao re-cut

Guia escrito em 2026-11-04. As telas das plataformas mudam com frequência: onde algo não pôde ser confirmado na
documentação oficial está marcado **(confirmar na tela)**. Os nomes de botões estão como aparecem nos consoles (em
inglês, que é como eles aparecem para a maioria das contas).

## Por que precisa disso

YouTube e Instagram só deixam postar por programa quem tem um "app de desenvolvedor" registrado com eles. O
cut.pro faz exatamente isso como empresa (os clientes usam os apps dele); aqui você registra os seus, um por
plataforma, só para as suas próprias contas. É grátis e feito uma vez só.

| Plataforma | Tempo estimado | Precisa de revisão? | Resultado |
|---|---|---|---|
| Instagram | 20–30 min (+ 10 min do site no GitHub Pages) | Não (Standard Access basta para a sua conta) | Reels público, link em 1–5 min |
| YouTube | 15–20 min | Não (aparece aviso "app não verificado", normal) | Short público, link na hora |

**TikTok fica manual, sem app** (decisão de 2026-11-04): app não auditado do TikTok só posta em privado e exige a
conta inteira privada na hora do envio ("All user accounts using the API client to post must be set to private at
the time of posting" — https://developers.tiktok.com/doc/content-sharing-guidelines), e a revisão recusa ferramenta
para postar nas próprias contas. No TikTok, o re-cut entrega o vídeo (QR code para o celular) e a legenda pronta
para copiar; você posta no app e cola o link de volta.

**Ordem recomendada:** 1) site no GitHub Pages (só para o login do Instagram), 2) Instagram, 3) YouTube.

**Regra de ouro:** tudo que você copiar (client id, secret, tokens) vai ser colado na futura tela **Contas** do
re-cut, que guarda em `contas/` (pasta fora do git). Nunca cole esses valores em commit, issue, chat ou print.

---

## 1. Site no GitHub Pages (para o login do Instagram)

O Instagram exige um endereço **HTTPS** para devolver o login. Um site estático grátis no GitHub resolve. O repositório do re-cut
continua privado; este é um repositório **separado e público**, só com estes 2 arquivos.

1. Entre em https://github.com com o usuário `guifeh` e clique em **New** (novo repositório).
2. **Repository name**: `re-cut-site`. Marque **Public**. Clique em **Create repository**.
3. Clique em **Add file** → **Create new file** e crie cada arquivo abaixo (nome + conteúdo), clicando em
   **Commit changes** a cada um.
4. Vá em **Settings** → **Pages** (na lateral). Em **Build and deployment** → **Source**, escolha
   **Deploy from a branch**; em **Branch** escolha `main` e a pasta `/ (root)`; clique em **Save**.
5. Espere 1–2 minutos e abra `https://guifeh.github.io/re-cut-site/`. Deve aparecer a página inicial.

Endereços que você vai usar depois:

- Site: `https://guifeh.github.io/re-cut-site/`
- Retorno do login (Instagram): `https://guifeh.github.io/re-cut-site/callback.html`

### `index.html`

```html
<!doctype html><meta charset="utf-8"><title>re-cut</title>
<h1>re-cut</h1>
<p>Ferramenta pessoal, de um único usuário, que publica os próprios vídeos curtos do dono nas contas dele
(YouTube, Instagram). / Personal single-user tool that publishes the owner's own short videos to the
owner's own accounts.</p>
```

### `callback.html`

Página que só mostra o código do login para você copiar e colar de volta no re-cut (o Instagram não devolve para
`localhost`; veja a seção 2).

```html
<!doctype html><meta charset="utf-8"><title>re-cut - código</title>
<h1>Copie o código abaixo e cole na tela Contas do re-cut</h1>
<textarea id="c" rows="4" cols="80" readonly></textarea>
<p id="e" style="color:red"></p>
<script>
  const p = new URLSearchParams(location.search);
  document.getElementById('c').value = (p.get('code') || '').replace(/#_$/, '');
  if (p.get('error')) document.getElementById('e').textContent = p.get('error') + ': ' + (p.get('error_description') || '');
</script>
```

Este site não recebe nem guarda nada: o código aparece só no seu navegador, vale 1 hora e só pode ser usado uma vez.

Fontes: https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site

---

## 2. Instagram

Não precisa de revisão da Meta: segundo a documentação, "se o seu app só atende a sua conta profissional do
Instagram ou uma conta que você gerencia, Standard Access é tudo que precisa". O app fica em **Development mode** e
funciona para quem tem papel nele (você).

**Diferença do plano:** a Meta só aceita endereço de retorno **HTTPS** (não aceita `http://localhost`). Por isso o
retorno vai para a página `callback.html` do seu site no GitHub Pages, que mostra um código para você copiar e colar
no re-cut. (Isto vem de guias de terceiros e da comunidade; a doc oficial só diz que precisa bater exatamente com o
cadastrado — se o painel aceitar `http://localhost`, melhor ainda **(confirmar na tela)**.)

### Passo a passo

1. **Conta profissional.** No app do Instagram: seu perfil → menu ☰ → **Settings and activity** (Configurações e
   atividade) → **Account type and tools** (Tipo de conta e ferramentas) → **Switch to professional account**
   (Mudar para conta profissional) → escolha **Creator** (Criador de conteúdo) ou **Business** (Empresa)
   **(confirmar na tela)**. Grátis e reversível.
2. Abra https://developers.facebook.com, entre com sua conta do Facebook/Meta e, se pedir, registre-se como
   desenvolvedor (**Get Started**).
3. Clique em **My Apps** → **Create App**.
   - **App details**: nome (`re-cut`) e e-mail de contato → **Next**.
   - **Use cases**: escolha **Manage messaging & content on Instagram** (pode aparecer em português como
     "Gerenciar mensagens e conteúdo no Instagram"). Essa escolha não pode ser desfeita. Se essa opção não aparecer,
     escolha **Other** → tipo **Business** **(confirmar na tela)**.
   - **Business**: se pedir um portfólio empresarial, pode pular ("I don't want to connect a business portfolio
     yet") — ele só é exigido para publicar o app em modo Live, que você não vai fazer **(confirmar na tela)**.
   - Finalize com **Create app** (pode pedir sua senha).
4. No painel do app, abra o caso de uso do Instagram (**Use cases** → **Customize** ao lado de "Manage messaging &
   content on Instagram") → **API setup with Instagram login** (Configuração da API com login do Instagram).
5. Em **Permissions**, confira que estão incluídas **instagram_business_basic** e
   **instagram_business_content_publish** (as outras que vêm por padrão podem ficar, o re-cut só pede essas duas).
6. **Adicionar sua conta como testadora.** No passo **Generate access tokens**, clique em **Add account** e entre
   com a sua conta do Instagram **(confirmar na tela)**. Se em vez disso o painel pedir convite: vá em
   **App roles** → **Roles** → **Add People** → **Instagram Tester** → digite seu @ do Instagram. Depois aceite
   o convite no Instagram: pelo navegador em https://www.instagram.com/accounts/manage_access/ → aba
   **Tester Invites** → **Accept**; ou no app: **Settings and activity** → **Website permissions** →
   **Apps and websites** → **Tester invites** **(confirmar na tela)**.
7. **Endereço de retorno.** Ainda em **API setup with Instagram login**, no passo **Set up Instagram business login**
   → **Business login settings**:
   - **OAuth redirect URIs**: `https://guifeh.github.io/re-cut-site/callback.html` → **Save**. A Meta às vezes
     acrescenta uma `/` no final sozinha; o re-cut tem que usar exatamente o que ficou salvo.
   - Se pedir **Deauthorize callback URL** / **Data deletion request URL**, pode usar
     `https://guifeh.github.io/re-cut-site/privacidade.html` **(confirmar na tela)**.
8. Na mesma tela, copie o **Instagram app ID** e o **Instagram app secret** (clique em **Show**). Atenção: são os do
   Instagram, mostrados nesta tela — **não** o "App ID" do topo do painel da Meta.
9. Como vai funcionar a conexão: o re-cut abre a página de login do Instagram, você autoriza, cai na
   `callback.html` com um código, copia e cola no re-cut. O código vale **1 hora** e serve uma vez só.

**Token:** o re-cut troca o código por um token de **60 dias** e o renova sozinho antes de vencer (a renovação só é
possível com o token tendo pelo menos 24 h e ainda válido). Se o re-cut ficar mais de 60 dias sem rodar, é só
conectar de novo.

**Plano B (sem callback):** a tela **Generate access tokens** tem um botão **Generate token** ao lado da conta
adicionada, que entrega um token direto **(confirmar na tela)** — dá para colar esse token no re-cut.

Limites: 100 posts por 24 h; legenda até 2200 caracteres e até 30 hashtags.

### O que copiar para o re-cut

- **Instagram app ID** e **Instagram app secret** (da tela "API setup with Instagram login").
- O **OAuth redirect URI** exatamente como ficou salvo.

Colar na tela **Contas** (guardado em `contas/`, fora do git). Nunca compartilhe o secret nem o token.

Fontes:
https://developers.facebook.com/docs/instagram-platform/overview ·
https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/create-a-meta-app-with-instagram ·
https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/business-login ·
https://developers.facebook.com/docs/instagram-platform/content-publishing ·
(terceiros, sobre HTTPS e nome do caso de uso) https://docs.unified.to/skills/instagram-oauth-app/SKILL.md

---

## 3. YouTube (Google Cloud)

Boa notícia de 2026-11-02: vídeos enviados por projetos **não verificados** não ficam mais presos em privado
(revision history da YouTube Data API). Ou seja, o Short sai público sem auditoria.

### Passo a passo

1. Abra https://console.cloud.google.com com a conta Google do seu canal. Aceite os termos se pedir.
2. **Criar projeto:** no seletor de projetos (topo) → **New project** → nome `re-cut` → **Create**. Confira que o
   projeto novo está selecionado no topo.
3. **Ligar a API:** menu ☰ → **APIs & Services** → **Library** → busque **YouTube Data API v3** → abra → **Enable**.
4. **Tela de consentimento:** menu ☰ → **Google Auth Platform** → **Branding** (ou **Overview**). Se aparecer
   **Get started**, clique:
   - **App information**: **App name** `re-cut`, **User support email** = seu e-mail → **Next**.
   - **Audience**: **External** → **Next**.
   - **Contact information**: seu e-mail → **Next**.
   - Marque **I agree to the Google API Services: User Data Policy** → **Continue** → **Create**.
5. **Você como usuário de teste:** **Google Auth Platform** → **Audience** → em **Test users** clique
   **Add users**, coloque seu e-mail → **Save**. (Só importa enquanto o app estiver em teste.)
6. **Escopo (opcional, ajuda a conferir):** **Google Auth Platform** → **Data Access** → **Add or remove scopes** →
   marque `https://www.googleapis.com/auth/youtube.upload` (cole na caixa "Manually add scopes" se não achar) →
   **Update** → **Save**.
7. **Colocar em produção (importante):** **Google Auth Platform** → **Audience** → em **Publishing status**
   clique **Publish app** → **Confirm**. Motivo: em "Testing" o Google faz a autorização **vencer em 7 dias** e
   você teria que reconectar toda semana. Em "In production" ela não vence assim.
   - `youtube.upload` é um escopo "sensível". O Google diz que app de **uso pessoal (menos de 100 usuários)** pode
     ser usado **sem verificação**. Se ao publicar aparecer um aviso sobre verificação, você **não** precisa
     enviar para verificação — só confirme a publicação **(confirmar na tela se o botão deixa publicar direto)**.
8. **Criar o cliente OAuth:** **Google Auth Platform** → **Clients** → **Create client** → **Application type**:
   **Desktop app** → nome `re-cut` → **Create**. Aparece o **Client ID** e o **Client secret**; copie (ou
   **Download JSON**). Não precisa cadastrar endereço de retorno: app Desktop aceita `http://127.0.0.1:<porta>`
   em qualquer porta, sem registrar.

### A tela de aviso que você vai ver (normal)

Ao conectar pela primeira vez, o Google mostra **"Google hasn't verified this app"** (O Google não verificou este
app). Como o app é seu e só você usa, é seguro: clique em **Advanced** (Avançado) → **Go to re-cut (unsafe)** (Ir
para re-cut (não seguro)) → marque a permissão de enviar vídeos → **Continue**. O limite de 100 usuários de app não
verificado não importa: só você usa.

Cota: cada envio gasta pouco da cota diária gratuita; para um usuário é folgado.

### O que copiar para o re-cut

- **Client ID** e **Client secret** (do cliente "Desktop app"), ou o JSON baixado.

Colar na tela **Contas** (guardado em `contas/`, fora do git). Nunca commite o JSON baixado: apague-o da pasta
Downloads depois de colar.

Fontes:
https://developers.google.com/youtube/v3/revision_history ·
https://developers.google.com/identity/protocols/oauth2 (refresh token de 7 dias em "Testing") ·
https://developers.google.com/identity/protocols/oauth2/native-app (cliente Desktop e loopback) ·
https://developers.google.com/workspace/guides/configure-oauth-consent (menus do Google Auth Platform) ·
https://support.google.com/cloud/answer/15549945 (Publish app, aviso de app não verificado, limite de 100) ·
https://support.google.com/cloud/answer/13464323 (uso pessoal dispensa verificação)

---

## Conferência final

- [ ] Site `https://guifeh.github.io/re-cut-site/` abre, e o `callback.html` também.
- [ ] Instagram: conta profissional, conta adicionada no app, redirect HTTPS salvo, app ID/secret do Instagram anotados.
- [ ] YouTube: API ligada, app em **In production**, cliente Desktop criado, ID/secret anotados.
- [ ] Nada disso foi salvo dentro do repositório do re-cut, só na tela Contas (`contas/`).
