import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发代理：/api -> 后端 FastAPI (uvicorn 默认 8000)
// 端口被占用时可覆盖：VITE_API_TARGET=http://127.0.0.1:8001 npm run dev
const apiTarget = process.env.VITE_API_TARGET || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
})
