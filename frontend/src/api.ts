export type Corte = {
  inicio: number
  fim: number
  titulo: string
  descricao: string
  nota: number
  motivo: string
  hashtags: string[]
  duracao: number
  lote: string
  criado_em: string
  video_url: string
  thumb_url: string
  /** nome do .mp4 do corte (sem pasta) */
  arquivo: string
  json: string
  template?: string
  momentos?: Momento[]
  reaplicavel: boolean
  /** identidade do corte: caminho relativo ao job sem .json (único mesmo com lotes de mesmo nome em transmissões diferentes);
   * é o item da esteira na aprovação e nas plataformas. Para mostrar, use o título */
  nome: string
  /** 3 opções de legenda da IA (cortes antigos não têm) */
  legendas?: string[]
  publicacao?: Publicacao
}

export type Plataforma = 'youtube' | 'instagram' | 'tiktok'
export type EstadoPlataforma = {
  estado: 'enviando' | 'ok' | 'erro' | 'incerto' | 'manual'
  link: string | null
  erro: string | null
  em: string
}
/** {} enquanto o corte não foi aprovado */
export type Publicacao = {
  aprovado_em?: string
  legenda?: string
  hashtags?: string[]
  plataformas?: Partial<Record<Plataforma, EstadoPlataforma>>
  /** ausente se o Telegram não estava pareado na aprovação */
  telegram?: { estado: 'enviando' | 'ok' | 'erro' | 'incerto'; erro: string | null; em: string; mensagens: number[]; bot?: string | null; chat_id?: number | null; outro_bot?: boolean }
}

export type ContaTelegram = {
  plataforma: 'telegram'
  configurada: boolean
  conectada: boolean
  nome: string | null
  bot?: string | null
  link_pareamento?: string | null
}
export type Conta = ContaOAuth | ContaTelegram
export type ContaOAuth = {
  plataforma: 'youtube' | 'instagram'
  configurada: boolean
  conectada: boolean
  nome: string | null
  vence_em: string | null
  dias_restantes: number | null
}

export type IdNo = 'entrada' | 'baixar' | 'transcrever' | 'ia' | 'renderizar' | 'ranking' | 'aprovacao' | Plataforma
export type EstadoNo = 'ocioso' | 'rodando' | 'ok' | 'erro' | 'esperando'
/** progresso de 0 a 1; itens = vídeos/lotes (etapas) ou nomes de cortes (aprovação e plataformas) */
export type NoEsteira = { estado: EstadoNo; progresso: number | null; itens: string[]; msg: string }
export type ItemFeed = { t: string; etapa: string; msg: string; estado: string }
/** arestas: "origem-destino" -> quantos itens passaram */
export type Esteira = { nos: Record<IdNo, NoEsteira>; arestas: Record<string, number>; feed: ItemFeed[] }
export type ResumoDoDia = { cortes: number; aprovados: number; postados: number; erros: number }

export type Job = {
  id: string
  entrada: string
  monitorar: boolean
  status: 'rodando' | 'concluido' | 'erro' | 'parado' | 'interrompido'
  criado_em: string
  cortes: Corte[]
  log: string | string[]
  reaplicando: boolean
}

export type Estrategia = { nome: string; texto: string }

/** item da lixeira (safe-delete): vídeo inteiro ou um corte, guardado por 30 dias */
export type ItemLixeira = {
  id: string
  tipo: 'video' | 'corte'
  job_id: string
  titulo: string
  entrada: string
  excluido_em: string
  expira_em: string
  tamanho: number
  cortes?: number
  nota?: number
  thumb_url: string | null
}

/** linha do histórico da lixeira: o que aconteceu, quando e com qual vídeo */
export type EventoLixeira = {
  em: string
  acao: 'excluido' | 'restaurado' | 'apagado' | 'expirado'
  tipo: 'video' | 'corte'
  item: string
  titulo: string
  entrada: string
  job_id: string
}

export type TipoMomento = 'risada' | 'reacao' | 'enfase' | 'punchline' | 'virada'
export type Efeito = 'zoom' | 'som' | 'emoji' | 'flash'
/** momento marcado pela IA dentro do corte; t em segundos do vídeo de origem */
export type Momento = { t: number; tipo: TipoMomento; intensidade: number; emoji: string }
/** som da biblioteca efeitos/<categoria>/<nome>; id = "categoria/nome" */
export type Som = { id: string; categoria: string; nome: string }

export type Template = {
  nome: string
  descricao: string
  proporcao: '9:16' | '1:1' | '4:5' | '16:9'
  enquadramento: 'rosto' | 'rosto_fixo' | 'centro' | 'ajustar'
  velocidade: number
  legenda: {
    ativa: boolean
    palavras_por_grupo: number
    pausa_max: number
    respeitar_pontuacao: boolean
    fonte: string
    tamanho: number
    negrito: boolean
    italico: boolean
    maiusculas: boolean
    cor: string
    contorno_cor: string
    contorno: number
    sombra: number
    fundo: boolean
    fundo_cor: string
    fundo_opacidade: number
    destaque: boolean
    destaque_cor: string
    posicao_y: number
    animacao: 'nenhuma' | 'pop' | 'fade'
  }
  titulo: { ativo: boolean; segundos: number; tamanho: number; cor: string; fundo_cor: string; posicao_y: number }
  logo: { arquivo: string; largura: number; posicao: 'topo-direita' | 'topo-esquerda' | 'base-direita' | 'base-esquerda' }
  efeitos: {
    ativo: boolean
    intensidade_min: number
    zoom: number
    regras: Partial<Record<TipoMomento, Efeito[]>>
    sons: Partial<Record<TipoMomento, string>>
  }
}

export type OpcoesTemplate = {
  proporcoes: Template['proporcao'][]
  enquadramentos: Template['enquadramento'][]
  animacoes: Template['legenda']['animacao'][]
  fontes: string[]
  posicoes_logo: Template['logo']['posicao'][]
  padrao: Template
  tipos_momento: TipoMomento[]
  efeitos: Efeito[]
}

export type NovoJob = {
  entrada: string
  monitorar: boolean
  estrategia?: string
  nota_min?: number
  limite?: number
  dur_min?: number
  dur_max?: number
  dias?: number[]
  horas?: number[]
  webhook?: string
  template?: string
}

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init)
  const dados = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(dados.erro ?? `erro ${r.status}`)
  return dados as T
}

const post = <T,>(url: string, corpo: unknown) =>
  req<T>(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(corpo) })

export const api = {
  jobs: () => req<Job[]>('/api/jobs'),
  job: (id: string) => req<Job>(`/api/jobs/${id}`),
  criarJob: (j: NovoJob) => post<Job>('/api/jobs', j),
  pararJob: (id: string) => post<Job>(`/api/jobs/${id}/parar`, {}),
  estrategias: () => req<Estrategia[]>('/api/estrategias'),
  salvarEstrategia: (e: Estrategia) => post<Estrategia>('/api/estrategias', e),
  agentes: () => req<string[]>('/api/agentes'),
  templates: () => req<Template[]>('/api/templates'),
  opcoesTemplate: () => req<OpcoesTemplate>('/api/templates/opcoes'),
  sons: () => req<Som[]>('/api/efeitos/sons'),
  excluirJob: (id: string) => post<ItemLixeira>(`/api/jobs/${id}/excluir`, {}),
  excluirCorte: (jobId: string, json: string) => post<ItemLixeira>(`/api/jobs/${jobId}/cortes/excluir`, { json }),
  lixeira: () => req<{ retencao_dias: number; itens: ItemLixeira[] }>('/api/lixeira'),
  registroLixeira: () => req<EventoLixeira[]>('/api/lixeira/registro'),
  restaurar: (id: string) => post<ItemLixeira>(`/api/lixeira/${id}/restaurar`, {}),
  apagarDeVez: (id: string) => post<ItemLixeira>(`/api/lixeira/${id}/apagar`, {}),
  esteira: (jobId: string) => req<{ job: Job; esteira: Esteira }>(`/api/esteira/${jobId}`),
  resumoDoDia: () => req<ResumoDoDia>('/api/esteira/resumo'),
  aprovar: (jobId: string, json: string, legenda: string, hashtags: string[]) =>
    post<Publicacao>(`/api/jobs/${jobId}/cortes/aprovar`, { json, legenda, hashtags }),
  publicacao: (jobId: string, json: string, plataforma: Plataforma | 'telegram', acao: 'tentar' | 'forcar' | 'link', link?: string) =>
    post<Publicacao>(`/api/jobs/${jobId}/cortes/publicacao`, { json, plataforma, acao, link }),
  configurarTelegram: (token: string) => post<ContaTelegram>('/api/contas/telegram/configurar', { token }),
  desconectarTelegram: () => post<ContaTelegram>('/api/contas/telegram/desconectar', {}),
  contas: () => req<Conta[]>('/api/contas'),
  configurarConta: (p: ContaOAuth['plataforma'], client_id: string, client_secret: string) =>
    post<Conta>(`/api/contas/${p}/configurar`, { client_id, client_secret }),
  conectarConta: (p: ContaOAuth['plataforma']) => post<{ url: string }>(`/api/contas/${p}/conectar`, {}),
  codigoInstagram: (codigo: string) => post<Conta>('/api/contas/instagram/codigo', { codigo }),
  desconectarConta: (p: ContaOAuth['plataforma']) => post<Conta>(`/api/contas/${p}/desconectar`, {}),
  salvarTemplate: (t: Template) => post<Template>('/api/templates', t),
  aplicarTemplate: (jobId: string, template: string, cortes?: string[]) =>
    post<Job>(`/api/jobs/${jobId}/aplicar_template`, { template, cortes }),
}

/** id do job a partir da URL do corte (/files/jobs/<id>/...) */
export const nomeEntrada = (e: string) => (e.startsWith('http') ? e.replace(/^https?:\/\/(www\.)?/, '') : e.split(/[\\/]/).pop()!.replace(/^[0-9a-f]{8}-/, ''))
export const jobDoCorte = (c: Corte) => c.video_url.split('/')[3]

/** XHR em vez de fetch para ter progresso do upload (vídeos de live são grandes). */
export function upload(arquivo: File, onProgresso: (pct: number) => void) {
  return new Promise<string>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `/api/upload?nome=${encodeURIComponent(arquivo.name)}`)
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgresso(Math.round((e.loaded / e.total) * 100))
    xhr.onload = () => {
      const dados = JSON.parse(xhr.responseText || '{}')
      if (xhr.status < 300) resolve(dados.caminho)
      else reject(new Error(dados.erro ?? `erro ${xhr.status}`))
    }
    xhr.onerror = () => reject(new Error('falha de rede no upload'))
    xhr.send(arquivo)
  })
}

/** "18-23, 8" -> [8, 18, 19, 20, 21, 22, 23] */
export function parseHoras(texto: string): number[] {
  const horas = new Set<number>()
  for (const parte of texto.split(',').map((p) => p.trim()).filter(Boolean)) {
    const [a, b = a] = parte.split('-').map(Number)
    if (Number.isNaN(a) || Number.isNaN(b)) continue
    for (let h = Math.max(0, a); h <= Math.min(23, b); h++) horas.add(h)
  }
  return [...horas].sort((x, y) => x - y)
}
