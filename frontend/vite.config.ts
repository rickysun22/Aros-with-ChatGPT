import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 开发时把 /api 代理到 AROS FastAPI 桥接服务(localhost:8000)。
// 生产静态部署时,通过环境变量 VITE_API_BASE 指定 API 地址(留空 = 同源)。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: true } },
  },
  build: {
    outDir: 'dist',
    // 关闭自动清空输出目录:沙箱 safe-delete 防护会误判 emptyDir 目标而拦截构建。
    // dist 本就被 .gitignore 忽略,且不参与提交,手动清空无必要。
    emptyOutDir: false,
  },
})
