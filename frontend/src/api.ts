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
}

export type Job = {
  id: string
  entrada: string
  monitorar: boolean
  status: 'rodando' | 'concluido' | 'erro' | 'parado' | 'interrompido'
  criado_em: string
  cortes: Corte[]
  log: string | string[]
}

export type Estrategia = { nome: string; texto: string }

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
}

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
