import { useEffect, useRef, useState, type MouseEvent } from 'react'
import type { Bar } from '../types'

function cssVar(name: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return v || fallback
}

function sma(values: number[], w: number): (number | null)[] {
  const out: (number | null)[] = []
  let sum = 0
  for (let i = 0; i < values.length; i++) {
    sum += values[i]
    if (i >= w) sum -= values[i - w]
    out.push(i >= w - 1 ? sum / w : null)
  }
  return out
}

export default function CandleChart({ bars }: { bars: Bar[] }) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [hover, setHover] = useState<number | null>(null)
  const [size, setSize] = useState({ w: 600, h: 320 })

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const ro = new ResizeObserver((entries) => {
      const cr = entries[0].contentRect
      setSize({ w: Math.max(320, cr.width), h: 320 })
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || bars.length === 0) return
    const dpr = window.devicePixelRatio || 1
    const W = size.w
    const H = size.h
    canvas.width = W * dpr
    canvas.height = H * dpr
    canvas.style.width = W + 'px'
    canvas.style.height = H + 'px'
    const ctx = canvas.getContext('2d')!
    ctx.scale(dpr, dpr)

    const up = cssVar('--up', '#ef4444')
    const down = cssVar('--down', '#22c55e')
    const grid = cssVar('--grid', '#1a2030')
    const axis = cssVar('--axis', '#2a3342')
    const text = cssVar('--text-dim', '#6b7587')
    const textHi = cssVar('--text-hi', '#e6eaf2')
    const ma5c = cssVar('--warn', '#f59e0b')
    const ma20c = cssVar('--accent', '#3b82f6')

    const padL = 8
    const padR = 56
    const padT = 8
    const volH = 56
    const padB = 18
    const plotW = W - padL - padR
    const plotH = H - padT - volH - padB
    const volTop = padT + plotH + 8

    const highs = bars.map((b) => b.high)
    const lows = bars.map((b) => b.low)
    let min = Math.min(...lows)
    let max = Math.max(...highs)
    const pad = (max - min) * 0.08
    min -= pad
    max += pad

    const n = bars.length
    const step = plotW / n
    const cw = Math.max(1, step * 0.66)

    const yOf = (v: number) => padT + ((max - v) / (max - min)) * plotH
    const xOf = (i: number) => padL + i * step + step / 2

    // grid + y labels
    ctx.font = '10px ui-monospace, monospace'
    ctx.textBaseline = 'middle'
    for (let g = 0; g <= 4; g++) {
      const v = max - ((max - min) / 4) * g
      const y = yOf(v)
      ctx.strokeStyle = grid
      ctx.lineWidth = 1
      ctx.beginPath()
      ctx.moveTo(padL, y)
      ctx.lineTo(padL + plotW, y)
      ctx.stroke()
      ctx.fillStyle = text
      ctx.textAlign = 'left'
      ctx.fillText(v.toFixed(2), padL + plotW + 4, y)
    }

    const closes = bars.map((b) => b.close)
    const ma5 = sma(closes, 5)
    const ma20 = sma(closes, 20)

    // volume max
    const volMax = Math.max(...bars.map((b) => b.volume)) || 1

    bars.forEach((b, i) => {
      const x = xOf(i)
      const rising = b.close >= b.open
      const col = rising ? up : down
      // candle body
      const yO = yOf(b.open)
      const yC = yOf(b.close)
      const top = Math.min(yO, yC)
      const h = Math.max(1, Math.abs(yC - yO))
      ctx.fillStyle = col
      ctx.fillRect(x - cw / 2, top, cw, h)
      // wick
      ctx.strokeStyle = col
      ctx.lineWidth = 1
      ctx.beginPath()
      ctx.moveTo(x, yOf(b.high))
      ctx.lineTo(x, yOf(b.low))
      ctx.stroke()
      // volume
      const vh = (b.volume / volMax) * (volH - 4)
      ctx.globalAlpha = 0.5
      ctx.fillRect(x - cw / 2, volTop + (volH - vh), cw, vh)
      ctx.globalAlpha = 1
    })

    // MA lines
    const drawMa = (arr: (number | null)[], color: string) => {
      ctx.strokeStyle = color
      ctx.lineWidth = 1.4
      ctx.beginPath()
      let started = false
      arr.forEach((v, i) => {
        if (v == null) return
        const x = xOf(i)
        const y = yOf(v)
        if (!started) {
          ctx.moveTo(x, y)
          started = true
        } else ctx.lineTo(x, y)
      })
      ctx.stroke()
    }
    drawMa(ma5, ma5c)
    drawMa(ma20, ma20c)

    // crosshair
    if (hover != null && hover >= 0 && hover < n) {
      const x = xOf(hover)
      ctx.strokeStyle = axis
      ctx.setLineDash([3, 3])
      ctx.beginPath()
      ctx.moveTo(x, padT)
      ctx.lineTo(x, volTop + volH)
      ctx.stroke()
      ctx.setLineDash([])
    }

    // legend
    ctx.textAlign = 'left'
    ctx.fillStyle = ma5c
    ctx.fillText('MA5', padL + 2, padT + 6)
    ctx.fillStyle = ma20c
    ctx.fillText('MA20', padL + 38, padT + 6)
  }, [bars, size, hover])

  const onMove = (e: MouseEvent<HTMLCanvasElement>) => {
    const rect = wrapRef.current!.getBoundingClientRect()
    const x = e.clientX - rect.left
    const plotW = size.w - 8 - 56
    const step = plotW / Math.max(1, bars.length)
    const i = Math.floor((x - 8) / step)
    setHover(i >= 0 && i < bars.length ? i : null)
  }

  const hb = hover != null ? bars[hover] : null

  return (
    <div className="relative" ref={wrapRef} style={{ width: '100%' }}>
      <canvas
        ref={canvasRef}
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
        style={{ display: 'block', cursor: 'crosshair' }}
      />
      {hb && (
        <div
          className="panel-2 mono"
          style={{
            position: 'absolute',
            left: 8,
            top: 8,
            padding: '6px 8px',
            fontSize: 11,
            pointerEvents: 'none',
            zIndex: 5,
          }}
        >
          <div style={{ color: 'var(--text-dim)' }}>{hb.date}</div>
          <div style={{ color: 'var(--text-hi)' }}>
            开 {hb.open} 高 {hb.high} 低 {hb.low} 收{' '}
            <span className={hb.pct && hb.pct >= 0 ? 'up' : 'down'}>{hb.close}</span>
          </div>
          <div style={{ color: 'var(--text-dim)' }}>
            量 {(hb.volume / 1e6).toFixed(1)}M {(hb.pct ?? 0) >= 0 ? '+' : ''}
            {(hb.pct ?? 0).toFixed(2)}%
          </div>
        </div>
      )}
    </div>
  )
}
