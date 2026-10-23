import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Film, History, RotateCcw, Scissors, Trash2 } from 'lucide-react'
import { api, type EventoLixeira, type ItemLixeira } from '@/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'

const dataHora = new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'short' })
export const quando = (iso: string) => dataHora.format(new Date(iso))
const megas = (bytes: number) => (bytes >= 1e9 ? `${(bytes / 1e9).toFixed(1)} GB` : `${(bytes / 1e6).toFixed(1)} MB`)
const diasAte = (iso: string) => Math.max(0, Math.ceil((new Date(iso).getTime() - Date.now()) / 86_400_000))

const ACAO: Record<EventoLixeira['acao'], { texto: string; classe: string }> = {
  excluido: { texto: 'Movido para a lixeira', classe: 'text-amber-400' },
  restaurado: { texto: 'Restaurado', classe: 'text-emerald-400' },
  apagado: { texto: 'Apagado de vez', classe: 'text-destructive' },
  expirado: { texto: 'Expirou e foi apagado', classe: 'text-muted-foreground' },
}

/** Confirmação com o diálogo do app (nada de window.confirm). */
export function Confirmar({ aberto, titulo, descricao, acao, perigo, onConfirmar, onFechar }: {
  aberto: boolean
  titulo: string
  descricao: string
  acao: string
  perigo?: boolean
  onConfirmar: () => Promise<void> | void
  onFechar: () => void
}) {
  const [ocupado, setOcupado] = useState(false)
  return (
    <Dialog open={aberto} onOpenChange={(o) => !o && !ocupado && onFechar()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{titulo}</DialogTitle>
          <DialogDescription>{descricao}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="ghost" onClick={onFechar} disabled={ocupado}>Cancelar</Button>
          <Button
            variant={perigo ? 'destructive' : 'default'}
            disabled={ocupado}
            onClick={async () => {
              setOcupado(true)
              try {
                await onConfirmar()
              } finally {
                setOcupado(false)
              }
            }}
          >
            {ocupado ? 'Aguarde…' : acao}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function Lixeira({ onMudou }: { onMudou: () => void }) {
  const [itens, setItens] = useState<ItemLixeira[] | null>(null)
  const [registro, setRegistro] = useState<EventoLixeira[]>([])
  const [apagando, setApagando] = useState<ItemLixeira | null>(null)

  const carregar = useCallback(() => {
    api.lixeira().then(setItens).catch(() => setItens([]))
    api.registroLixeira().then(setRegistro).catch(() => {})
  }, [])
  useEffect(carregar, [carregar])

  async function restaurar(i: ItemLixeira) {
    try {
      await api.restaurar(i.id)
      toast.success(i.tipo === 'video' ? 'Vídeo restaurado' : 'Corte restaurado', { description: i.titulo })
      carregar()
      onMudou()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  async function apagar(i: ItemLixeira) {
    try {
      await api.apagarDeVez(i.id)
      toast(`"${i.titulo}" apagado de vez`)
      setApagando(null)
      carregar()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  return (
    <div className="flex flex-col gap-8">
      <section className="flex flex-col gap-3">
        <div>
          <h2 className="text-lg font-semibold">Lixeira</h2>
          <p className="text-sm text-muted-foreground">
            Vídeos e cortes excluídos ficam aqui por 30 dias e podem ser restaurados. Depois disso são apagados de vez.
          </p>
        </div>
        {itens?.length === 0 && (
          <div className="grid place-items-center gap-2 rounded-xl border border-dashed p-10 text-center text-sm text-muted-foreground">
            <Trash2 className="size-6" /> A lixeira está vazia.
          </div>
        )}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {itens?.map((i) => (
            <Card key={i.id} size="sm">
              <CardContent className="flex gap-3">
                <div className="grid aspect-[9/16] w-16 shrink-0 place-items-center overflow-hidden rounded-md border bg-muted">
                  {i.thumb_url ? <img src={i.thumb_url} alt="" className="h-full w-full object-cover" /> : <Film className="size-5 text-muted-foreground" />}
                </div>
                <div className="flex min-w-0 flex-1 flex-col gap-1">
                  <div className="flex items-center gap-1.5">
                    <Badge variant="outline">{i.tipo === 'video' ? <><Film className="size-3" /> vídeo</> : <><Scissors className="size-3" /> corte</>}</Badge>
                    <span className="text-xs text-muted-foreground">{megas(i.tamanho)}</span>
                  </div>
                  <span className="truncate text-sm font-medium" title={i.titulo}>{i.titulo}</span>
                  {i.tipo === 'corte' && <span className="truncate text-xs text-muted-foreground" title={i.entrada}>de {i.entrada}</span>}
                  {i.tipo === 'video' && <span className="text-xs text-muted-foreground">{i.cortes} cortes</span>}
                  <span className="text-xs text-muted-foreground">Excluído em {quando(i.excluido_em)}</span>
                  <span className="text-xs text-amber-400">Apagado de vez em {diasAte(i.expira_em)} dias ({quando(i.expira_em)})</span>
                  <div className="mt-1 flex gap-1">
                    <Button size="sm" variant="outline" onClick={() => restaurar(i)}><RotateCcw className="size-3" /> Restaurar</Button>
                    <Button size="sm" variant="ghost" className="text-destructive" onClick={() => setApagando(i)}><Trash2 className="size-3" /> Apagar de vez</Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="flex items-center gap-2 text-lg font-semibold"><History className="size-4" /> Histórico</h2>
        {registro.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nenhuma exclusão registrada ainda.</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 font-medium">Data e hora</th>
                  <th className="px-3 py-2 font-medium">Ação</th>
                  <th className="px-3 py-2 font-medium">Tipo</th>
                  <th className="px-3 py-2 font-medium">Vídeo</th>
                </tr>
              </thead>
              <tbody>
                {registro.map((h, n) => (
                  <tr key={`${h.em}-${h.item}-${n}`} className="border-t">
                    <td className="whitespace-nowrap px-3 py-2 font-mono text-xs">{quando(h.em)}</td>
                    <td className={`whitespace-nowrap px-3 py-2 ${ACAO[h.acao]?.classe ?? ''}`}>{ACAO[h.acao]?.texto ?? h.acao}</td>
                    <td className="px-3 py-2">{h.tipo === 'video' ? 'vídeo' : 'corte'}</td>
                    <td className="max-w-[28rem] px-3 py-2">
                      <div className="truncate" title={h.titulo}>{h.titulo}</div>
                      {h.tipo === 'corte' && <div className="truncate text-xs text-muted-foreground" title={h.entrada}>{h.entrada}</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <Confirmar
        aberto={apagando !== null}
        titulo="Apagar de vez?"
        descricao={`"${apagando?.titulo}" vai ser apagado do disco e não dá para desfazer.`}
        acao="Apagar de vez"
        perigo
        onConfirmar={async () => { if (apagando) await apagar(apagando) }}
        onFechar={() => setApagando(null)}
      />
    </div>
  )
}
