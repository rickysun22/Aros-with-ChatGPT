import { useEffect, useState } from 'react'
import Sidebar from './components/Sidebar'
import Topbar from './components/Topbar'
import KpiRow from './components/KpiRow'
import Watchlist, { WatchRow } from './components/Watchlist'
import AlphaRadar from './components/AlphaRadar'
import CandleChart from './components/CandleChart'
import IndicatorPanel from './components/IndicatorPanel'
import AIInsight from './components/AIInsight'
import PaperPortfolio from './components/PaperPortfolio'
import Sectors from './components/Sectors'
import Alerts from './components/Alerts'
import SystemStatus from './components/SystemStatus'
import CalendarPanel from './components/CalendarPanel'
import { Card } from './ui'
import { api } from './api'
import type { AlphaRow, Bar, IndexSnap } from './types'
import * as mock from './mock'

const nameMap: Record<string, string> = Object.fromEntries(mock.mockStocks.map((s) => [s.code, s.name]))

export default function App() {
  const [theme, setTheme] = useState<'dark' | 'light'>('dark')
  const [mode, setMode] = useState<'live' | 'mock'>('mock')
  const [nav, setNav] = useState('Dashboard')
  const [indices, setIndices] = useState<IndexSnap[]>(mock.mockIndices())
  const [selected, setSelected] = useState('600000')
  const [bars, setBars] = useState<Bar[]>([])
  const [last, setLast] = useState<Record<string, number | null>>({})
  const [price, setPrice] = useState<number | undefined>()
  const [pct, setPct] = useState<number | undefined>()
  const [detailLive, setDetailLive] = useState(false)

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
  }, [theme])

  // 启动时探测 AROS API
  useEffect(() => {
    ;(async () => {
      try {
        const h = await api.health()
        const live = h.status === 'ok' && h.stock_count > 0
        setMode(live ? 'live' : 'mock')
        if (live) {
          try {
            const m = await api.market()
            if (!m.empty) setIndices(m.indices)
          } catch {
            /* 用 mock 指数 */
          }
        }
      } catch {
        setMode('mock')
      }
    })()
  }, [])

  // 选中股票 → 拉真实数据(失败回 mock)
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      const applyMock = () => {
        if (cancelled) return
        const mb = mock.mockBars(selected)
        setBars(mb)
        setPrice(mb[mb.length - 1].close)
        setPct(mb[mb.length - 1].pct ?? undefined)
        setLast(mock.mockFactorLast(selected))
        setDetailLive(false)
      }
      if (mode === 'live') {
        try {
          const [b, ind, fac] = await Promise.all([
            api.bars(selected),
            api.indicators(selected),
            api.factors(selected),
          ])
          if (cancelled) return
          if (!b.empty && b.bars.length) {
            setBars(b.bars)
            setPrice(b.last ? b.last.close : undefined)
            setPct(b.last ? b.last.pct ?? undefined : undefined)
            setDetailLive(true)
          } else {
            applyMock()
            return
          }
          const merged: Record<string, number | null> = {}
          if (!ind.empty && ind.rows.length) Object.assign(merged, ind.rows[ind.rows.length - 1])
          if (!fac.empty && fac.rows.length) Object.assign(merged, fac.rows[fac.rows.length - 1])
          setLast(Object.keys(merged).length ? merged : mock.mockFactorLast(selected))
        } catch {
          applyMock()
        }
      } else {
        applyMock()
      }
    })()
    return () => {
      cancelled = true
    }
  }, [selected, mode])

  const watchlist: WatchRow[] = mock.mockWatchlist()
  const alpha: AlphaRow[] = mock.mockAlpha()

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: 'var(--bg-base)' }}>
      <Sidebar active={nav} onSelect={setNav} />

      <div className="flex-1 flex flex-col overflow-hidden">
        <Topbar indices={indices} mode={mode} theme={theme} onToggleTheme={() => setTheme(theme === 'dark' ? 'light' : 'dark')} />

        <main className="flex-1 overflow-y-auto p-4 space-y-3" style={{ maxWidth: 1600, margin: '0 auto', width: '100%' }}>
          <KpiRow indices={indices} />

          {/* 自选股 + 右栏卡片 */}
          <div className="grid grid-cols-12 gap-3">
            <Card title="自选股 Watchlist" className="col-span-12 lg:col-span-7">
              <Watchlist rows={watchlist} selected={selected} onSelect={setSelected} />
            </Card>
            <div className="col-span-12 lg:col-span-5 grid grid-cols-1 sm:grid-cols-2 gap-3 content-start">
              <Card title="AI Market Insight">
                <AIInsight />
              </Card>
              <Card title="Paper Portfolio">
                <PaperPortfolio p={mock.mockPortfolio()} />
              </Card>
              <Card title="板块表现" className="sm:col-span-2">
                <Sectors sectors={mock.mockSectors()} />
              </Card>
              <Card title="实时告警" className="sm:col-span-2">
                <Alerts alerts={mock.mockAlerts()} />
              </Card>
            </div>
          </div>

          {/* 蜡烛图 + 指标/因子面板(真实引擎计算) */}
          <div className="grid grid-cols-12 gap-3">
            <Card
              title={`${selected} ${nameMap[selected] ?? ''} · 蜡烛图`}
              right={
                detailLive ? (
                  <span style={{ color: 'var(--down)', fontSize: 11 }}>● 真实数据</span>
                ) : (
                  <span style={{ color: 'var(--warn)', fontSize: 11 }}>演示数据</span>
                )
              }
              className="col-span-12 lg:col-span-8"
            >
              {bars.length ? (
                <CandleChart bars={bars} />
              ) : (
                <div style={{ color: 'var(--text-dim)', padding: 40, textAlign: 'center' }}>无数据</div>
              )}
            </Card>
            <Card title="指标 & 因子" className="col-span-12 lg:col-span-4">
              <IndicatorPanel last={last} price={price} pct={pct} />
            </Card>
          </div>

          {/* Alpha 雷达 + 系统/日历 */}
          <div className="grid grid-cols-12 gap-3">
            <Card title="Alpha Radar · 因子评分" className="col-span-12 lg:col-span-7">
              <AlphaRadar rows={alpha} />
            </Card>
            <div className="col-span-12 lg:col-span-5 grid grid-cols-1 sm:grid-cols-2 gap-3 content-start">
              <Card title="系统状态">
                <SystemStatus items={mock.mockSystem()} />
              </Card>
              <Card title="日历事件">
                <CalendarPanel events={mock.mockCalendar()} />
              </Card>
            </div>
          </div>

          {mode === 'mock' && (
            <div
              className="panel-2 px-3 py-2 text-[12px]"
              style={{ color: 'var(--warn)', borderColor: 'var(--warn)' }}
            >
              ⚠ 当前为演示数据。启动 AROS API(<code className="mono">python api_server.py</code>)并同步数据后,
              蜡烛图 / 指标 / 因子将切换为 AROS 引擎实时计算结果。
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
