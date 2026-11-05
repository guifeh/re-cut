import type { EstadoPlataforma, Plataforma } from '@/api'

export const PLATAFORMAS: Plataforma[] = ['youtube', 'instagram', 'tiktok']
export const NOME_PLATAFORMA: Record<Plataforma, string> = { youtube: 'YouTube', instagram: 'Instagram', tiktok: 'TikTok' }
/** cor do texto do estado de publicação de um corte numa plataforma */
export const COR_PUBLICACAO: Record<EstadoPlataforma['estado'], string> = {
  ok: 'text-emerald-500',
  erro: 'text-destructive',
  incerto: 'text-destructive',
  enviando: 'text-muted-foreground',
  manual: 'text-muted-foreground',
}
