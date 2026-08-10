/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: {
          base: 'var(--bg-base)',
          panel: 'var(--bg-panel)',
          panel2: 'var(--bg-panel-2)',
          hover: 'var(--bg-hover)',
        },
        line: { DEFAULT: 'var(--border)', soft: 'var(--border-soft)' },
        ink: {
          hi: 'var(--text-hi)',
          DEFAULT: 'var(--text)',
          dim: 'var(--text-dim)',
        },
        up: 'var(--up)',
        down: 'var(--down)',
        accent: 'var(--accent)',
        accent2: 'var(--accent-2)',
        warn: 'var(--warn)',
      },
      fontFamily: {
        mono: ['ui-monospace', 'JetBrains Mono', 'IBM Plex Mono', 'Fira Code', 'Menlo', 'Consolas', 'monospace'],
        sans: ['system-ui', '-apple-system', 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', 'sans-serif'],
      },
      borderRadius: { panel: '12px', card: '8px' },
    },
  },
  plugins: [],
}
