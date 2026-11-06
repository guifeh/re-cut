import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import { AlertTriangle, CheckCircle2, ChevronDown, Loader2 } from 'lucide-react'
import { api, type ContaOAuth, type ContaTelegram } from '@/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { NOME_PLATAFORMA } from '@/plataformas'

const erroToast = (e: unknown) => toast.error((e as Error).message)

// Resumo de docs/contas-passo-a-passo.md (a fonte); o guia completo fica nesse arquivo do repositório.
const PASSOS: Record<ContaOAuth['plataforma'], { id: string; segredo: string; passos: string[] }> = {
  youtube: {
    id: 'Client ID',
    segredo: 'Client secret',
    passos: [
      'Em console.cloud.google.com, crie um projeto "re-cut" e ligue a YouTube Data API v3 (APIs & Services > Library > Enable).',
      'Google Auth Platform > Branding: nome "re-cut", seu e-mail, público External. Em Audience, adicione seu e-mail em Test users.',
      'Em Audience, clique Publish app (em "Testing" a autorização vence em 7 dias). Uso pessoal não precisa de verificação.',
      'Clients > Create client > tipo Desktop app. Copie o Client ID e o Client secret e cole abaixo.',
      'Ao conectar, o Google avisa "app não verificado": Advanced > Go to re-cut (unsafe) > Continue. É seu app, é seguro.',
    ],
  },
  instagram: {
    id: 'Instagram app ID',
    segredo: 'Instagram app secret',
    passos: [
      'Precisa de conta profissional (Creator ou Business) e do site no GitHub Pages com a callback.html (seção 1 do guia).',
      'Em developers.facebook.com, crie o app (caso de uso "Manage messaging & content on Instagram") e abra "API setup with Instagram login".',
      'Confira as permissões instagram_business_basic e instagram_business_content_publish e adicione sua conta como testadora (Add account).',
      'Em Business login settings, cadastre o OAuth redirect URI https://guifeh.github.io/re-cut-site/callback.html e salve.',
      'Copie o Instagram app ID e o app secret desta mesma tela (não o App ID do topo do painel) e cole abaixo.',
      'Ao conectar, autorize no Instagram; a callback.html mostra um código: copie e cole em "Cole o código". Vale 1 hora, uso único.',
    ],
  },
}

export function Contas() {
  const [contas, setContas] = useState<(ContaOAuth | ContaTelegram)[] | null>(null)
  const carregar = () => api.contas().then(setContas).catch((e) => { setContas((c) => c ?? []); erroToast(e) })

  // recarga do poll do Telegram: silenciosa (com o servidor fora não vira um toast a cada 3 s) e de identidade estável
  const recarregar = useCallback(() => { api.contas().then(setContas).catch(() => {}) }, [])

  useEffect(() => {
    carregar()
    // volta do Google (/?aba=contas&erro=...): mostra o erro uma vez e limpa a URL
    const url = new URL(location.href)
    const erro = url.searchParams.get('erro')
    if (erro) {
      toast.error(erro)
      url.searchParams.delete('erro')
      history.replaceState(null, '', url)
    }
  }, [])

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">
        Ligue as contas uma vez; depois a Esteira posta sozinha. Os segredos ficam só na pasta <code>contas/</code> deste computador e nunca voltam para a tela.
        Guia completo: <code>docs/contas-passo-a-passo.md</code>.
      </p>
      <div className="grid items-start gap-4 lg:grid-cols-3">
        {contas === null && <p className="text-sm text-muted-foreground">Carregando…</p>}
        {contas?.map((c) => c.plataforma === 'telegram'
          ? <CartaoTelegram key={c.plataforma} conta={c} onMudou={carregar} onPoll={recarregar} />
          : <CartaoConta key={c.plataforma} conta={c} onMudou={carregar} />)}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">TikTok <Badge variant="outline">manual</Badge></CardTitle>
            <CardDescription>
              O TikTok só deixa apps aprovados postarem em público; aqui você posta pelo app e cola o link na Esteira.
            </CardDescription>
          </CardHeader>
        </Card>
      </div>
    </div>
  )
}

function CartaoConta({ conta: c, onMudou }: { conta: ContaOAuth; onMudou: () => void }) {
  const info = PASSOS[c.plataforma]
  const nome = NOME_PLATAFORMA[c.plataforma]
  const [id, setId] = useState('')
  const [segredo, setSegredo] = useState('')
  const [codigo, setCodigo] = useState('')
  const [urlLogin, setUrlLogin] = useState<string | null>(null) // Instagram: login aberto, esperando o código
  const [trocando, setTrocando] = useState(false)
  const [ocupado, setOcupado] = useState(false)

  async function agir(fn: () => Promise<void>) {
    setOcupado(true)
    try {
      await fn()
    } catch (e) {
      erroToast(e)
    } finally {
      setOcupado(false)
    }
  }

  const salvar = (e: React.FormEvent) => {
    e.preventDefault()
    return agir(async () => {
      await api.configurarConta(c.plataforma, id.trim(), segredo.trim())
      setId('')
      setSegredo('')
      setTrocando(false)
      toast.success(`${nome}: credenciais salvas`)
      onMudou()
    })
  }

  const conectar = () =>
    agir(async () => {
      const { url } = await api.conectarConta(c.plataforma)
      if (c.plataforma === 'youtube') {
        location.href = url // o Google volta por /api/contas/youtube/retorno
      } else {
        window.open(url, '_blank', 'noopener') // pode ser bloqueado (vem depois de um await): por isso o link guardado
        setUrlLogin(url)
      }
    })

  const enviarCodigo = (e: React.FormEvent) => {
    e.preventDefault()
    return agir(async () => {
      await api.codigoInstagram(codigo.trim())
      setCodigo('')
      setUrlLogin(null)
      toast.success('Instagram conectado')
      onMudou()
    })
  }

  const desconectar = () =>
    agir(async () => {
      await api.desconectarConta(c.plataforma)
      setUrlLogin(null)
      toast(`${nome} desconectado`, { description: 'As credenciais do app continuam salvas.' })
      onMudou()
    })

  const vencendo = c.conectada && c.dias_restantes !== null && c.dias_restantes < 10

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {nome}
          {c.conectada ? (
            <Badge variant="secondary" className="text-emerald-400"><CheckCircle2 className="size-3" /> Conectada</Badge>
          ) : (
            <Badge variant="outline">{c.configurada ? 'Configurada' : 'Não configurada'}</Badge>
          )}
        </CardTitle>
        {c.conectada && (c.nome || c.dias_restantes !== null) && (
          <CardDescription>
            {c.nome}
            {c.nome && c.dias_restantes !== null && ' · '}
            {c.dias_restantes !== null && `vence em ${c.dias_restantes} ${c.dias_restantes === 1 ? 'dia' : 'dias'}`}
          </CardDescription>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {vencendo && (
          <p role="alert" className="flex items-start gap-2 rounded-md bg-amber-500/15 p-2 text-sm text-amber-400">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" />
            Falta{c.dias_restantes === 1 ? '' : 'm'} {c.dias_restantes} {c.dias_restantes === 1 ? 'dia' : 'dias'} e a renovação automática não conseguiu renovar; reconecte.
          </p>
        )}

        {(!c.configurada || trocando) && (
          <form onSubmit={salvar} className="flex flex-col gap-3">
            <div className="flex flex-col gap-2">
              <Label htmlFor={`${c.plataforma}-id`}>{info.id}</Label>
              <Input id={`${c.plataforma}-id`} value={id} onChange={(e) => setId(e.target.value)} autoComplete="off" required />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor={`${c.plataforma}-segredo`}>{info.segredo}</Label>
              <Input id={`${c.plataforma}-segredo`} type="password" value={segredo} onChange={(e) => setSegredo(e.target.value)} autoComplete="new-password" required />
            </div>
            <Button type="submit" disabled={ocupado}>{ocupado && <Loader2 className="size-4 animate-spin" />} Salvar credenciais</Button>
            {trocando && <Button type="button" variant="ghost" onClick={() => { setTrocando(false); setId(''); setSegredo('') }}>Cancelar</Button>}
          </form>
        )}

        {c.configurada && !c.conectada && (
          <Button onClick={conectar} disabled={ocupado}>{ocupado && <Loader2 className="size-4 animate-spin" />} Conectar</Button>
        )}

        {urlLogin && c.plataforma === 'instagram' && (
          <form onSubmit={enviarCodigo} className="flex flex-col gap-2">
            <Label htmlFor="instagram-codigo">Cole o código</Label>
            <div className="flex gap-2">
              <Input id="instagram-codigo" value={codigo} onChange={(e) => setCodigo(e.target.value)} autoComplete="off" required />
              <Button type="submit" variant="outline" disabled={ocupado}>Enviar</Button>
            </div>
            <a href={urlLogin} target="_blank" rel="noopener noreferrer" className="text-xs text-muted-foreground underline">
              A aba não abriu? Abrir o login do Instagram
            </a>
          </form>
        )}

        {c.conectada && (
          <div className="flex gap-2">
            {/* YouTube: o refresh token pode ter sido revogado sem a tela saber; reconectar é o mesmo fluxo */}
            {(vencendo || c.plataforma === 'youtube') && <Button onClick={conectar} disabled={ocupado}>Reconectar</Button>}
            <Button variant="outline" onClick={desconectar} disabled={ocupado}>Desconectar</Button>
          </div>
        )}

        {c.configurada && !trocando && (
          <Button variant="ghost" size="sm" className="self-start text-muted-foreground" onClick={() => setTrocando(true)}>Trocar credenciais</Button>
        )}

        <details className="group text-sm">
          <summary className="flex cursor-pointer list-none items-center gap-1 text-muted-foreground hover:text-foreground">
            <ChevronDown className="size-4 transition-transform group-open:rotate-180" /> Como conseguir {info.id} e {info.segredo}
          </summary>
          <ol className="mt-2 flex list-decimal flex-col gap-1.5 pl-5 text-muted-foreground">
            {info.passos.map((p) => <li key={p}>{p}</li>)}
          </ol>
        </details>
      </CardContent>
    </Card>
  )
}

function CartaoTelegram({ conta: c, onMudou, onPoll }: { conta: ContaTelegram; onMudou: () => void; onPoll: () => void }) {
  const [token, setToken] = useState('')
  const [trocando, setTrocando] = useState(false)
  const [ocupado, setOcupado] = useState(false)
  const aguardando = c.configurada && !c.conectada

  // aguardando o toque em Começar no Telegram: recarrega até conectar
  useEffect(() => {
    if (!aguardando) return
    const t = setInterval(onPoll, 3000)
    return () => clearInterval(t)
  }, [aguardando, onPoll])

  async function agir(fn: () => Promise<void>) {
    setOcupado(true)
    try {
      await fn()
    } catch (e) {
      erroToast(e)
    } finally {
      setOcupado(false)
    }
  }

  const salvar = (e: React.FormEvent) => {
    e.preventDefault()
    return agir(async () => {
      await api.configurarTelegram(token.trim())
      setToken('')
      setTrocando(false)
      toast.success('Telegram: token salvo')
      onMudou()
    })
  }

  const desconectar = () =>
    agir(async () => {
      await api.desconectarTelegram()
      toast('Telegram desconectado')
      onMudou()
    })

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          Telegram <Badge variant="outline">opcional</Badge>
          {c.conectada ? (
            <Badge variant="secondary" className="text-emerald-400"><CheckCircle2 className="size-3" /> Conectado</Badge>
          ) : (
            <Badge variant="outline">{aguardando ? 'Aguardando' : 'Não configurado'}</Badge>
          )}
        </CardTitle>
        <CardDescription>
          {c.conectada
            ? `Conectado como ${c.nome ?? 'você'}${c.bot ? ` (@${c.bot})` : ''}`
            : 'O bot leva o vídeo e o texto de cada corte aprovado para o seu Telegram, para postar no TikTok pelo celular.'}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {(!c.configurada || trocando) && (
          <form onSubmit={salvar} className="flex flex-col gap-3">
            <div className="flex flex-col gap-2">
              <Label htmlFor="telegram-token">Token do bot</Label>
              <Input id="telegram-token" type="password" value={token} onChange={(e) => setToken(e.target.value)} autoComplete="new-password" required />
            </div>
            <Button type="submit" disabled={ocupado}>{ocupado && <Loader2 className="size-4 animate-spin" />} Salvar token</Button>
            {trocando && <Button type="button" variant="ghost" onClick={() => { setTrocando(false); setToken('') }}>Cancelar</Button>}
            <p className="text-xs text-muted-foreground">Sem token? Veja o passo a passo em <code>docs/contas-passo-a-passo.md</code>, seção 4 (Telegram).</p>
          </form>
        )}

        {aguardando && !trocando && c.link_pareamento && (
          <>
            <Button render={<a href={c.link_pareamento} target="_blank" rel="noopener noreferrer" />} nativeButton={false}>Abrir no Telegram</Button>
            <p className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="size-3 animate-spin" /> Toque em Começar no Telegram; esta tela atualiza sozinha.
            </p>
          </>
        )}

        {c.configurada && !trocando && (
          <div className="flex gap-2">
            {c.conectada && <Button variant="outline" onClick={desconectar} disabled={ocupado}>Desconectar</Button>}
            <Button variant="ghost" size="sm" className="text-muted-foreground" onClick={() => setTrocando(true)}>Trocar token</Button>
          </div>
        )}

        <details className="group text-sm">
          <summary className="flex cursor-pointer list-none items-center gap-1 text-muted-foreground hover:text-foreground">
            <ChevronDown className="size-4 transition-transform group-open:rotate-180" /> Como conseguir o token
          </summary>
          <ol className="mt-2 flex list-decimal flex-col gap-1.5 pl-5 text-muted-foreground">
            <li>No Telegram, abra o @BotFather e envie /newbot. Escolha um nome e um usuário (termina em bot).</li>
            <li>Copie o token que ele devolve (parece 123456:ABC...) e cole acima. Não compartilhe.</li>
            <li>Clique em Abrir no Telegram e toque em Começar.</li>
            <li>Aprove um corte, poste no TikTok pelo celular e responda à mensagem do corte com o link do post: o re-cut salva o link.</li>
          </ol>
          <p className="mt-2 text-xs text-muted-foreground">Vídeos acima de 50 MB não passam pelo bot (use Baixar no painel). Só cortes aprovados depois de conectar chegam. Guia: <code>docs/contas-passo-a-passo.md</code>, seção 4.</p>
        </details>
      </CardContent>
    </Card>
  )
}
