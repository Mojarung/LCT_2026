/// <reference types="vitest/config" />
import { copyFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import react from '@vitejs/plugin-react';
import { defineConfig, type Plugin } from 'vite';

const root = path.dirname(fileURLToPath(import.meta.url));

/** Swagger UI из бандла, а не с CDN: стенд жюри может быть без интернета, а /docs FastAPI по
 *  умолчанию грузит скрипт и стили с cdn.jsdelivr.net и без сети показывает пустую страницу. */
function swaggerVendor(): Plugin {
  return {
    name: 'green-swagger-vendor',
    apply: 'build',
    async closeBundle() {
      const from = path.dirname(fileURLToPath(import.meta.resolve('swagger-ui-dist/package.json')));
      const to = path.join(root, 'dist', 'vendor', 'swagger');
      await mkdir(to, { recursive: true });
      for (const name of ['swagger-ui.css', 'swagger-ui-bundle.js']) {
        await copyFile(path.join(from, name), path.join(to, name));
      }
    },
  };
}

// Бэкенд для разработки. Порт 8000 обычно занят контейнером сервиса, поэтому отдельный.
const api = process.env.GREEN_API_URL ?? 'http://127.0.0.1:8010';

export default defineConfig({
  plugins: [react(), swaggerVendor()],
  server: {
    port: 5173,
    // Кроме самого фронтенда - только каталог config/: тест базы моделей сверяет её с
    // config/species.yaml, чтобы новый вид каталога не рисовался запасной моделью молча.
    fs: { allow: ['.', '../config'] },
    proxy: {
      '/api': { target: api, changeOrigin: true },
      '/docs': { target: api, changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: true,
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    // Стили в тестах не нужны, кроме src/styles: их текст читает проверка CSS-переменных.
    css: { include: [/\/src\/styles\/[^/?]+\.css/] },
    restoreMocks: true,
  },
});
