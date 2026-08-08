import { Pct } from '../ui'

const insights = [
  {
    tag: '因子',
    text: '半导体板块 F-Score 均值升至 7.8,盈利质量与动量共振,建议提升权重。',
    pct: 2.1,
  },
  {
    tag: '风险',
    text: '沪深300 20 日波动率回落至 0.18,但白酒龙头 RSI 进入超买区,注意回撤。',
    pct: -1.3,
  },
  {
    tag: '资金',
    text: '北向口径估算净流入 +28.6 亿,集中流入新能源与银行,与 Alpha 排名一致。',
    pct: 1.0,
  },
]

export default function AIInsight() {
  return (
    <div className="space-y-3">
      <div
        className="rounded-md px-2.5 py-2"
        style={{ background: 'linear-gradient(135deg, var(--accent-2), var(--accent))', color: '#fff', fontSize: 12.5 }}
      >
        AROS AI 综合研判:市场情绪偏多,结构分化加剧,建议“高因子 + 低波动”组合。
      </div>
      {insights.map((x, i) => (
        <div key={i} className="flex gap-2.5">
          <span
            className="mono px-1.5 py-0.5 rounded"
            style={{ background: 'var(--bg-panel-2)', color: 'var(--accent-2)', fontSize: 10, alignSelf: 'flex-start' }}
          >
            {x.tag}
          </span>
          <div className="flex-1">
            <div style={{ color: 'var(--text)', fontSize: 12.5, lineHeight: 1.5 }}>{x.text}</div>
            <div className="text-[11px] mt-0.5">
              <Pct v={x.pct} />
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
