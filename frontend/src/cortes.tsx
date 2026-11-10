import { useEffect, useState } from 'react'
import { Menu } from '@base-ui/react/menu'
import { CalendarClock, EllipsisVertical, Send, Video } from 'lucide-react'
import { toast } from 'sonner'
import { api, type Corte } from '@/api'
import { Confirmar } from '@/lixeira'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'

const horario = (data: string) => new Date(data).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })
const erroToast = (erro: unknown) => toast.error((erro as Error).message)
const agendavel = (c: Corte) => !c.publicacao?.plataformas?.youtube || c.publicacao.plataformas.youtube.estado === 'erro'
const itemMenu = 'flex cursor-pointer items-center gap-2 rounded px-3 py-2 text-sm outline-none data-[highlighted]:bg-muted data-[disabled]:pointer-events-none data-[disabled]:opacity-40'

export function GradeCortes({ cortes, carregando, onAbrir, onMudou }: {
  cortes: Corte[]; carregando: boolean; onAbrir: (c: Corte) => void; onMudou: () => void
}) {
  const [selecionados, setSelecionados] = useState<string[]>([])
  const [agendar, setAgendar] = useState<Corte[]>([])
  const [envio, setEnvio] = useState<{ corte: Corte; plataforma: 'youtube' | 'telegram' } | null>(null)
  const escolhas = selecionados.flatMap((id) => cortes.filter((c) => c.video_url === id && agendavel(c)))
  const disponiveis = cortes.filter(agendavel)

  function selecionar(c: Corte) {
    setSelecionados((ids) => ids.includes(c.video_url) ? ids.filter((id) => id !== c.video_url) : [...ids, c.video_url])
  }

  async function enviar() {
    if (!envio) return
    const c = envio.corte
    const estado = envio.plataforma === 'telegram' ? c.publicacao?.telegram : c.publicacao?.plataformas?.youtube
    try {
      await api.enviarCorte(c, envio.plataforma, { forcar: estado?.estado === 'ok' || estado?.estado === 'incerto' })
      toast.success(`Enviando para o ${envio.plataforma === 'youtube' ? 'YouTube' : 'Telegram'}`)
      setEnvio(null)
      onMudou()
    } catch (erro) {
      erroToast(erro)
    }
  }

  if (carregando) return <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">{[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="aspect-[9/16]" />)}</div>
  if (!cortes.length) return <p className="rounded-xl border border-dashed p-10 text-center text-sm text-muted-foreground">Os cortes aparecem aqui, ordenados pela nota viral.</p>
  const destino = envio?.plataforma === 'youtube' ? 'YouTube' : 'Telegram'
  const registro = envio?.plataforma === 'youtube' ? envio.corte.publicacao?.plataformas?.youtube : envio?.corte.publicacao?.telegram
  const repetindo = registro?.estado === 'ok' || registro?.estado === 'incerto'

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2 rounded-lg border p-3">
        <Button variant="outline" size="sm" disabled={!disponiveis.length} onClick={() => setSelecionados(disponiveis.map((c) => c.video_url))}>Selecionar disponíveis ({disponiveis.length})</Button>
        <Button variant="ghost" size="sm" disabled={!selecionados.length} onClick={() => setSelecionados([])}>Limpar seleção</Button>
        <Button size="sm" disabled={!escolhas.length} onClick={() => setAgendar(escolhas)}><CalendarClock className="size-4" /> Agendar selecionados ({escolhas.length})</Button>
        <span className="text-xs text-muted-foreground">Selecione os cortes na ordem de publicação.</span>
      </div>
      <div className="grid grid-cols-2 items-start gap-4 sm:grid-cols-3 lg:grid-cols-5">
        {cortes.map((c) => {
          const yt = c.publicacao?.plataformas?.youtube
          const tg = c.publicacao?.telegram
          const programado = yt?.estado === 'ok' && yt.publish_at
          return (
            <article key={c.video_url} className="flex min-w-0 flex-col gap-2">
              <div className="relative overflow-hidden rounded-xl border bg-muted">
                <button onClick={() => onAbrir(c)} className="group block w-full" aria-label={`Abrir corte: ${c.titulo}`}>
                  <img src={c.thumb_url} alt="" className="aspect-[9/16] w-full object-cover transition-transform duration-300 group-hover:scale-[1.03]" loading="lazy" />
                </button>
                <label className="absolute left-2 top-2 flex items-center gap-1.5 rounded bg-black/75 p-1.5 text-xs text-white">
                  <input type="checkbox" checked={escolhas.some((e) => e.video_url === c.video_url)} disabled={!agendavel(c)} onChange={() => selecionar(c)} aria-label={`Selecionar para agendar: ${c.titulo}`} className="size-4 accent-primary" />
                  {c.nota.toFixed(1)}
                </label>
                <div className="absolute right-2 top-2">
                  <Menu.Root>
                    <Menu.Trigger className="grid size-8 place-items-center rounded-md bg-black/75 text-white hover:bg-black focus-visible:outline-2 focus-visible:outline-primary" aria-label={`Ações do corte: ${c.titulo}`}><EllipsisVertical className="size-4" /></Menu.Trigger>
                    <Menu.Portal>
                      <Menu.Positioner align="end" sideOffset={6} className="z-50">
                        <Menu.Popup className="min-w-52 rounded-lg border bg-popover p-1 text-popover-foreground shadow-lg">
                          <Menu.Item className={itemMenu} disabled={yt?.estado === 'enviando'} onClick={() => setEnvio({ corte: c, plataforma: 'youtube' })}><Video className="size-4" /> {yt ? 'Reenviar ao YouTube' : 'Enviar ao YouTube'}</Menu.Item>
                          <Menu.Item className={itemMenu} disabled={!agendavel(c)} onClick={() => setAgendar([c])}><CalendarClock className="size-4" /> Agendar no YouTube</Menu.Item>
                          <Menu.Item className={itemMenu} disabled={tg?.estado === 'enviando'} onClick={() => setEnvio({ corte: c, plataforma: 'telegram' })}><Send className="size-4" /> {tg ? 'Reenviar ao Telegram' : 'Enviar ao Telegram'}</Menu.Item>
                        </Menu.Popup>
                      </Menu.Positioner>
                    </Menu.Portal>
                  </Menu.Root>
                </div>
                <span className="pointer-events-none absolute bottom-2 right-2 rounded bg-black/70 px-1.5 py-0.5 text-[11px] text-white">{Math.floor(c.duracao / 60)}:{String(Math.round(c.duracao % 60)).padStart(2, '0')}</span>
              </div>
              <button onClick={() => onAbrir(c)} className="line-clamp-2 text-left text-sm font-medium leading-snug">{c.titulo}</button>
              {yt && <p className={`text-xs ${yt.estado === 'erro' || yt.estado === 'incerto' ? 'text-destructive' : 'text-muted-foreground'}`}>
                {yt.estado === 'enviando' ? 'YouTube: enviando…' : programado ? `Agendado · ${horario(yt.publish_at!)}` : yt.estado === 'ok' ? 'YouTube: publicado' : `YouTube: ${yt.estado}`}
              </p>}
              {yt?.erro && <p className="break-words text-xs text-destructive">{yt.erro}</p>}
              {tg && <p className={`text-xs ${tg.estado === 'erro' || tg.estado === 'incerto' ? 'text-destructive' : 'text-muted-foreground'}`}>Telegram: {tg.estado === 'ok' ? 'enviado' : tg.estado === 'enviando' ? 'enviando…' : tg.estado}</p>}
              {tg?.erro && <p className="break-words text-xs text-destructive">{tg.erro}</p>}
            </article>
          )
        })}
      </div>
      <Confirmar
        aberto={envio !== null}
        titulo={`${repetindo ? 'Reenviar' : 'Enviar'} para o ${destino}?`}
        descricao={repetindo ? `Este corte já teve um envio. Confirmar cria uma nova cópia no ${destino} e mantém o registro anterior no histórico.` : `${envio?.corte.titulo ?? ''}. ${envio?.plataforma === 'youtube' ? 'O vídeo será publicado agora no canal conectado.' : 'O vídeo e a legenda serão enviados ao chat conectado.'}`}
        acao={repetindo ? 'Confirmar reenvio' : 'Enviar agora'}
        onConfirmar={enviar}
        onFechar={() => setEnvio(null)}
      />
      {agendar.length > 0 && <Agendamento
        cortes={agendar}
        onFechar={() => setAgendar([])}
        onEnviado={(c) => { setSelecionados((ids) => ids.filter((id) => id !== c.video_url)); onMudou() }}
      />}
    </div>
  )
}

function proximoHorario() {
  const data = new Date()
  data.setMinutes(data.getMinutes() < 30 ? 30 : 60, 0, 0)
  return new Date(data.getTime() - data.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
}

function Agendamento({ cortes, onFechar, onEnviado }: { cortes: Corte[]; onFechar: () => void; onEnviado: (c: Corte) => void }) {
  const [pendentes, setPendentes] = useState(cortes)
  const [inicio, setInicio] = useState(proximoHorario)
  const [intervalo, setIntervalo] = useState('30')
  const [ocupado, setOcupado] = useState(false)
  const [falhas, setFalhas] = useState<string[]>([])
  const [agora, setAgora] = useState(Date.now)
  useEffect(() => {
    const timer = setInterval(() => setAgora(Date.now()), 10000)
    return () => clearInterval(timer)
  }, [])
  const minutos = Number(intervalo)
  const inicioMs = new Date(inicio).getTime()
  const valido = Number.isFinite(inicioMs) && inicioMs > agora && Number.isInteger(minutos) && minutos >= 1 && minutos <= 10080
  const fuso = Intl.DateTimeFormat().resolvedOptions().timeZone
  const datas = pendentes.map((c) => {
    const indice = cortes.findIndex((original) => original.video_url === c.video_url)
    return new Date(inicioMs + indice * minutos * 60000)
  })

  async function confirmar() {
    if (!valido || ocupado) return
    setOcupado(true)
    setFalhas([])
    const erros: string[] = []
    const restantes: Corte[] = []
    for (let i = 0; i < pendentes.length; i++) {
      const c = pendentes[i]
      try {
        await api.enviarCorte(c, 'youtube', { publish_at: datas[i].toISOString() })
        onEnviado(c)
      } catch (erro) {
        restantes.push(c)
        erros.push(`${c.titulo}: ${(erro as Error).message}`)
      }
    }
    setOcupado(false)
    if (!erros.length) {
      toast.success(`Agendamento solicitado para ${pendentes.length} corte(s)`, { description: 'Acompanhe a confirmação do upload na grade.' })
      onFechar()
    } else {
      setPendentes(restantes)
      setFalhas(erros)
    }
  }

  return (
    <Dialog open onOpenChange={(aberto) => !aberto && !ocupado && onFechar()}>
      <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Agendar no YouTube</DialogTitle>
          <DialogDescription>Os vídeos serão enviados agora e publicados pelo YouTube nos horários abaixo. Fuso do navegador: {fuso}.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-2"><Label htmlFor="inicio-agendamento">Primeira publicação</Label><Input id="inicio-agendamento" type="datetime-local" value={inicio} onChange={(e) => setInicio(e.target.value)} disabled={ocupado} /></div>
          <div className="flex flex-col gap-2"><Label htmlFor="intervalo-agendamento">Intervalo em minutos</Label><Input id="intervalo-agendamento" type="number" min="1" max="10080" step="1" value={intervalo} onChange={(e) => setIntervalo(e.target.value)} disabled={ocupado} /></div>
        </div>
        {!valido && <p className="text-sm text-destructive">Escolha uma data futura e um intervalo de 1 a 10080 minutos.</p>}
        <ol className="max-h-64 divide-y overflow-y-auto rounded-lg border px-3">
          {pendentes.map((c, i) => <li key={c.video_url} className="flex flex-col gap-1 py-3 text-sm"><span className="font-medium">{c.titulo}</span><span className="text-muted-foreground">{valido ? horario(datas[i].toISOString()) : 'Horário inválido'}</span></li>)}
        </ol>
        {falhas.length > 0 && <div role="alert" className="space-y-1 text-sm text-destructive">{falhas.map((erro) => <p key={erro}>{erro}</p>)}<p>Os envios aceitos já aparecem na grade. Confira os erros antes de tentar os restantes.</p></div>}
        <div className="flex justify-end gap-2"><Button variant="ghost" onClick={onFechar} disabled={ocupado}>Cancelar</Button><Button onClick={confirmar} disabled={ocupado || !valido}>{ocupado ? 'Preparando envios…' : `Agendar ${pendentes.length} corte(s)`}</Button></div>
      </DialogContent>
    </Dialog>
  )
}
