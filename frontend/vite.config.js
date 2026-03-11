import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
    plugins: [react()],
    server: {
        port: 3412,
        // Proxy is only used in local dev — in production, nginx routes /api to FastAPI on 7887
        proxy: {
            '/api': {
                target: 'http://localhost:7887',
                changeOrigin: true,
                rewrite: (path) => path.replace(/^\/api/, '')
            }
        }
    }
})
