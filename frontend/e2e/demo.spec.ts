import { expect, test, type Page } from '@playwright/test';

/* Сквозной путь, как на защите: консоль -> встроенный участок -> карта -> норма посадки ->
 * перенос -> пересборка -> DXF -> 3D-вид и снимок. Бэкенд настоящий (green serve на своём порту, без каталога
 * улиц - как на стенде жюри без датасета), и браузер не ходит никуда, кроме него: стенд
 * проверки без интернета. */

/** Запросы страницы мимо своего сервера. data: и blob: - не сеть. */
function watchForeign(page: Page, baseURL: string): string[] {
  const own = new URL(baseURL).origin;
  const foreign: string[] = [];
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (url.protocol.startsWith('http') && url.origin !== own) foreign.push(request.url());
  });
  return foreign;
}

/** Центр свободной области карты: туда Enter ставит выбранную посадку. Та же арифметика, что
 *  у движка (PlanEngine.clearArea): панели по бокам, кнопки и полоса хода снизу, значки шапки
 *  сверху. Разойдётся с движком - перенос промахнётся, и тест упадёт на сообщении правки. */
function clearCenter(page: Page): Promise<{ x: number; y: number }> {
  return page.evaluate(() => {
    const gap = 14;
    const canvas = document.querySelector<HTMLCanvasElement>('#plan-canvas');
    if (!canvas) throw new Error('на странице нет холста карты');
    const rect = canvas.getBoundingClientRect();
    let left = 0;
    let right = rect.width;
    let top = 0;
    let bottom = rect.height;
    for (const panel of document.querySelectorAll<HTMLElement>('[data-map-obstacle="side"]')) {
      const box = panel.getBoundingClientRect();
      if (box.width === 0 || getComputedStyle(panel).position !== 'absolute') continue;
      if (box.left - rect.left < rect.width / 2) left = Math.max(left, box.right - rect.left + gap);
      else right = Math.min(right, box.left - rect.left - gap);
    }
    for (const strip of document.querySelectorAll<HTMLElement>('[data-map-obstacle="bottom"]')) {
      if (strip.hidden || getComputedStyle(strip).position !== 'absolute') continue;
      bottom = Math.min(bottom, strip.getBoundingClientRect().top - rect.top - gap);
    }
    const bar = document.querySelector<HTMLElement>('.topbar');
    if (bar && getComputedStyle(bar).position === 'fixed') {
      const box = bar.getBoundingClientRect();
      if (box.left - rect.left < right) top = Math.max(top, box.bottom - rect.top + 12);
    }
    return { x: rect.left + (left + right) / 2, y: rect.top + (top + bottom) / 2 };
  });
}

/** Сколько разных цветов на холсте (выборка): пустой холст даёт один-два. */
function paintedColors(page: Page): Promise<number> {
  return page.evaluate(() => {
    const canvas = document.querySelector<HTMLCanvasElement>('#plan-canvas');
    const context = canvas?.getContext('2d');
    if (!canvas || !context) return 0;
    const { data } = context.getImageData(0, 0, canvas.width, canvas.height);
    const colors = new Set<number>();
    for (let i = 0; i + 2 < data.length; i += 4 * 61) {
      colors.add(((data[i] ?? 0) << 16) | ((data[i + 1] ?? 0) << 8) | (data[i + 2] ?? 0));
    }
    return colors.size;
  });
}

test('демо: от консоли до пересобранного DXF', async ({ page, baseURL }) => {
  // Шаги сами ждут до 200 с прогона, 150 с пересборки и 120 с 3D-сцены: общий предел
  // конфигурации (240 с) меньше их суммы, и тест падал на последнем шаге, когда всё работало.
  test.setTimeout(480_000);
  const foreign = watchForeign(page, baseURL ?? '');
  let edits = 0;
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith('/edits')) edits += 1;
  });

  await page.goto('/');
  await page.getByRole('button', { name: 'Запустить на встроенном участке' }).click();
  await expect(page).toHaveURL(/\/runs\/[0-9a-f-]{36}$/);

  // Готовый план: справа панель состава, на холсте нарисованы подоснова и посадки.
  const right = page.getByRole('complementary', { name: 'Состав плана' });
  await expect(right.getByRole('heading', { name: /^Состав плана: \d+/ })).toBeVisible({
    timeout: 200_000,
  });
  await expect.poll(() => paintedColors(page)).toBeGreaterThan(20);

  // Посадка с клавиатуры: норма, акт и пункт в панели.
  await page.locator('#plan-canvas').focus();
  await page.keyboard.press('ArrowRight');
  await expect(right.locator('.detail-name')).toContainText('№');
  await expect(right).toContainText(/R-[A-Z]+-[A-Z]+-\d{3}/);
  await expect(right).toContainText(/СП 42|743-ПП|623-ПП/);
  await expect(right).toContainText(/п\. |табл\. /);

  // Перенос мышью: вердикт и нормы пересчитывает сервис.
  await page.keyboard.press('Enter');
  await page.waitForTimeout(1000);
  await page.getByRole('checkbox', { name: 'Переносить и удалять посадки' }).check();
  const from = await clearCenter(page);
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  for (let step = 1; step <= 10; step += 1) {
    await page.mouse.move(from.x + step * 2, from.y + step * 2.5);
  }
  await page.mouse.up();
  const bar = page.locator('#edit-bar');
  await expect(bar).toContainText('перенесена и проверена по нормам.');
  await expect(bar).toHaveAttribute('data-stale', '1');
  await expect.poll(() => edits).toBe(1);

  // Перенос без мыши (WCAG 2.2, 2.5.7): Alt со стрелками - одна правка на серию нажатий.
  await page.locator('#plan-canvas').focus();
  await page.keyboard.press('Alt+ArrowRight');
  await page.keyboard.press('Alt+ArrowRight');
  await page.keyboard.press('Alt+Shift+ArrowDown');
  await expect.poll(() => edits).toBe(2);

  // И одним указателем: кнопка в панели, затем клик по новому месту.
  const place = right.getByRole('button', { name: 'Указать новое место на карте' });
  await place.click();
  await expect(place).toHaveAttribute('aria-pressed', 'true');
  const spot = await clearCenter(page);
  await page.mouse.click(spot.x - 30, spot.y + 20);
  await expect.poll(() => edits).toBe(3);
  await expect(place).toHaveAttribute('aria-pressed', 'false');

  // Пересборка: «готово» только когда прогон вернулся с новой отметкой времени.
  await page.getByRole('button', { name: /Пересобрать DXF/ }).click();
  await expect(bar).toContainText('пересобраны по исправленному плану', { timeout: 150_000 });
  await expect(bar).toHaveAttribute('data-stale', '0');

  // DXF скачивается, и в нём слои результата.
  const href = await page.getByRole('link', { name: /Скачать DXF/ }).getAttribute('href');
  expect(href).toBeTruthy();
  const dxf = await page.request.get(href ?? '');
  expect(dxf.status()).toBe(200);
  expect(await dxf.text()).toContain('GREEN_');

  // 3D-вид того же прогона: сцена собирается из пересобранного плана, снимок - файл PNG.
  await page.getByRole('link', { name: /3D-вид участка/ }).click();
  await expect(page).toHaveURL(/\/runs\/[0-9a-f-]{36}\/3d/);
  await expect(page.getByRole('complementary', { name: 'Настройки 3D-вида' })).toBeVisible({
    timeout: 120_000,
  });
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'снимок', exact: true }).click();
  const shot = await download;
  expect(shot.suggestedFilename()).toMatch(/^3d-.+\.png$/);
  await expect(page.getByRole('img', { name: /Снимок \d+×\d+/ })).toBeVisible();

  expect(foreign).toEqual([]);
});

test('Swagger открывается без интернета', async ({ page, baseURL }) => {
  const foreign = watchForeign(page, baseURL ?? '');

  await page.goto('/docs');
  await expect(page.locator('.swagger-ui .title')).toContainText('green API');
  await expect(page.getByText('/api/v1/runs', { exact: true }).first()).toBeVisible();

  expect(foreign).toEqual([]);
});
