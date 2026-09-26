// Собирает презентацию в один HTML без внешних зависимостей.
// Запуск: node tools/presentation/build.mjs  ->  docs/presentation.html
import { readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, 'src');
const out = join(here, '..', '..', 'docs', 'presentation.html');

const read = (p) => readFileSync(join(src, p), 'utf8');
const scenes = readdirSync(join(src, 'scenes'))
  .filter((f) => f.endsWith('.js'))
  .sort()
  .map((f) => `// ---- scenes/${f}\n` + read(join('scenes', f)));

const js = [read('runtime.js'), read('lib.js'), read('common.js'), read('world.js'), ...scenes, read('audio.js'), read('player.js')].join('\n');
if (js.includes('</script')) throw new Error('в коде встретилось </script, сборка сломает страницу');

const html = `<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>green: озеленение улиц по нормам</title>
<style>
html,body{margin:0;height:100%;background:#060A1C;overflow:hidden}
body{display:flex;align-items:center;justify-content:center;-webkit-user-select:none;user-select:none}
canvas{display:block;cursor:pointer}
</style>
</head>
<body>
<canvas id="stage" width="1920" height="1080"></canvas>
<script>
${js}
</script>
</body>
</html>
`;
writeFileSync(out, html);
console.log(`${out}: ${(html.length / 1024).toFixed(0)} КБ, сцен ${scenes.length}`);
