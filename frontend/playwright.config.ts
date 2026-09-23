import { defineConfig, devices } from '@playwright/test';

// Свой порт: 8000 занят контейнером сервиса, а проба готовности по чужому порту подтвердила
// бы чужое приложение. Сервер поднимает сам Playwright и падает, если порт уже занят.
const port = Number(process.env.GREEN_E2E_PORT ?? 8012);
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: 'e2e',
  timeout: 240_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: { baseURL, trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: `uv run --frozen green serve --port ${port}`,
    cwd: '..',
    url: `${baseURL}/api/v1/health`,
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      GREEN_WEB_DIR: 'frontend/dist',
      GREEN_RUNS_DIR: 'var/e2e-runs',
      // Каталога улиц нет, как на стенде жюри без датасета: консоль предлагает встроенный участок.
      GREEN_STREETS_DIR: 'var/e2e-no-streets',
      PYTHONIOENCODING: 'utf-8',
    },
  },
});
