// 与 AROS FastAPI 桥接服务返回结构对应的类型
export interface Stock {
  code: string
  name: string
}

export interface Bar {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  amount: number
  change?: number | null
  pct?: number | null
}

export interface IndexSnap {
  code: string
  name: string
  close: number
  pct: number
  date: string
}

export interface AlphaRow {
  rank: number
  code: string
  name: string
  alpha: number
  entry: number
  strategyHit: number
  context: string
  action: 'BUY' | 'HOLD' | 'WATCH' | 'SELL'
}

export interface FactorLast {
  ma_dist_20?: number | null
  macd_cross?: number | null
  kdj_cross?: number | null
  rsi_signal_14?: number | null
  boll_pos_20?: number | null
  mom_5?: number | null
  vol_ratio_5?: number | null
  ma_cross_5_20?: number | null
}

export interface ApiState {
  mode: 'live' | 'mock'
  message?: string
}
