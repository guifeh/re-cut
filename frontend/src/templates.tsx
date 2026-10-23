import { useEffect, useState, type CSSProperties, type ReactNode } from 'react'
import { toast } from 'sonner'
import { Copy, Pencil, Plus, Upload } from 'lucide-react'
import { api, upload, type Efeito, type OpcoesTemplate, type Som, type Template, type TipoMomento } from '@/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'

const TAMANHOS: Record<Template['proporcao'], [number, number]> = { '9:16': [1080, 1920], '1:1': [1080, 1080], '4:5': [1080, 1350], '16:9': [1920, 1080] }
const ENQUADRAMENTO: Record<Template['enquadramento'], string> = {
  rosto: 'Seguir o rosto',
  rosto_fixo: 'Rosto, câmera parada',
  centro: 'Centro',
  ajustar: 'Vídeo inteiro (fundo desfocado)',
}
const ANIMACAO: Record<Template['legenda']['animacao'], string> = { nenhuma: 'Nenhuma', pop: 'Pop', fade: 'Fade' }
const POSICAO_LOGO: Record<Template['logo']['posicao'], string> = {
  'topo-direita': 'Topo direita',
  'topo-esquerda': 'Topo esquerda',
  'base-direita': 'Base direita',
  'base-esquerda': 'Base esquerda',
}
const FRASE = ['esse', 'foi', 'o', 'melhor', 'momento', 'da', 'live']
export const TIPO_MOMENTO: Record<TipoMomento, { nome: string; dica: string }> = {
  risada: { nome: 'Risada', dica: 'alguém ri ou algo é claramente engraçado' },
  reacao: { nome: 'Reação', dica: 'surpresa, choque, grito, susto' },
  enfase: { nome: 'Ênfase', dica: 'frase de efeito, número ou afirmação forte' },
  punchline: { nome: 'Punchline', dica: 'o desfecho de uma piada ou história' },
  virada: { nome: 'Virada', dica: 'mudança brusca de assunto ou reviravolta' },
}
const EFEITO: Record<Efeito, string> = { zoom: 'Zoom no rosto', som: 'Som', emoji: 'Emoji', flash: 'Flash' }

const hexA = (hex: string, opacidade: number) => `${hex}${Math.round((opacidade / 100) * 255).toString(16).padStart(2, '0')}`

/** Aproximação em CSS do que o libass desenha: mesma escala (PlayRes), posições em % e cores do template. */
export function PreviaTemplate({ t, largura, animado = false, titulo = 'Título do corte aqui', logoUrl }: {
  t: Template
  largura: number
  animado?: boolean
  titulo?: string
  logoUrl?: string
}) {
  const [W, H] = TAMANHOS[t.proporcao]
  const k = largura / W
  const [passo, setPasso] = useState(0)
  useEffect(() => {
    if (!animado) return
    const id = setInterval(() => setPasso((p) => p + 1), 450)
    return () => clearInterval(id)
  }, [animado])

  const n = t.legenda.palavras_por_grupo
  const grupo = Math.floor((passo % FRASE.length) / n) * n
  const palavras = animado ? FRASE.slice(grupo, grupo + n) : FRASE.slice(3, 3 + n)
  const ativa = animado ? (passo % FRASE.length) - grupo : 0
  const leg = t.legenda
  const caixa = leg.fundo
  const estiloLegenda: CSSProperties = {
    top: `${leg.posicao_y}%`,
    fontFamily: `"${leg.fonte}", Arial, sans-serif`,
    fontSize: leg.tamanho * k,
    fontWeight: leg.negrito ? 900 : 400,
    fontStyle: leg.italico ? 'italic' : 'normal',
    textTransform: leg.maiusculas ? 'uppercase' : 'none',
    color: leg.cor,
    lineHeight: 1.15,
    ...(caixa
      ? { background: hexA(leg.fundo_cor, leg.fundo_opacidade), padding: `${4 * k * 3}px ${12 * k * 3}px`, borderRadius: 4 }
      : {
          WebkitTextStroke: `${leg.contorno * k * 2}px ${leg.contorno_cor}`,
          paintOrder: 'stroke fill',
          textShadow: leg.sombra ? `0 ${leg.sombra * k * 2}px ${leg.sombra * k * 2}px #0009` : undefined,
        }),
  }

  return (
    <div className="relative shrink-0 overflow-hidden rounded-lg bg-zinc-800" style={{ width: largura, height: (largura * H) / W }}>
      {/* "vídeo" de exemplo: gradiente + silhueta; no modo ajustar, o quadro 16:9 sobre a versão desfocada */}
      <div className="absolute inset-0 bg-gradient-to-b from-sky-900 via-slate-700 to-amber-900" />
      {t.enquadramento === 'ajustar' ? (
        <>
          <div className="absolute inset-0 bg-gradient-to-b from-sky-900 via-slate-700 to-amber-900 blur-md" />
          <div className="absolute inset-x-0 top-1/2 aspect-video -translate-y-1/2 overflow-hidden bg-gradient-to-br from-slate-600 to-slate-800">
            <Silhueta />
          </div>
        </>
      ) : (
        <Silhueta />
      )}
      {t.titulo.ativo && (
        <div className="absolute inset-x-[7%] -translate-y-1/2 text-center" style={{ top: `${t.titulo.posicao_y}%` }}>
          <span
            className="inline px-1 leading-snug [box-decoration-break:clone]"
            style={{
              background: t.titulo.fundo_cor,
              color: t.titulo.cor,
              fontFamily: `"${leg.fonte}", Arial, sans-serif`,
              fontWeight: 800,
              fontSize: t.titulo.tamanho * k,
              textTransform: leg.maiusculas ? 'uppercase' : 'none',
              padding: `${2 * k * 6}px ${6 * k * 6}px`,
            }}
          >
            {titulo}
          </span>
        </div>
      )}
      {leg.ativa && (
        <div
          key={animado && leg.animacao !== 'nenhuma' ? grupo : 'fixo'}
          className={`absolute left-1/2 max-w-[90%] -translate-x-1/2 -translate-y-1/2 text-center ${animado ? { nenhuma: '', pop: 'animate-[pop_.12s_ease-out]', fade: 'animate-[fadein_.15s_ease-out]' }[leg.animacao] : ''}`}
          style={estiloLegenda}
        >
          {palavras.map((p, i) => (
            <span key={i} style={leg.destaque && i === ativa ? { color: leg.destaque_cor } : undefined}>
              {p}
              {i < palavras.length - 1 ? ' ' : ''}
            </span>
          ))}
        </div>
      )}
      {(t.logo.arquivo || logoUrl) && (
        <div
          className="absolute grid place-items-center overflow-hidden rounded bg-white/85 text-[8px] font-bold text-black"
          style={{
            width: `${t.logo.largura}%`,
            aspectRatio: logoUrl ? undefined : '2 / 1',
            [t.logo.posicao.startsWith('topo') ? 'top' : 'bottom']: 40 * k,
            [t.logo.posicao.endsWith('direita') ? 'right' : 'left']: 40 * k,
          }}
        >
          {logoUrl ? <img src={logoUrl} alt="logo" className="w-full" /> : 'LOGO'}
        </div>
      )}
      {t.velocidade !== 1 && <span className="absolute bottom-1 left-1 rounded bg-black/60 px-1 text-[9px] text-white">{t.velocidade}x</span>}
    </div>
  )
}

function Silhueta() {
  return (
    <div className="absolute bottom-0 left-1/2 h-[62%] w-[70%] -translate-x-1/2">
      <div className="mx-auto aspect-square w-[38%] rounded-full bg-black/35" />
      <div className="mx-auto mt-[4%] h-full w-full rounded-t-[45%] bg-black/35" />
    </div>
  )
}

export function Templates({ templates, onSalvo }: { templates: Template[]; onSalvo: (t: Template) => void }) {
  const [opcoes, setOpcoes] = useState<OpcoesTemplate | null>(null)
  const [editando, setEditando] = useState<Template | null>(null)
  useEffect(() => {
    api.opcoesTemplate().then(setOpcoes).catch(() => toast.error('Não foi possível carregar as opções de template'))
  }, [])

  const copiar = (t: Template) => structuredClone(t)

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Templates de corte</h2>
          <p className="text-sm text-muted-foreground">Formato, enquadramento e estilo da legenda. Escolha um ao clipar ou aplique em cortes prontos.</p>
        </div>
        <Button disabled={!opcoes} onClick={() => opcoes && setEditando({ ...copiar(opcoes.padrao), nome: '' })}>
          <Plus className="size-4" /> Novo template
        </Button>
      </div>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        {templates.map((t) => (
          <Card key={t.nome} size="sm" className="gap-2 pt-0">
            <div className="grid place-items-center bg-muted/40 p-3">
              <PreviaTemplate t={t} largura={150} />
            </div>
            <CardContent className="flex flex-1 flex-col gap-2">
              <div className="flex items-center justify-between gap-2">
                <span className="truncate font-medium">{t.nome}</span>
                <Badge variant="outline">{t.proporcao}</Badge>
              </div>
              <p className="line-clamp-3 text-xs text-muted-foreground">{t.descricao || ENQUADRAMENTO[t.enquadramento]}</p>
              {t.efeitos.ativo && <Badge variant="secondary" className="self-start">efeitos automáticos</Badge>}
              <div className="mt-auto flex gap-1">
                <Button variant="ghost" size="sm" onClick={() => setEditando(copiar(t))}><Pencil className="size-3" /> Editar</Button>
                <Button variant="ghost" size="sm" onClick={() => setEditando({ ...copiar(t), nome: `${t.nome}-copia` })}><Copy className="size-3" /> Duplicar</Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
      {editando && opcoes && (
        <EditorTemplate
          inicial={editando}
          opcoes={opcoes}
          onFechar={() => setEditando(null)}
          onSalvo={(t) => {
            onSalvo(t)
            setEditando(null)
          }}
        />
      )}
    </div>
  )
}

function EditorTemplate({ inicial, opcoes, onFechar, onSalvo }: {
  inicial: Template
  opcoes: OpcoesTemplate
  onFechar: () => void
  onSalvo: (t: Template) => void
}) {
  const [t, setT] = useState<Template>(inicial)
  const [logoUrl, setLogoUrl] = useState<string>()
  const [salvando, setSalvando] = useState(false)
  const leg = <K extends keyof Template['legenda']>(k: K, v: Template['legenda'][K]) => setT((x) => ({ ...x, legenda: { ...x.legenda, [k]: v } }))
  const tit = <K extends keyof Template['titulo']>(k: K, v: Template['titulo'][K]) => setT((x) => ({ ...x, titulo: { ...x.titulo, [k]: v } }))
  const logo = <K extends keyof Template['logo']>(k: K, v: Template['logo'][K]) => setT((x) => ({ ...x, logo: { ...x.logo, [k]: v } }))
  const efe = <K extends keyof Template['efeitos']>(k: K, v: Template['efeitos'][K]) => setT((x) => ({ ...x, efeitos: { ...x.efeitos, [k]: v } }))
  const [sons, setSons] = useState<Som[]>([])
  useEffect(() => {
    api.sons().then(setSons).catch(() => {})
  }, [])
  const alternarEfeito = (tipo: TipoMomento, e: Efeito) => {
    const atuais = t.efeitos.regras[tipo] ?? []
    const ligando = !atuais.includes(e)
    setT((x) => ({
      ...x,
      efeitos: {
        ...x.efeitos,
        regras: { ...x.efeitos.regras, [tipo]: ligando ? [...atuais, e] : atuais.filter((y) => y !== e) },
        // ligou "som" num tipo sem som escolhido: grava o padrão em vez de só mostrar um que não seria salvo
        sons: ligando && e === 'som' && !x.efeitos.sons[tipo] ? { ...x.efeitos.sons, [tipo]: opcoes.padrao.efeitos.sons[tipo] ?? sons[0]?.id } : x.efeitos.sons,
      },
    }))
  }

  async function enviarLogo(f: File | undefined) {
    if (!f) return
    try {
      setLogoUrl(URL.createObjectURL(f))
      logo('arquivo', await upload(f, () => {}))
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  async function salvar() {
    if (!t.nome.trim()) return toast.error('Dê um nome ao template')
    setSalvando(true)
    try {
      const salvo = await api.salvarTemplate(t)
      toast.success(`Template "${salvo.nome}" salvo`, { description: 'Ele já aparece na lista na hora de clipar ou aplicar nos cortes.' })
      onSalvo(salvo)
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setSalvando(false)
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onFechar()}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle>{inicial.nome ? `Editar ${inicial.nome}` : 'Novo template'}</DialogTitle>
          <DialogDescription>A prévia é uma aproximação; o corte final é desenhado pelo ffmpeg com as mesmas medidas.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-6 md:grid-cols-[1fr_auto]">
          <div className="flex flex-col gap-5">
            <Secao titulo="Geral">
              <Campo label="Nome"><Input value={t.nome} onChange={(e) => setT({ ...t, nome: e.target.value })} placeholder="meu-template" /></Campo>
              <Campo label="Descrição" largo><Textarea rows={2} value={t.descricao} onChange={(e) => setT({ ...t, descricao: e.target.value })} /></Campo>
            </Secao>

            <Secao titulo="Formato">
              <Campo label="Proporção">
                <Escolha valor={t.proporcao} itens={opcoes.proporcoes.map((p) => [p, p])} onChange={(v) => setT({ ...t, proporcao: v })} />
              </Campo>
              <Campo label="Enquadramento">
                <Escolha valor={t.enquadramento} itens={opcoes.enquadramentos.map((e) => [e, ENQUADRAMENTO[e]])} onChange={(v) => setT({ ...t, enquadramento: v })} />
              </Campo>
              <Faixa label={`Velocidade ${t.velocidade}x`} min={0.5} max={2} step={0.05} valor={t.velocidade} onChange={(v) => setT({ ...t, velocidade: v })} />
            </Secao>

            <Secao titulo="Legenda" chave={<Switch checked={t.legenda.ativa} onCheckedChange={(v) => leg('ativa', v)} />}>
              {t.legenda.ativa && (
                <>
                  <Campo label="Fonte">
                    <Escolha valor={t.legenda.fonte} itens={opcoes.fontes.map((f) => [f, f])} onChange={(v) => leg('fonte', v)} />
                  </Campo>
                  <Campo label="Animação de entrada">
                    <Escolha valor={t.legenda.animacao} itens={opcoes.animacoes.map((a) => [a, ANIMACAO[a]])} onChange={(v) => leg('animacao', v)} />
                  </Campo>
                  <Faixa label={`Tamanho ${t.legenda.tamanho}`} min={20} max={200} valor={t.legenda.tamanho} onChange={(v) => leg('tamanho', v)} />
                  <Faixa label={`Posição vertical ${t.legenda.posicao_y}%`} min={5} max={95} valor={t.legenda.posicao_y} onChange={(v) => leg('posicao_y', v)} />
                  <Faixa label={`Palavras por vez: ${t.legenda.palavras_por_grupo}`} min={1} max={12} valor={t.legenda.palavras_por_grupo} onChange={(v) => leg('palavras_por_grupo', v)} />
                  <Cor label="Cor do texto" valor={t.legenda.cor} onChange={(v) => leg('cor', v)} />
                  <Faixa label={`Pausa que quebra o bloco: ${t.legenda.pausa_max}s`} min={0} max={2} step={0.1} valor={t.legenda.pausa_max} onChange={(v) => leg('pausa_max', v)} />
                  <Liga label="Negrito" valor={t.legenda.negrito} onChange={(v) => leg('negrito', v)} />
                  <Liga label="Itálico" valor={t.legenda.italico} onChange={(v) => leg('italico', v)} />
                  <Liga label="MAIÚSCULAS" valor={t.legenda.maiusculas} onChange={(v) => leg('maiusculas', v)} />
                  <Liga label="Quebrar no fim da frase" valor={t.legenda.respeitar_pontuacao} onChange={(v) => leg('respeitar_pontuacao', v)} />
                  <Liga label="Destacar a palavra falada" valor={t.legenda.destaque} onChange={(v) => leg('destaque', v)} />
                  {t.legenda.destaque && <Cor label="Cor do destaque" valor={t.legenda.destaque_cor} onChange={(v) => leg('destaque_cor', v)} />}
                  <Liga label="Caixa atrás do texto" valor={t.legenda.fundo} onChange={(v) => leg('fundo', v)} />
                  {t.legenda.fundo ? (
                    <>
                      <Cor label="Cor da caixa" valor={t.legenda.fundo_cor} onChange={(v) => leg('fundo_cor', v)} />
                      <Faixa label={`Opacidade da caixa ${t.legenda.fundo_opacidade}%`} min={0} max={100} valor={t.legenda.fundo_opacidade} onChange={(v) => leg('fundo_opacidade', v)} />
                    </>
                  ) : (
                    <>
                      <Cor label="Cor do contorno" valor={t.legenda.contorno_cor} onChange={(v) => leg('contorno_cor', v)} />
                      <Faixa label={`Contorno ${t.legenda.contorno}`} min={0} max={20} valor={t.legenda.contorno} onChange={(v) => leg('contorno', v)} />
                      <Faixa label={`Sombra ${t.legenda.sombra}`} min={0} max={10} valor={t.legenda.sombra} onChange={(v) => leg('sombra', v)} />
                    </>
                  )}
                </>
              )}
            </Secao>

            <Secao titulo="Título do corte" chave={<Switch checked={t.titulo.ativo} onCheckedChange={(v) => tit('ativo', v)} />}>
              {t.titulo.ativo && (
                <>
                  <Faixa label={t.titulo.segundos ? `Aparece nos primeiros ${t.titulo.segundos}s` : 'Aparece o corte todo'} min={0} max={15} valor={t.titulo.segundos} onChange={(v) => tit('segundos', v)} />
                  <Faixa label={`Posição vertical ${t.titulo.posicao_y}%`} min={5} max={95} valor={t.titulo.posicao_y} onChange={(v) => tit('posicao_y', v)} />
                  <Faixa label={`Tamanho ${t.titulo.tamanho}`} min={20} max={200} valor={t.titulo.tamanho} onChange={(v) => tit('tamanho', v)} />
                  <Cor label="Cor do texto" valor={t.titulo.cor} onChange={(v) => tit('cor', v)} />
                  <Cor label="Cor da faixa" valor={t.titulo.fundo_cor} onChange={(v) => tit('fundo_cor', v)} />
                </>
              )}
            </Secao>

            <Secao titulo="Efeitos automáticos" chave={<Switch checked={t.efeitos.ativo} onCheckedChange={(v) => efe('ativo', v)} />}>
              {t.efeitos.ativo ? (
                <>
                  <p className="text-xs text-muted-foreground sm:col-span-2">
                    A IA marca os momentos de cada corte; aqui você escolhe o que acontece em cada tipo.
                  </p>
                  <Faixa label={`Só momentos com intensidade ${t.efeitos.intensidade_min}+ (de 3)`} min={1} max={3} valor={t.efeitos.intensidade_min} onChange={(v) => efe('intensidade_min', v)} />
                  <Faixa label={`Força do zoom ${t.efeitos.zoom.toFixed(2)}x`} min={1.05} max={2} step={0.05} valor={t.efeitos.zoom} onChange={(v) => efe('zoom', v)} />
                  <div className="flex flex-col gap-2 sm:col-span-2">
                    {opcoes.tipos_momento.map((tipo) => {
                      const ativos = t.efeitos.regras[tipo] ?? []
                      return (
                        <div key={tipo} className="flex flex-wrap items-center gap-2 rounded-md border px-3 py-2">
                          <div className="mr-auto min-w-36">
                            <div className="text-sm font-medium">{TIPO_MOMENTO[tipo].nome}</div>
                            <div className="text-xs text-muted-foreground">{TIPO_MOMENTO[tipo].dica}</div>
                          </div>
                          {opcoes.efeitos.map((e) => (
                            <button
                              key={e}
                              type="button"
                              onClick={() => alternarEfeito(tipo, e)}
                              className={`rounded-full border px-2.5 py-1 text-xs transition-colors ${ativos.includes(e) ? 'border-primary bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`}
                            >
                              {EFEITO[e]}
                            </button>
                          ))}
                          {ativos.includes('som') && sons.length > 0 && (
                            <div className="w-44">
                              <EscolhaSom sons={sons} valor={t.efeitos.sons[tipo] ?? ''} onChange={(v) => efe('sons', { ...t.efeitos.sons, [tipo]: v })} />
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                </>
              ) : (
                <p className="text-xs text-muted-foreground sm:col-span-2">Zoom no rosto, sons, emojis e flash nos momentos engraçados, de reação e de ênfase que a IA marcar.</p>
              )}
            </Secao>

            <Secao titulo="Logo / marca d'água">
              <Campo label="Imagem (PNG com fundo transparente)">
                <label className="flex cursor-pointer items-center gap-2 rounded-lg border border-dashed px-3 py-2 text-sm text-muted-foreground hover:text-foreground">
                  <Upload className="size-4" /> {t.logo.arquivo ? 'Trocar logo' : 'Enviar logo'}
                  <input type="file" accept="image/png,image/jpeg,image/webp" className="sr-only" onChange={(e) => enviarLogo(e.target.files?.[0])} />
                </label>
              </Campo>
              {t.logo.arquivo && (
                <>
                  <Campo label="Posição">
                    <Escolha valor={t.logo.posicao} itens={opcoes.posicoes_logo.map((p) => [p, POSICAO_LOGO[p]])} onChange={(v) => logo('posicao', v)} />
                  </Campo>
                  <Faixa label={`Largura ${t.logo.largura}%`} min={5} max={60} valor={t.logo.largura} onChange={(v) => logo('largura', v)} />
                  <Button variant="ghost" size="sm" className="self-start" onClick={() => { logo('arquivo', ''); setLogoUrl(undefined) }}>Remover logo</Button>
                </>
              )}
            </Secao>
          </div>

          <div className="flex flex-col items-center gap-3 md:sticky md:top-0 md:self-start">
            <PreviaTemplate t={t} largura={t.proporcao === '16:9' ? 360 : 240} animado logoUrl={logoUrl} />
            <Button className="w-full" onClick={salvar} disabled={salvando}>{salvando ? 'Salvando…' : 'Salvar template'}</Button>
            <Button className="w-full" variant="ghost" onClick={onFechar}>Cancelar</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function Secao({ titulo, chave, children }: { titulo: string; chave?: ReactNode; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3 rounded-lg border p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">{titulo}</h3>
        {chave}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">{children}</div>
    </section>
  )
}

function Campo({ label, largo, children }: { label: string; largo?: boolean; children: ReactNode }) {
  return (
    <div className={`flex flex-col gap-1.5 ${largo ? 'sm:col-span-2' : ''}`}>
      <Label className="text-xs text-muted-foreground">{label}</Label>
      {children}
    </div>
  )
}

function Escolha<T extends string>({ valor, itens, onChange }: { valor: T; itens: [T, string][]; onChange: (v: T) => void }) {
  const lista = itens.map(([value, label]) => ({ value, label }))
  return (
    <Select items={lista} value={valor} onValueChange={(v) => onChange(v as T)}>
      <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
      <SelectContent>{lista.map((i) => <SelectItem key={i.value} value={i.value}>{i.label}</SelectItem>)}</SelectContent>
    </Select>
  )
}

/** biblioteca de sons agrupada por categoria (efeitos/<categoria>/<nome>), como a do cut.pro */
function EscolhaSom({ sons, valor, onChange }: { sons: Som[]; valor: string; onChange: (v: string) => void }) {
  const categorias = [...new Set(sons.map((s) => s.categoria))]
  return (
    <Select items={sons.map((s) => ({ value: s.id, label: `${s.categoria} · ${s.nome}` }))} value={valor} onValueChange={(v) => onChange(String(v))}>
      <SelectTrigger className="w-full"><SelectValue placeholder="Escolha um som" /></SelectTrigger>
      <SelectContent>
        {categorias.map((c) => (
          <SelectGroup key={c}>
            <SelectLabel>{c}</SelectLabel>
            {sons.filter((s) => s.categoria === c).map((s) => <SelectItem key={s.id} value={s.id}>{s.nome}</SelectItem>)}
          </SelectGroup>
        ))}
      </SelectContent>
    </Select>
  )
}

function Faixa({ label, min, max, step = 1, valor, onChange }: { label: string; min: number; max: number; step?: number; valor: number; onChange: (v: number) => void }) {
  return (
    <Campo label={label}>
      <input type="range" min={min} max={max} step={step} value={valor} onChange={(e) => onChange(Number(e.target.value))} className="h-8 w-full accent-primary" />
    </Campo>
  )
}

function Cor({ label, valor, onChange }: { label: string; valor: string; onChange: (v: string) => void }) {
  return (
    <Campo label={label}>
      <div className="flex items-center gap-2">
        <input type="color" value={valor} onChange={(e) => onChange(e.target.value.toUpperCase())} className="h-8 w-10 cursor-pointer rounded border bg-transparent" />
        <Input value={valor} onChange={(e) => /^#[0-9a-fA-F]{0,6}$/.test(e.target.value) && onChange(e.target.value.toUpperCase())} className="font-mono" />
      </div>
    </Campo>
  )
}

function Liga({ label, valor, onChange }: { label: string; valor: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center justify-between gap-3 rounded-md border px-3 py-2 text-sm">
      {label}
      <Switch checked={valor} onCheckedChange={(v) => onChange(v)} />
    </label>
  )
}
