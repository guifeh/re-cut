import { useCallback, useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { Clapperboard, Copy, Download, Film, Palette, Radio, Scissors, Sparkles, Square, Upload } from 'lucide-react'
import { api, jobDoCorte, parseHoras, upload, type Corte, type Estrategia, type Job, type Template } from '@/api'
import { PreviaTemplate, Templates } from '@/templates'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { FileUpload } from '@/components/ui/file-upload'
import { UiContentProvider } from '@/components/ui/file-upload-utils/content'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Toaster } from '@/components/ui/sonner'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'

const DIAS = ['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom']
const STATUS: Record<Job['status'], { texto: string; classe: string }> = {
  rodando: { texto: 'processando', classe: 'bg-primary/15 text-primary' },
  concluido: { texto: 'concluído', classe: 'bg-emerald-500/15 text-emerald-400' },
  erro: { texto: 'erro', classe: 'bg-destructive/15 text-destructive' },
  parado: { texto: 'parado', classe: 'bg-muted text-muted-foreground' },
  interrompido: { texto: 'interrompido', classe: 'bg-muted text-muted-foreground' },
}

const nomeEntrada = (e: string) => (e.startsWith('http') ? e.replace(/^https?:\/\/(www\.)?/, '') : e.split(/[\\/]/).pop()!.replace(/^[0-9a-f]{8}-/, ''))
const tempo = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`

export default function App() {
  const [jobs, setJobs] = useState<Job[] | null>(null)
  const [estrategias, setEstrategias] = useState<Estrategia[]>([])
  const [templates, setTemplates] = useState<Template[]>([])
  const [agentes, setAgentes] = useState<string[]>([])
  const [aba, setAba] = useState('cortar')
  const [aberto, setAberto] = useState<Corte | null>(null)

  const atualizar = useCallback(() => api.jobs().then(setJobs).catch(() => setJobs((j) => j ?? [])), [])
  useEffect(() => {
    atualizar()
    api.estrategias().then(setEstrategias).catch(() => {})
    api.templates().then(setTemplates).catch(() => {})
    api.agentes().then(setAgentes).catch(() => {})
    const t = setInterval(atualizar, 3000)
    return () => clearInterval(t)
  }, [atualizar])

  const cortes = useMemo(() => (jobs ?? []).flatMap((j) => j.cortes).sort((a, b) => b.nota - a.nota), [jobs])

  return (
    <UiContentProvider content={{ fileUpload: { dragPrompt: 'Arraste o vídeo aqui, ou', browse: 'escolha um arquivo', remove: 'Remover' } }}>
      <div className="min-h-svh bg-background text-foreground">
        <header className="border-b">
          <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-4">
            <div className="flex items-center gap-2">
              <div className="grid size-8 place-items-center rounded-md bg-primary text-primary-foreground">
                <Scissors className="size-4" />
              </div>
              <span className="text-lg font-semibold tracking-tight">re-cut</span>
              <span className="hidden text-sm text-muted-foreground sm:inline">cortes de live com IA</span>
            </div>
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Sparkles className="size-3.5" />
              {agentes.length ? (
                agentes.map((a, i) => (
                  <Badge key={a} variant={i === 0 ? 'default' : 'outline'}>{a}</Badge>
                ))
              ) : (
                <span className="text-destructive">nenhum agente de IA com sessão</span>
              )}
            </div>
          </div>
        </header>

        <main className="mx-auto max-w-6xl px-4 py-6">
          <Tabs value={aba} onValueChange={(v) => setAba(String(v))}>
            <TabsList>
              <TabsTrigger value="cortar">Cortar</TabsTrigger>
              <TabsTrigger value="cortes">Cortes {cortes.length > 0 && <Badge variant="secondary" className="ml-1">{cortes.length}</Badge>}</TabsTrigger>
              <TabsTrigger value="templates">Templates</TabsTrigger>
              <TabsTrigger value="estrategias">Estratégias</TabsTrigger>
            </TabsList>

            <TabsContent value="cortar" className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
              <NovoCorte estrategias={estrategias} templates={templates} onCriado={() => { atualizar(); }} />
              <ListaJobs jobs={jobs} onAtualizar={atualizar} onAbrir={setAberto} />
            </TabsContent>

            <TabsContent value="cortes" className="mt-6">
              <GradeCortes cortes={cortes} carregando={jobs === null} onAbrir={setAberto} />
            </TabsContent>

            <TabsContent value="templates" className="mt-6">
              <Templates templates={templates} onSalvo={(t) => setTemplates((l) => [...l.filter((x) => x.nome !== t.nome), t].sort((a, b) => a.nome.localeCompare(b.nome)))} />
            </TabsContent>

            <TabsContent value="estrategias" className="mt-6">
              <Estrategias estrategias={estrategias} onSalva={(e) => setEstrategias((l) => [...l.filter((x) => x.nome !== e.nome), e])} />
            </TabsContent>
          </Tabs>
        </main>

        <DialogCorte corte={aberto} templates={templates} onFechar={() => setAberto(null)} onAplicado={() => { setAberto(null); atualizar() }} />
        <Toaster richColors />
      </div>
    </UiContentProvider>
  )
}

function NovoCorte({ estrategias, templates, onCriado }: { estrategias: Estrategia[]; templates: Template[]; onCriado: () => void }) {
  const [modo, setModo] = useState<'video' | 'live'>('video')
  const [url, setUrl] = useState('')
  const [arquivos, setArquivos] = useState<File[]>([])
  const [estrategia, setEstrategia] = useState('__nenhuma')
  const [template, setTemplate] = useState('classico')
  const [textoLivre, setTextoLivre] = useState('')
  const [notaMin, setNotaMin] = useState(6)
  const [limite, setLimite] = useState(10)
  const [durMin, setDurMin] = useState(15)
  const [durMax, setDurMax] = useState(90)
  const [dias, setDias] = useState<number[]>([])
  const [horas, setHoras] = useState('')
  const [webhook, setWebhook] = useState('')
  const [enviando, setEnviando] = useState<number | null>(null)

  const itensEstrategia = [
    { value: '__nenhuma', label: 'Padrão (energia, reações, setup e payoff)' },
    ...estrategias.map((e) => ({ value: e.nome, label: e.nome })),
    { value: '__livre', label: 'Escrever agora…' },
  ]

  async function enviar(e: React.FormEvent) {
    e.preventDefault()
    try {
      let entrada = url.trim()
      if (modo === 'video' && arquivos[0]) {
        setEnviando(0)
        entrada = await upload(arquivos[0], setEnviando)
      }
      if (!entrada) throw new Error(modo === 'live' ? 'informe a URL do canal' : 'informe uma URL ou envie um vídeo')
      const job = await api.criarJob({
        entrada,
        monitorar: modo === 'live',
        estrategia: estrategia === '__livre' ? textoLivre : estrategia === '__nenhuma' ? '' : estrategia,
        template: templates.some((t) => t.nome === template) ? template : '',
        nota_min: notaMin,
        limite,
        dur_min: durMin,
        dur_max: durMax,
        ...(modo === 'live' && { dias, horas: parseHoras(horas), webhook }),
      })
      toast.success(modo === 'live' ? 'Monitoramento iniciado' : 'Processando o vídeo', { description: nomeEntrada(job.entrada) })
      setUrl('')
      setArquivos([])
      onCriado()
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setEnviando(null)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Novo corte</CardTitle>
        <CardDescription>A IA transcreve, acha os melhores momentos e entrega clipes 9:16 legendados.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={enviar} className="flex flex-col gap-5">
          <div className="grid grid-cols-2 gap-2 rounded-lg bg-muted p-1">
            {([['video', Film, 'Vídeo ou VOD'], ['live', Radio, 'Monitorar live']] as const).map(([v, Icone, texto]) => (
              <button
                key={v}
                type="button"
                onClick={() => setModo(v)}
                className={`flex items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors ${modo === v ? 'bg-background shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
              >
                <Icone className="size-4" /> {texto}
              </button>
            ))}
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="url">{modo === 'live' ? 'Canal (Twitch, Kick ou youtube.com/@canal/live)' : 'Link do vídeo (YouTube, Twitch, Kick…)'}</Label>
            <Input
              id="url"
              placeholder={modo === 'live' ? 'https://www.twitch.tv/seucanal' : 'https://www.youtube.com/watch?v=…'}
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              disabled={modo === 'video' && arquivos.length > 0}
            />
          </div>

          {modo === 'video' && (
            <>
              <div className="flex items-center gap-3 text-xs text-muted-foreground">
                <div className="h-px flex-1 bg-border" /> ou envie um arquivo <div className="h-px flex-1 bg-border" />
              </div>
              <FileUpload accept="video/*" files={arquivos} onFilesChange={setArquivos} disabled={enviando !== null} />
            </>
          )}

          <div className="flex flex-col gap-2">
            <Label>Estratégia de corte</Label>
            <Select items={itensEstrategia} value={estrategia} onValueChange={(v) => setEstrategia(String(v))}>
              <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                {itensEstrategia.map((i) => <SelectItem key={i.value} value={i.value}>{i.label}</SelectItem>)}
              </SelectContent>
            </Select>
            {estrategia === '__livre' && (
              <Textarea placeholder="Ex.: priorize humor e reações do chat; títulos curtos em caixa alta" value={textoLivre} onChange={(e) => setTextoLivre(e.target.value)} />
            )}
          </div>

          {templates.length > 0 && (
            <div className="flex flex-col gap-2">
              <Label>Template de edição</Label>
              <div className="flex gap-2 overflow-x-auto pb-1">
                {templates.map((t) => (
                  <button
                    key={t.nome}
                    type="button"
                    onClick={() => setTemplate(t.nome)}
                    className={`flex shrink-0 flex-col items-center gap-1 rounded-lg border-2 p-1.5 text-xs transition-colors ${template === t.nome ? 'border-primary' : 'border-transparent hover:border-border'}`}
                  >
                    <PreviaTemplate t={t} largura={64} />
                    <span className={template === t.nome ? 'font-medium text-foreground' : 'text-muted-foreground'}>{t.nome}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Campo label="Nota mínima" valor={notaMin} set={setNotaMin} min={0} max={10} step={0.5} />
            <Campo label={modo === 'live' ? 'Limite por lote' : 'Máx. de cortes'} valor={limite} set={setLimite} min={1} max={50} />
            <Campo label="Duração mín. (s)" valor={durMin} set={setDurMin} min={5} max={300} />
            <Campo label="Duração máx. (s)" valor={durMax} set={setDurMax} min={10} max={600} />
          </div>

          {modo === 'live' && (
            <div className="flex flex-col gap-4 rounded-lg border p-4">
              <p className="text-sm text-muted-foreground">
                Começa a clipar assim que o canal entrar ao vivo, em lotes de 10 minutos, sem esperar a live acabar.
              </p>
              <div className="flex flex-col gap-2">
                <Label>Dias (vazio = todos)</Label>
                <div className="flex flex-wrap gap-1.5">
                  {DIAS.map((d, i) => {
                    const ativo = dias.includes(i + 1)
                    return (
                      <button
                        key={d}
                        type="button"
                        onClick={() => setDias((l) => (ativo ? l.filter((x) => x !== i + 1) : [...l, i + 1]))}
                        className={`rounded-full border px-3 py-1 text-xs transition-colors ${ativo ? 'border-primary bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`}
                      >
                        {d}
                      </button>
                    )
                  })}
                </div>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="flex flex-col gap-2">
                  <Label htmlFor="horas">Horas (vazio = todas)</Label>
                  <Input id="horas" placeholder="18-23" value={horas} onChange={(e) => setHoras(e.target.value)} />
                </div>
                <div className="flex flex-col gap-2">
                  <Label htmlFor="webhook">Webhook (opcional)</Label>
                  <Input id="webhook" placeholder="https://meu.app/hook" value={webhook} onChange={(e) => setWebhook(e.target.value)} />
                </div>
              </div>
            </div>
          )}

          <Button type="submit" size="lg" disabled={enviando !== null}>
            {enviando !== null ? (
              <><Upload className="size-4 animate-pulse" /> Enviando {enviando}%</>
            ) : modo === 'live' ? (
              <><Radio className="size-4" /> Começar a monitorar</>
            ) : (
              <><Scissors className="size-4" /> Gerar cortes</>
            )}
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}

function Campo({ label, valor, set, min, max, step = 1 }: { label: string; valor: number; set: (n: number) => void; min: number; max: number; step?: number }) {
  return (
    <div className="flex flex-col gap-2">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      <Input type="number" inputMode="decimal" value={valor} min={min} max={max} step={step} onChange={(e) => set(Number(e.target.value))} />
    </div>
  )
}

function ListaJobs({ jobs, onAtualizar, onAbrir }: { jobs: Job[] | null; onAtualizar: () => void; onAbrir: (c: Corte) => void }) {
  const [detalhe, setDetalhe] = useState<Job | null>(null)

  async function parar(id: string) {
    await api.pararJob(id).then(() => toast('Job parado')).catch((e) => toast.error(e.message))
    onAtualizar()
  }

  async function abrirLog(id: string) {
    setDetalhe(await api.job(id))
  }

  return (
    <div className="flex flex-col gap-3">
      <h2 className="text-sm font-medium text-muted-foreground">Processamentos</h2>
      {jobs === null && [0, 1].map((i) => <Skeleton key={i} className="h-24 w-full" />)}
      {jobs?.length === 0 && (
        <div className="grid place-items-center gap-2 rounded-xl border border-dashed p-10 text-center text-sm text-muted-foreground">
          <Clapperboard className="size-6" />
          Nenhum vídeo ainda. Cole um link ou envie um arquivo para gerar os primeiros cortes.
        </div>
      )}
      {jobs?.map((j) => {
        const ultimo = Array.isArray(j.log) ? j.log.at(-1) : ''
        return (
          <Card key={j.id} size="sm">
            <CardContent className="flex flex-col gap-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    {j.monitorar ? <Radio className="size-4 shrink-0 text-primary" /> : <Film className="size-4 shrink-0 text-muted-foreground" />}
                    <span className="truncate font-medium">{nomeEntrada(j.entrada)}</span>
                  </div>
                  <p className="mt-1 truncate font-mono text-xs text-muted-foreground">{ultimo || '—'}</p>
                </div>
                <span className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${STATUS[j.status].classe}`}>
                  {j.status === 'rodando' && <span className="size-1.5 animate-pulse rounded-full bg-current" />}
                  {STATUS[j.status].texto}
                </span>
              </div>
              {j.cortes.length > 0 && (
                <div className="flex gap-2 overflow-x-auto pb-1">
                  {j.cortes.slice(0, 6).map((c) => (
                    <button key={c.video_url} onClick={() => onAbrir(c)} className="relative w-16 shrink-0 overflow-hidden rounded-md border" title={c.titulo}>
                      <img src={c.thumb_url} alt={c.titulo} className="aspect-[9/16] w-full object-cover" loading="lazy" />
                      <span className="absolute bottom-0.5 right-0.5 rounded bg-black/70 px-1 text-[10px] font-semibold text-white">{c.nota.toFixed(1)}</span>
                    </button>
                  ))}
                </div>
              )}
              <div className="flex gap-2">
                <Button variant="ghost" size="sm" onClick={() => abrirLog(j.id)}>Ver log</Button>
                {j.status === 'rodando' && (
                  <Button variant="outline" size="sm" onClick={() => parar(j.id)}><Square className="size-3" /> Parar</Button>
                )}
              </div>
            </CardContent>
          </Card>
        )
      })}

      <Dialog open={detalhe !== null} onOpenChange={(o) => !o && setDetalhe(null)}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{detalhe && nomeEntrada(detalhe.entrada)}</DialogTitle>
            <DialogDescription>{detalhe?.id}</DialogDescription>
          </DialogHeader>
          <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap rounded-md bg-muted p-3 font-mono text-xs">{typeof detalhe?.log === 'string' ? detalhe.log || '(sem saída ainda)' : ''}</pre>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function GradeCortes({ cortes, carregando, onAbrir }: { cortes: Corte[]; carregando: boolean; onAbrir: (c: Corte) => void }) {
  if (carregando) return <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">{[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="aspect-[9/16]" />)}</div>
  if (!cortes.length)
    return <p className="rounded-xl border border-dashed p-10 text-center text-sm text-muted-foreground">Os cortes aparecem aqui, ordenados pela nota viral.</p>
  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
      {cortes.map((c) => (
        <button key={c.video_url} onClick={() => onAbrir(c)} className="group flex flex-col gap-2 text-left">
          <div className="relative overflow-hidden rounded-xl border bg-muted">
            <img src={c.thumb_url} alt={c.titulo} className="aspect-[9/16] w-full object-cover transition-transform duration-300 group-hover:scale-[1.03]" loading="lazy" />
            <span className={`absolute left-2 top-2 rounded-md px-1.5 py-0.5 text-xs font-bold ${c.nota >= 8 ? 'bg-primary text-primary-foreground' : 'bg-black/70 text-white'}`}>{c.nota.toFixed(1)}</span>
            <span className="absolute bottom-2 right-2 rounded bg-black/70 px-1.5 py-0.5 text-[11px] text-white">{tempo(c.duracao)}</span>
          </div>
          <span className="line-clamp-2 text-sm font-medium leading-snug">{c.titulo}</span>
        </button>
      ))}
    </div>
  )
}

function DialogCorte({ corte, templates, onFechar, onAplicado }: {
  corte: Corte | null
  templates: Template[]
  onFechar: () => void
  onAplicado: () => void
}) {
  const [novo, setNovo] = useState('')
  const [aplicando, setAplicando] = useState(false)
  async function aplicar(todos: boolean) {
    if (!corte || !novo) return
    setAplicando(true)
    try {
      await api.aplicarTemplate(jobDoCorte(corte), novo, todos ? undefined : [corte.json])
      toast.success(`Aplicando "${novo}"`, { description: todos ? 'Todos os cortes deste vídeo serão renderizados de novo.' : 'O corte é renderizado de novo em alguns segundos.' })
      onAplicado()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setAplicando(false)
    }
  }
  const legenda = corte ? `${corte.descricao}\n\n${corte.hashtags.map((h) => (h.startsWith('#') ? h : `#${h}`)).join(' ')}` : ''
  return (
    <Dialog open={corte !== null} onOpenChange={(o) => !o && onFechar()}>
      <DialogContent className="sm:max-w-3xl">
        {corte && (
          <div className="grid gap-5 sm:grid-cols-[240px_1fr]">
            <video src={corte.video_url} poster={corte.thumb_url} controls autoPlay className="aspect-[9/16] w-full rounded-lg bg-black" />
            <div className="flex min-w-0 flex-col gap-4">
              <DialogHeader>
                <DialogTitle className="text-lg leading-snug">{corte.titulo}</DialogTitle>
                <DialogDescription>
                  {tempo(corte.inicio)}–{tempo(corte.fim)} do {corte.lote} · {tempo(corte.duracao)}
                </DialogDescription>
              </DialogHeader>
              <div className="flex items-baseline gap-2">
                <span className="text-3xl font-bold text-primary">{corte.nota.toFixed(1)}</span>
                <span className="text-sm text-muted-foreground">/ 10 nota viral</span>
              </div>
              <p className="text-sm text-muted-foreground">{corte.motivo}</p>
              <div className="flex flex-col gap-2">
                <Label className="text-xs text-muted-foreground">Descrição do post</Label>
                <p className="whitespace-pre-wrap rounded-md bg-muted p-3 text-sm">{legenda}</p>
              </div>
              <div className="mt-auto flex flex-wrap gap-2">
                <Button variant="outline" onClick={() => navigator.clipboard.writeText(legenda).then(() => toast.success('Descrição copiada'))}>
                  <Copy className="size-4" /> Copiar descrição
                </Button>
                <Button render={<a href={corte.video_url} download />}>
                  <Download className="size-4" /> Baixar MP4
                </Button>
              </div>
              <div className="flex flex-col gap-2 rounded-lg border p-3">
                <Label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Palette className="size-3.5" /> Template {corte.template ? <Badge variant="secondary">{corte.template}</Badge> : null}
                </Label>
                {corte.reaplicavel ? (
                  <div className="flex flex-wrap gap-2">
                    <Select items={templates.map((t) => ({ value: t.nome, label: t.nome }))} value={novo} onValueChange={(v) => setNovo(String(v))}>
                      <SelectTrigger className="min-w-36 flex-1"><SelectValue placeholder="Trocar para…" /></SelectTrigger>
                      <SelectContent>{templates.map((t) => <SelectItem key={t.nome} value={t.nome}>{t.nome}</SelectItem>)}</SelectContent>
                    </Select>
                    <Button variant="outline" disabled={!novo || aplicando} onClick={() => aplicar(false)}>Aplicar</Button>
                    <Button variant="ghost" disabled={!novo || aplicando} onClick={() => aplicar(true)}>Em todos do vídeo</Button>
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground">Corte gerado antes dos templates: gere de novo para poder trocar o template.</p>
                )}
              </div>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

function Estrategias({ estrategias, onSalva }: { estrategias: Estrategia[]; onSalva: (e: Estrategia) => void }) {
  const [nome, setNome] = useState('')
  const [texto, setTexto] = useState('')

  async function salvar(e: React.FormEvent) {
    e.preventDefault()
    try {
      onSalva(await api.salvarEstrategia({ nome, texto }))
      toast.success('Estratégia salva')
      setNome('')
      setTexto('')
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>Nova estratégia</CardTitle>
          <CardDescription>Diz à IA o que procurar no vídeo e como escrever os títulos. Salve uma vez e reutilize.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={salvar} className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="nome-estrategia">Nome</Label>
              <Input id="nome-estrategia" placeholder="dicas-praticas" value={nome} onChange={(e) => setNome(e.target.value)} required />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="texto-estrategia">Instrução</Label>
              <Textarea id="texto-estrategia" rows={5} placeholder="Foque em dicas práticas de até 60 segundos; títulos em forma de pergunta." value={texto} onChange={(e) => setTexto(e.target.value)} required />
            </div>
            <Button type="submit">Salvar estratégia</Button>
          </form>
        </CardContent>
      </Card>
      <div className="flex flex-col gap-3">
        {estrategias.map((e) => (
          <Card key={e.nome} size="sm">
            <CardHeader>
              <CardTitle className="font-mono text-sm">{e.nome}</CardTitle>
              <CardDescription>{e.texto}</CardDescription>
            </CardHeader>
          </Card>
        ))}
      </div>
    </div>
  )
}
