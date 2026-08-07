import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // CORS 設定を書かずに済ませるため /api をバックエンドへ転送する（docs/spec.md §3）
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
  test: {
    // コンポーネントのテスト（プロフィール画面）が DOM を使うので jsdom にする
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    globals: true,
  },
})
