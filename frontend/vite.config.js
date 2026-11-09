import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  // VITE_API_TARGET overrides the default backend address (e.g. for dev on a different port).
  const apiTarget = env.VITE_API_TARGET || 'http://127.0.0.1:8233'

  return {
    plugins: [react()],
    server: {
      port: 3000,
      proxy: {
        '/api': {
          // 避免 Windows 下优先解析 ::1 导致 IPv6 拒绝连接
          target: apiTarget,
          changeOrigin: true
        }
      }
    },
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: './src/test/setup.js'
    }
  }
})
