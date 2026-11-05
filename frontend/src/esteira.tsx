import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import {
  Background, BackgroundVariant, BaseEdge, EdgeLabelRenderer, Handle, Position, ReactFlow, getBezierPath,
  type Edge, type EdgeProps, type Node, type NodeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import {
  AudioLines, Camera, Check, Clapperboard, Download, Inbox, MonitorPlay, RotateCcw, Smartphone, Sparkles, Trophy, UserCheck, WifiOff, X,
  type LucideIcon,
} from 'lucide-react'
import { api, nomeEntrada, type Corte, type Esteira as DadosEsteira, type EstadoNo, type IdNo, type Job, type NoEsteira, type Plataforma, type ResumoDoDia } from '@/api'
import { PainelAprovacao } from '@/aprovacao'
import { COR_PUBLICACAO, NOME_PLATAFORMA, PLATAFORMAS } from '@/plataformas'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'

const ETAPAS: IdNo[] = ['entrada', 'baixar', 'transcrever', 'ia', 'renderizar', 'ranking', 'aprovacao']
const NO: Record<IdNo, { rotulo: string; Icone: LucideIcon }> = {
  entrada: { rotulo: 'Entrada', Icone: Inbox },
  baixar: { rotulo: 'Baixar', Icone: Download },
  transcrever: { rotulo: 'Transcrever', Icone: AudioLines },
  ia: { rotulo: 'IA escolhe momentos', Icone: Sparkles },
  renderizar: { rotulo: 'Renderizar', Icone: Clapperboard },
  ranking: { rotulo: 'Ranking + legendas', Icone: Trophy },
  aprovacao: { rotulo: 'Sua aprovação', Icone: UserCheck },
  youtube: { rotulo: `${NOME_PLATAFORMA.youtube} Shorts`, Icone: MonitorPlay },
  instagram: { rotulo: `${NOME_PLATAFORMA.instagram} Reels`, Icone: Camera },
  tiktok: { rotulo: NOME_PLATAFORMA.tiktok, Icone: Smartphone },
}
// 'sem-sinal': o nó estava rodando mas o servidor não responde; não anima um processo que pode ter parado
type EstadoVisto = EstadoNo | 'sem-sinal'
const ESTADO: Record<EstadoVisto, string> = { ocioso: 'parado', rodando: 'rodando', ok: 'concluído', erro: 'erro', esperando: 'esperando você', 'sem-sinal': 'sem notícia do servidor' }
const BORDA: Record<EstadoVisto, string> = {
  'sem-sinal': 'border-[1.5px] border-dashed border-foreground/40',
  ocioso: 'border-[1.5px] border-foreground/25',
  rodando: 'border-[1.5px] border-transparent',
  ok: 'border-2 border-emerald-500',
  erro: 'border-2 border-destructive',
  esperando: 'border-2 border-orange-400',
}
const CORAL = '#ff6d5a'
const PASSO = 176 // distância entre os nós da linha
const MAX_CARTOES = 3 // por nó; o resto vira um cartão "+N"
// o tema do app é fixo (class="dark" no index.html, sem ThemeProvider: o useTheme do next-themes não saberia)
const ESCURO = document.documentElement.classList.contains('dark')
const temProperty = typeof CSS !== 'undefined' && 'registerProperty' in CSS

type DadosNo = { no: IdNo; estado: EstadoVisto; progresso: number | null; msg: string }
type DadosCartao = { no: IdNo; texto: string }
type DadosLigacao = { n: number; ok: boolean }
type NoFluxo = Node<DadosNo, 'no'>
type CartaoFluxo = Node<DadosCartao, 'cartao'>
type LigacaoFluxo = Edge<DadosLigacao, 'ligacao'>

/** Estado da esteira de um job + resumo do dia; polling de 2 s que para com a aba do navegador escondida
 * (e com a aba Esteira fechada, porque o painel da aba é desmontado). */
export function useEsteira(jobId: string | null) {
  const [dados, setDados] = useState<{ job: Job; esteira: DadosEsteira } | null>(null)
  const [resumo, setResumo] = useState<ResumoDoDia | null>(null)
  const [tick, setTick] = useState(0)
  const [offline, setOffline] = useState(false) // última busca da esteira falhou
  useEffect(() => {
    if (!jobId) return
    let vivo = true // resposta atrasada de outro job não sobrescreve a do job atual
    let t: ReturnType<typeof setInterval> | undefined
    const buscar = () => {
      api.esteira(jobId).then((d) => { if (vivo) { setDados(d); setOffline(false) } }).catch(() => vivo && setOffline(true))
      api.resumoDoDia().then((r) => vivo && setResumo(r)).catch(() => {})
    }
    const ligar = () => {
      clearInterval(t)
      if (document.hidden) return
      buscar()
      t = setInterval(buscar, 2000)
    }
    ligar()
    document.addEventListener('visibilitychange', ligar)
    return () => {
      vivo = false
      clearInterval(t)
      document.removeEventListener('visibilitychange', ligar)
    }
  }, [jobId, tick])
  return { dados: dados?.job.id === jobId ? dados : null, resumo, offline, atualizar: () => setTick((n) => n + 1) }
}

function NoEtapa({ data }: NodeProps<NoFluxo>) {
  const { Icone, rotulo } = NO[data.no]
  const publicacao = data.no === 'youtube' || data.no === 'instagram'
  const sub = data.progresso !== null ? `${Math.round(data.progresso * 100)}%${data.msg ? ` · ${data.msg}` : ''}` : data.msg
  return (
    <div className="relative isolate flex w-24 flex-col items-center">
      <button
        type="button"
        data-estado={data.estado}
        aria-label={`${rotulo}: ${ESTADO[data.estado]}`}
        className={`no-esteira relative grid size-24 cursor-pointer place-items-center rounded-2xl bg-card transition-colors ${BORDA[data.estado]}`}
      >
        {data.estado === 'rodando' && !temProperty && (
          <span className="absolute -inset-[3px] -z-10 overflow-hidden rounded-[19px]">
            <span className="absolute -inset-1/2 animate-spin [animation-duration:1.5s]" style={{ background: `conic-gradient(${CORAL} 0 20%, ${CORAL}33 35% 65%, ${CORAL} 90%)` }} />
          </span>
        )}
        <Icone className={`size-8 ${data.estado === 'rodando' ? 'text-[#ff6d5a]' : data.estado === 'ocioso' ? 'text-muted-foreground' : 'text-foreground'}`} />
        {data.estado === 'ok' && (
          <span className="absolute -right-2 -top-2 grid size-5 place-items-center rounded-full bg-emerald-500 text-white"><Check className="size-3" strokeWidth={3} /></span>
        )}
        <Handle type="target" position={Position.Left} isConnectable={false} className="!opacity-0" />
        <Handle type="source" position={Position.Right} isConnectable={false} className="!opacity-0" />
      </button>
      <div className="absolute top-full mt-2 flex w-36 flex-col items-center text-center">
        <span className="line-clamp-2 text-xs font-medium leading-tight">{rotulo}</span>
        {sub && <span className="mt-0.5 line-clamp-1 text-[10px] text-muted-foreground" title={sub}>{sub}</span>}
        {data.estado === 'erro' && publicacao && (
          <span className="mt-1 inline-flex items-center gap-1 text-[10px] font-medium text-destructive"><RotateCcw className="size-3" /> tentar de novo</span>
        )}
      </div>
    </div>
  )
}

function Cartao({ data }: NodeProps<CartaoFluxo>) {
  return <div className="w-28 truncate rounded-md border bg-background px-2 py-1 text-[10px] text-muted-foreground shadow-sm" title={data.texto}>{data.texto}</div>
}

function Ligacao({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data }: EdgeProps<LigacaoFluxo>) {
  const [caminho, x, y] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition })
  return (
    <>
      <BaseEdge path={caminho} style={{ strokeWidth: 2, stroke: data?.ok ? '#10b981' : 'color-mix(in oklab, var(--muted-foreground) 60%, transparent)' }} />
      {!!data?.n && (
        <EdgeLabelRenderer>
          <span
            className="nodrag nopan absolute rounded-full border bg-background px-1.5 py-px text-[10px] text-muted-foreground"
            style={{ transform: `translate(-50%, -50%) translate(${x}px, ${y}px)` }}
          >
            {data.n} {data.n === 1 ? 'item' : 'itens'}
          </span>
        </EdgeLabelRenderer>
      )}
    </>
  )
}

const tiposNo = { no: NoEtapa, cartao: Cartao }
const tiposLigacao = { ligacao: Ligacao }

const posicao = (no: IdNo) => {
  const i = ETAPAS.indexOf(no)
  return i >= 0 ? { x: i * PASSO, y: 0 } : { x: ETAPAS.length * PASSO, y: (PLATAFORMAS.indexOf(no as Plataforma) - 1) * 180 }
}

function montar(e: DadosEsteira, cortes: Corte[], offline: boolean) {
  const porNome = new Map(cortes.map((c) => [c.nome, c]))
  const nos: (NoFluxo | CartaoFluxo)[] = []
  for (const [id, no] of Object.entries(e.nos) as [IdNo, NoEsteira][]) {
    const p = posicao(id)
    nos.push({ id, type: 'no', position: p, data: { no: id, estado: offline && no.estado === 'rodando' ? 'sem-sinal' : no.estado, progresso: no.progresso, msg: no.msg } })
    const lateral = PLATAFORMAS.includes(id as Plataforma) // nas plataformas os cartões vão ao lado (embaixo tem o próximo nó)
    const textos = no.itens.slice(0, MAX_CARTOES).map((item) => {
      const c = porNome.get(item)
      return { item, texto: c ? `${c.nota.toFixed(1)} · ${c.titulo}` : item || 'vídeo' }
    })
    if (no.itens.length > MAX_CARTOES) textos.push({ item: '+', texto: `+${no.itens.length - MAX_CARTOES}` })
    textos.forEach(({ item, texto }, k) =>
      nos.push({
        // mesmo id enquanto o item anda pelas etapas: o React Flow só troca o transform e o CSS faz o deslize
        id: lateral || item === '+' ? `cartao:${id}:${item}` : `cartao:${item}`,
        type: 'cartao',
        position: lateral ? { x: p.x + 112, y: p.y + 8 + k * 26 } : { x: p.x - 8, y: p.y + 160 + k * 26 },
        data: { no: id, texto },
        selectable: false,
      }),
    )
  }
  const ligacoes: LigacaoFluxo[] = Object.entries(e.arestas).map(([chave, n]) => {
    const [origem, destino] = chave.split('-') as [IdNo, IdNo]
    return { id: chave, source: origem, target: destino, type: 'ligacao', data: { n, ok: e.nos[origem]?.estado === 'ok' } }
  })
  return { nos, ligacoes }
}

export function Esteira({ jobs }: { jobs: Job[] | null }) {
  const [escolhido, setEscolhido] = useState<string | null>(null)
  const [aberto, setAberto] = useState<IdNo | null>(null)
  // padrão: o job rodando mais recente, senão o mais recente (a lista já vem do mais novo para o mais velho)
  const jobId = jobs?.some((j) => j.id === escolhido) ? escolhido : (jobs?.find((j) => j.status === 'rodando') ?? jobs?.[0])?.id ?? null
  const { dados, resumo, offline, atualizar } = useEsteira(jobId)
  const fluxo = useMemo(() => dados && montar(dados.esteira, dados.job.cortes, offline), [dados, offline])

  if (jobs === null) return <Skeleton className="h-[440px] w-full" />
  if (!jobs.length)
    return <p className="rounded-xl border border-dashed p-10 text-center text-sm text-muted-foreground">Nenhum vídeo ainda. Comece pela aba Cortar e acompanhe aqui cada etapa até a postagem.</p>

  const itensJob = jobs.map((j) => ({ value: j.id, label: `${nomeEntrada(j.entrada)}${j.status === 'rodando' ? ' · processando' : ''}` }))
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <Select items={itensJob} value={jobId} onValueChange={(v) => { setEscolhido(String(v)); setAberto(null) }}>
          <SelectTrigger className="w-full max-w-md" aria-label="Vídeo"><SelectValue /></SelectTrigger>
          <SelectContent>{itensJob.map((i) => <SelectItem key={i.value} value={i.value}>{i.label}</SelectItem>)}</SelectContent>
        </Select>
        <span className="text-xs text-muted-foreground">Clique num nó para ver o que está nele.</span>
      </div>
      {offline && (
        <p role="alert" className="flex items-center gap-2 rounded-md bg-destructive/15 p-2 text-sm text-destructive">
          <WifiOff className="size-4 shrink-0" /> Sem conexão com o servidor: a esteira mostra a última situação conhecida.
        </p>
      )}

      <div className="relative h-[440px] overflow-hidden rounded-xl border bg-card/40">
        {fluxo ? (
          <ReactFlow
            nodes={fluxo.nos}
            edges={fluxo.ligacoes}
            nodeTypes={tiposNo}
            edgeTypes={tiposLigacao}
            colorMode={ESCURO ? 'dark' : 'light'}
            style={{ background: 'transparent' }}
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable={false}
            nodesFocusable={false} // o foco fica no botão de cada nó
            edgesFocusable={false}
            zoomOnScroll={false}
            preventScrolling={false}
            fitView
            fitViewOptions={{ padding: 0.15 }}
            onNodeClick={(_, n) => setAberto(n.type === 'cartao' ? (n.data as DadosCartao).no : (n.id as IdNo))}
          >
            <Background variant={BackgroundVariant.Dots} gap={16} color="color-mix(in oklab, var(--muted-foreground) 45%, transparent)" />
          </ReactFlow>
        ) : (
          <Skeleton className="size-full" />
        )}
        {aberto && dados && <PainelNo no={aberto} dados={dados} onFechar={() => setAberto(null)} onMudou={atualizar} />}
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <Feed esteira={dados?.esteira ?? null} />
        <Resumo resumo={resumo} />
      </div>
    </div>
  )
}

function PainelNo({ no, dados, onFechar, onMudou }: { no: IdNo; dados: { job: Job; esteira: DadosEsteira }; onFechar: () => void; onMudou: () => void }) {
  const estado = dados.esteira.nos[no]
  const porNome = new Map(dados.job.cortes.map((c) => [c.nome, c]))
  const plataforma = PLATAFORMAS.includes(no as Plataforma) ? (no as Plataforma) : null
  const [ocupado, setOcupado] = useState<string | null>(null)

  async function tentar(c: Corte, p: Plataforma) {
    setOcupado(c.nome)
    try {
      await api.publicacao(dados.job.id, c.json, p, 'tentar')
      toast.success('Enviando de novo', { description: c.titulo })
      onMudou()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setOcupado(null)
    }
  }

  return (
    <aside className={`absolute inset-y-0 right-0 z-10 flex ${no === 'aprovacao' ? 'w-96' : 'w-80'} max-w-full flex-col border-l bg-background/95 backdrop-blur`}>
      <div className="flex items-start justify-between gap-2 border-b p-4">
        <div className="min-w-0">
          <h3 className="font-medium">{NO[no].rotulo}</h3>
          <p className="text-xs text-muted-foreground">{ESTADO[estado.estado]}{estado.msg && ` · ${estado.msg}`}</p>
        </div>
        <Button variant="ghost" size="icon-sm" aria-label="Fechar painel" onClick={onFechar}><X className="size-4" /></Button>
      </div>
      {no === 'aprovacao' ? (
        <PainelAprovacao job={dados.job} cortes={estado.itens.flatMap((i) => porNome.get(i) ?? [])} onMudou={onMudou} />
      ) : (
        <ul className="flex flex-1 flex-col gap-2 overflow-y-auto p-4">
          {!estado.itens.length && <li className="text-sm text-muted-foreground">Nenhum item aqui agora.</li>}
          {estado.itens.map((item) => {
            const c = porNome.get(item)
            if (!c) return <li key={item} className="rounded-md border px-3 py-2 text-sm">{item || 'vídeo inteiro'}</li>
            const pub = plataforma ? c.publicacao?.plataformas?.[plataforma] : undefined
            return (
              <li key={item} className="flex gap-3 rounded-md border p-2">
                <img src={c.thumb_url} alt="" className="aspect-[9/16] w-10 shrink-0 rounded object-cover" loading="lazy" />
                <div className="flex min-w-0 flex-col gap-1">
                  <span className="line-clamp-2 text-sm leading-snug">{c.titulo}</span>
                  <span className="text-xs text-muted-foreground"><b className="text-primary">{c.nota.toFixed(1)}</b> / 10</span>
                  {pub && (
                    <span className={`text-xs ${COR_PUBLICACAO[pub.estado]}`}>
                      {pub.estado}{pub.erro && `: ${pub.erro}`}
                    </span>
                  )}
                  {pub?.link && <a href={pub.link} target="_blank" rel="noreferrer" className="truncate text-xs text-primary underline">{pub.link}</a>}
                  {pub?.estado === 'erro' && plataforma !== 'tiktok' && (
                    <Button variant="outline" size="sm" className="self-start" disabled={ocupado === c.nome} onClick={() => tentar(c, plataforma!)}>
                      <RotateCcw className="size-3" /> Tentar de novo
                    </Button>
                  )}
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </aside>
  )
}

const COR_FEED: Record<string, string> = { inicio: 'bg-sky-500', progresso: 'bg-muted-foreground', fim: 'bg-emerald-500', erro: 'bg-destructive' }

function Feed({ esteira }: { esteira: DadosEsteira | null }) {
  return (
    <section className="flex flex-col gap-2 rounded-xl border p-4">
      <h3 className="text-sm font-medium text-muted-foreground">Ao vivo</h3>
      {!esteira?.feed.length ? (
        <p className="text-sm text-muted-foreground">Nada aconteceu ainda neste vídeo.</p>
      ) : (
        <ol className="flex max-h-64 flex-col gap-1.5 overflow-y-auto">
          {esteira.feed.map((f, i) => (
            <li key={i} className="flex items-baseline gap-2 text-sm">
              <span className="shrink-0 font-mono text-xs text-muted-foreground">{f.t?.slice(11, 19)}</span>
              <span className={`size-1.5 shrink-0 translate-y-[-1px] rounded-full ${COR_FEED[f.estado] ?? 'bg-muted-foreground'}`} />
              <span className="shrink-0 text-xs font-medium">{NO[f.etapa as IdNo]?.rotulo ?? f.etapa}</span>
              <span className="truncate text-muted-foreground">{f.msg}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}

function Resumo({ resumo }: { resumo: ResumoDoDia | null }) {
  const itens: [string, keyof ResumoDoDia, string][] = [
    ['Cortes gerados', 'cortes', ''],
    ['Aprovados', 'aprovados', ''],
    ['Postados', 'postados', 'text-emerald-500'],
    ['Erros', 'erros', 'text-destructive'],
  ]
  return (
    <section className="flex flex-col gap-2 rounded-xl border p-4">
      <h3 className="text-sm font-medium text-muted-foreground">Hoje</h3>
      <dl className="grid grid-cols-2 gap-3">
        {itens.map(([rotulo, chave, cor]) => (
          <div key={chave} className="rounded-lg bg-muted/50 p-3">
            <dt className="text-xs text-muted-foreground">{rotulo}</dt>
            <dd className={`text-2xl font-semibold ${resumo?.[chave] ? cor : ''}`}>{resumo ? resumo[chave] : '–'}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}
