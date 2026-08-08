import type { AlphaRow, Bar, IndexSnap, Stock } from './types'

const API_BASE = import.meta.env.VITE_API_BASE || ''

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return (await res.json()) as T
}

export interface Health {
  status: string
  data_source: string
  stock_count: number
  indicators: string[]
  factors: string[]
}
export interface BarsResp {
  empty: boolean
  code: string
  bars: Bar[]
  last?: Bar | null
  message?: string
}
export interface FrameResp {
  empty: boolean
  code: string
  columns: string[]
  rows: Record<string, any>[]
  message?: string
}
export interface MarketResp {
  empty: boolean
  indices: IndexSnap[]
}
export interface StocksResp {
  empty: boolean
  stocks: Stock[]
}

export const api = {
  health: () => getJSON<Health>('/api/health'),
  stocks: () => getJSON<StocksResp>('/api/stocks'),
  bars: (code: string, limit = 180) => getJSON<BarsResp>(`/api/bars/${code}?limit=${limit}`),
  indicators: (code: string) => getJSON<FrameResp>(`/api/indicators/${code}`),
  factors: (code: string) => getJSON<FrameResp>(`/api/factors/${code}`),
  market: () => getJSON<MarketResp>('/api/market'),
}
