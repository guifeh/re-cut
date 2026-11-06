import { useState } from 'react'
import { toast } from 'sonner'
import { Check, Copy, Download, ExternalLink, Loader2, Plus, RotateCcw, Trash2 } from 'lucide-react'
import { api, type Corte, type EstadoPlataforma, type Job, type Plataforma, type Publicacao } from '@/api'
import { Confirmar } from '@/lixeira'
import { COR_PUBLICACAO, NOME_PLATAFORMA as NOME, PLATAFORMAS } from '@/plataformas'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'

const LIMITE = 2200
const tamanho = (s: string) => Array.from(s).length // o servidor conta caracteres do Python (code points), não UTF-16

/** Espelho de `publicar.texto_final`: legenda + linha em branco + até 30 hashtags, tudo em até 2200 caracteres. */
function textoFinal(legenda: string, hashtags: string[]) {
  const tags = hashtags.map((h) => h.replace(/\s+/g, '').replace(/^#+/, '')).filter(Boolean).slice(0, 30).map((t) => `#${t}`).join(' ')
  const sufixo = tags ? `\n\n${tags}` : ''
  return Array.from(Array.from(legenda.trim()).slice(0, LIMITE - tamanho(sufixo)).join('') + sufixo).slice(0, LIMITE).join('')
}

const erroToast = (e: unknown) => toast.error((e as Error).message)

async function copiar(texto: string, oque: string) {
  try {
    await navigator.clipboard.writeText(texto)
    toast.success(`${oque} copiad${oque === 'Legenda' ? 'a' : 'o'}`)
  } catch {
    toast.error('Não deu para copiar: selecione e copie à mão')
  }
}

/** Corpo do painel do nó "Sua aprovação": cortes esperando (maior nota primeiro) e, abaixo, os já aprovados
 * com o status de cada plataforma (mais recente primeiro). */
export function PainelAprovacao({ job, cortes, onMudou }: { job: Job; cortes: Corte[]; onMudou: () => void }) {
  const esperando = [...cortes].sort((a, b) => b.nota - a.nota)
  const aprovados = job.cortes
    .filter((c) => c.publicacao?.aprovado_em)
    .sort((a, b) => b.publicacao!.aprovado_em!.localeCompare(a.publicacao!.aprovado_em!))
  return (
    <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-4">
      <section className="flex flex-col gap-3">
        <h4 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Esperando ({esperando.length})</h4>
        {!esperando.length && <p className="text-sm text-muted-foreground">Nenhum corte esperando sua aprovação.</p>}
        {esperando.map((c) => <Esperando key={c.nome} job={job} corte={c} onMudou={onMudou} />)}
      </section>
      {aprovados.length > 0 && (
        <section className="flex flex-col gap-3">
          <h4 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Aprovados ({aprovados.length})</h4>
          {aprovados.map((c) => <Aprovado key={c.nome} job={job} corte={c} onMudou={onMudou} />)}
        </section>
      )}
    </div>
  )
}

function Esperando({ job, corte: c, onMudou }: { job: Job; corte: Corte; onMudou: () => void }) {
  const [legendas, setLegendas] = useState(() => (c.legendas?.length ? c.legendas : [c.descricao || c.titulo]))
  const [escolhida, setEscolhida] = useState(0)
  const [tags, setTags] = useState(() =>
    [...new Map(c.hashtags.map((h) => h.replace(/\s+/g, '').replace(/^#+/, '')).filter(Boolean).map((t) => [t.toLowerCase(), t])).values()]
      .map((t) => ({ t, on: true })),
  )
  const [nova, setNova] = useState('')
  const [fase, setFase] = useState<'livre' | 'enviando' | 'aprovado'>('livre')
  const [descartar, setDescartar] = useState(false)

  const legenda = legendas[escolhida] ?? ''
  const marcadas = tags.filter((h) => h.on).map((h) => h.t)
  const texto = textoFinal(legenda, marcadas)
  const bruto = tamanho(legenda.trim()) + (marcadas.length ? 2 + tamanho(marcadas.slice(0, 30).map((t) => `#${t}`).join(' ')) : 0)

  function adicionar() {
    const t = nova.replace(/\s+/g, '').replace(/^#+/, '')
    if (t && !tags.some((h) => h.t.toLowerCase() === t.toLowerCase())) setTags([...tags, { t, on: true }])
    setNova('')
  }

  async function aprovar() {
    setFase('enviando') // desabilita já no clique; só volta se falhar
    try {
      const r = await api.aprovar(job.id, c.json, legenda, marcadas)
      setFase('aprovado') // fica travado sem spinner até o próximo polling tirar o corte desta lista
      toast.success('Aprovado: enviando para YouTube e Instagram', {
        description: r.telegram ? 'O TikTok foi para o seu Telegram: poste pelo celular e responda à mensagem com o link.' : 'O TikTok fica com você: baixe o vídeo e cole o link depois.',
      })
      onMudou()
    } catch (e) {
      erroToast(e)
      setFase('livre')
    }
  }

  async function moverParaLixeira() {
    try {
      await api.excluirCorte(job.id, c.json)
      toast.success('Corte movido para a lixeira', { description: c.titulo })
      setDescartar(false)
      onMudou()
    } catch (e) {
      erroToast(e)
    }
  }

  return (
    <article className="flex flex-col gap-3 rounded-lg border p-3">
      <video src={c.video_url} poster={c.thumb_url} controls preload="metadata" className="mx-auto aspect-[9/16] h-64 rounded bg-black" />
      <div>
        <p className="text-sm font-medium leading-snug">{c.titulo}</p>
        <p className="mt-1 text-xs text-muted-foreground"><b className="text-primary">{c.nota.toFixed(1)}</b> / 10 · {c.motivo}</p>
      </div>

      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 text-xs font-medium">Legenda</legend>
        {legendas.map((l, i) => (
          <div key={i} className="flex items-start gap-2">
            <input
              type="radio"
              name={`legenda-${c.nome}`}
              checked={escolhida === i}
              onChange={() => setEscolhida(i)}
              aria-label={`Legenda ${i + 1}`}
              className="mt-2 accent-primary"
            />
            <Textarea
              value={l}
              rows={2}
              aria-label={`Texto da legenda ${i + 1}`}
              className="min-h-0 text-sm"
              onFocus={() => setEscolhida(i)}
              onChange={(e) => setLegendas(legendas.map((x, k) => (k === i ? e.target.value : x)))}
            />
          </div>
        ))}
      </fieldset>

      <div className="flex flex-col gap-2">
        <span className="text-xs font-medium">Hashtags</span>
        <div className="flex flex-wrap gap-1.5">
          {tags.map((h, i) => (
            <button
              key={h.t}
              type="button"
              aria-pressed={h.on}
              onClick={() => setTags(tags.map((x, k) => (k === i ? { ...x, on: !x.on } : x)))}
              className={`inline-flex h-6 items-center gap-1 rounded-full border px-2 text-xs transition-colors ${h.on ? 'border-primary bg-primary/15 text-foreground' : 'text-muted-foreground line-through'}`}
            >
              {h.on && <Check className="size-3" />}#{h.t}
            </button>
          ))}
        </div>
        <form className="flex gap-1.5" onSubmit={(e) => { e.preventDefault(); adicionar() }}>
          <Input value={nova} onChange={(e) => setNova(e.target.value)} placeholder="nova hashtag" aria-label="Nova hashtag" className="h-7 text-xs" />
          <Button type="submit" variant="outline" size="sm" disabled={!nova.trim()}><Plus className="size-3" /> Adicionar</Button>
        </form>
      </div>

      <div className="flex flex-col gap-1">
        <div className="flex items-baseline justify-between text-xs">
          <span className="font-medium">Como vai sair</span>
          <span className={bruto > LIMITE ? 'text-destructive' : 'text-muted-foreground'}>{tamanho(texto)} / {LIMITE}</span>
        </div>
        <p className="max-h-32 overflow-y-auto whitespace-pre-wrap break-words rounded-md bg-muted/50 p-2 text-xs">{texto || '—'}</p>
        {bruto > LIMITE && <p className="text-xs text-destructive">Passou de {LIMITE}: o fim da legenda será cortado.</p>}
        {marcadas.length > 30 && <p className="text-xs text-muted-foreground">Só as 30 primeiras hashtags entram.</p>}
      </div>

      <div className="flex gap-2">
        <Button className="flex-1" disabled={fase !== 'livre' || !legenda.trim()} onClick={aprovar}>
          {fase === 'enviando' && <Loader2 className="size-4 animate-spin" />}
          {fase === 'aprovado' ? <><Check className="size-4" /> Aprovado</> : 'Aprovar e postar'}
        </Button>
        <Button variant="outline" disabled={fase !== 'livre'} onClick={() => setDescartar(true)}><Trash2 className="size-4" /> Descartar</Button>
      </div>
      <Confirmar
        aberto={descartar}
        titulo="Descartar este corte?"
        descricao={`"${c.titulo}" vai para a lixeira e não é postado. Dá para restaurar pela aba Lixeira.`}
        acao="Mover para a lixeira"
        perigo
        onConfirmar={moverParaLixeira}
        onFechar={() => setDescartar(false)}
      />
    </article>
  )
}

function Aprovado({ job, corte: c, onMudou }: { job: Job; corte: Corte; onMudou: () => void }) {
  const pub = c.publicacao!
  const texto = textoFinal(pub.legenda ?? '', pub.hashtags ?? [])
  return (
    <article className="flex flex-col gap-2 rounded-lg border p-3">
      <div className="flex gap-3">
        <img src={c.thumb_url} alt="" className="aspect-[9/16] w-10 shrink-0 rounded object-cover" loading="lazy" />
        <div className="min-w-0">
          <p className="line-clamp-2 text-sm leading-snug">{c.titulo}</p>
          <p className="text-xs text-muted-foreground">aprovado {pub.aprovado_em!.slice(11, 16)} · <b className="text-primary">{c.nota.toFixed(1)}</b></p>
        </div>
      </div>
      <ul className="flex flex-col divide-y">
        {PLATAFORMAS.map((p) => {
          const e = pub.plataformas?.[p]
          return e ? <LinhaPlataforma key={p} job={job} corte={c} plataforma={p} estado={e} texto={texto} onMudou={onMudou} /> : null
        })}
        {pub.telegram && <LinhaTelegram job={job} corte={c} estado={pub.telegram} onMudou={onMudou} />}
      </ul>
    </article>
  )
}

function LinhaPlataforma({ job, corte: c, plataforma: p, estado: e, texto, onMudou }: {
  job: Job; corte: Corte; plataforma: Plataforma; estado: EstadoPlataforma; texto: string; onMudou: () => void
}) {
  const [ocupado, setOcupado] = useState(false)
  const [colando, setColando] = useState(false)
  const [reenviar, setReenviar] = useState(false)

  async function acao(a: 'tentar' | 'forcar' | 'link', link?: string) {
    setOcupado(true)
    try {
      await api.publicacao(job.id, c.json, p, a, link)
      toast.success(a === 'link' ? `Link do ${NOME[p]} salvo` : `Enviando de novo para o ${NOME[p]}`)
      setColando(false)
      setReenviar(false)
      onMudou()
    } catch (err) {
      erroToast(err)
    } finally {
      setOcupado(false)
    }
  }

  return (
    <li className="flex flex-col gap-1.5 py-2 text-xs">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium">{NOME[p]}</span>
        <span className={COR_PUBLICACAO[e.estado]}>
          {e.estado === 'enviando' ? <span className="inline-flex items-center gap-1"><Loader2 className="size-3 animate-spin" /> enviando…</span>
            : { ok: 'postado', erro: 'erro', incerto: 'incerto', manual: 'com você' }[e.estado]}
        </span>
      </div>

      {e.estado === 'ok' && (e.link ? (
        <div className="flex items-center gap-1">
          <a href={e.link} target="_blank" rel="noreferrer" className="min-w-0 flex-1 truncate text-primary underline">{e.link}</a>
          <Button variant="ghost" size="icon-xs" aria-label={`Copiar link do ${NOME[p]}`} onClick={() => copiar(e.link!, 'Link')}><Copy className="size-3" /></Button>
        </div>
      ) : (
        <>
          <p className="text-muted-foreground">Postado, mas o link não veio: pegue no app e cole aqui.</p>
          <ColarLink plataforma={p} ocupado={ocupado} onSalvar={(l) => acao('link', l)} />
        </>
      ))}

      {e.estado === 'erro' && (
        <>
          <p className="break-words text-destructive">{e.erro}</p>
          {p !== 'tiktok' && (
            <Button variant="outline" size="sm" className="self-start" disabled={ocupado} onClick={() => acao('tentar')}>
              <RotateCcw className="size-3" /> Tentar de novo
            </Button>
          )}
          {/* ex.: o reenvio achou o Reel já publicado; o servidor aceita link em erro */}
          <ColarLink plataforma={p} ocupado={ocupado} onSalvar={(l) => acao('link', l)} />
        </>
      )}

      {e.estado === 'incerto' && (
        <>
          <p className="break-words text-muted-foreground">{e.erro ?? 'Não deu para confirmar o envio: confira no app antes de enviar de novo.'}</p>
          <div className="flex flex-wrap gap-1.5">
            <Button variant="outline" size="sm" disabled={ocupado} onClick={() => setColando(!colando)}>Já saiu (colar link)</Button>
            <Button variant="outline" size="sm" disabled={ocupado} onClick={() => setReenviar(true)}><RotateCcw className="size-3" /> Enviar de novo</Button>
          </div>
          {colando && <ColarLink plataforma={p} ocupado={ocupado} onSalvar={(l) => acao('link', l)} />}
          <Confirmar
            aberto={reenviar}
            titulo={`Enviar de novo para o ${NOME[p]}?`}
            descricao="Se o primeiro envio saiu, o vídeo vai aparecer duas vezes. Confira no app antes."
            acao="Enviar de novo"
            perigo
            onConfirmar={() => acao('forcar')}
            onFechar={() => setReenviar(false)}
          />
        </>
      )}

      {e.estado === 'manual' && (
        <>
          <div className="flex flex-wrap gap-1.5">
            <Button variant="outline" size="sm" render={<a href={c.video_url} download={c.arquivo} />} nativeButton={false}>
              <Download className="size-3" /> Baixar vídeo
            </Button>
            <Button variant="outline" size="sm" onClick={() => copiar(texto, 'Legenda')}><Copy className="size-3" /> Copiar legenda</Button>
          </div>
          <ColarLink plataforma={p} ocupado={ocupado} onSalvar={(l) => acao('link', l)} />
        </>
      )}
    </li>
  )
}

function LinhaTelegram({ job, corte: c, estado: e, onMudou }: {
  job: Job; corte: Corte; estado: NonNullable<Publicacao['telegram']>; onMudou: () => void
}) {
  const [ocupado, setOcupado] = useState(false)
  const [reenviar, setReenviar] = useState(false)

  async function acao(a: 'tentar' | 'forcar') {
    setOcupado(true)
    try {
      await api.publicacao(job.id, c.json, 'telegram', a)
      toast.success('Enviando de novo para o Telegram')
      setReenviar(false)
      onMudou()
    } catch (err) {
      erroToast(err)
    } finally {
      setOcupado(false)
    }
  }

  return (
    <li className="flex flex-col gap-1.5 py-2 text-xs">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium">Telegram</span>
        <span className={COR_PUBLICACAO[e.estado]}>
          {e.estado === 'enviando' ? <span className="inline-flex items-center gap-1"><Loader2 className="size-3 animate-spin" /> enviando…</span>
            : { ok: 'enviado', erro: 'erro', incerto: 'incerto' }[e.estado]}
        </span>
      </div>
      {e.estado === 'erro' && (
        <>
          <p className="break-words text-destructive">{e.erro}</p>
          <Button variant="outline" size="sm" className="self-start" disabled={ocupado} onClick={() => acao('tentar')}>
            <RotateCcw className="size-3" /> Tentar de novo
          </Button>
        </>
      )}
      {e.estado === 'incerto' && (
        <>
          <p className="break-words text-muted-foreground">{e.erro ?? 'Não deu para confirmar o envio: confira no Telegram antes de enviar de novo.'}</p>
          <Button variant="outline" size="sm" className="self-start" disabled={ocupado} onClick={() => setReenviar(true)}>
            <RotateCcw className="size-3" /> Enviar mesmo assim
          </Button>
          <Confirmar
            aberto={reenviar}
            titulo="Enviar de novo para o Telegram?"
            descricao="Se o primeiro envio chegou, o vídeo vai aparecer duas vezes no chat. Confira antes."
            acao="Enviar mesmo assim"
            perigo
            onConfirmar={() => acao('forcar')}
            onFechar={() => setReenviar(false)}
          />
        </>
      )}
    </li>
  )
}

function ColarLink({ plataforma: p, ocupado, onSalvar }: { plataforma: Plataforma; ocupado: boolean; onSalvar: (link: string) => void }) {
  const [link, setLink] = useState('')
  return (
    <form className="flex gap-1.5" onSubmit={(e) => { e.preventDefault(); onSalvar(link.trim()) }}>
      <Input type="url" value={link} onChange={(e) => setLink(e.target.value)} placeholder={`Colar link do ${NOME[p]}`} aria-label={`Link do post no ${NOME[p]}`} className="h-7 text-xs" />
      <Button type="submit" size="sm" disabled={ocupado || !link.trim()}><ExternalLink className="size-3" /> Salvar</Button>
    </form>
  )
}
