// Manual visual experiment; never invoked by tests or CI. Requires Chrome and a running Vite server.
// prepare copies existing run artifacts only; capture measures the actual engine without running a test suite.
import { chromium } from "../frontend/node_modules/@playwright/test/index.mjs";
import { writeFileSync, mkdirSync, copyFileSync } from "node:fs";
import { execFileSync, spawnSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
process.chdir(resolve(dirname(fileURLToPath(import.meta.url)), ".."));
const [mode, input, ref = "HEAD"] = process.argv.slice(2);
const LAB_HTML =
    "<!doctype html><html lang=\"ru\"><meta charset=\"utf-8\"><link rel=\"icon\" href=\"data:,\"><title>Сравнение графики 3D</title><style>html,body{margin:0;width:100%;height:100%;overflow:hidden}main{width:100%;height:100%}canvas{width:100%;height:100%;display:block}</style><main><canvas></canvas></main><script type=\"module\">\nconst old=new URLSearchParams(location.search).has('baseline');\nconst root=old?'./baseline/frontend/src':'/src';\nconst {SceneEngine}=await import(root+'/scene3d/engine.ts');\nconst {buildWorld}=await import(root+'/scene3d/world.ts');\nconst [scene,basemap,meta]=await Promise.all(['scene.json','basemap.geojson','surface.json'].map(n=>fetch('./'+n).then(r=>r.json())));\nconst img=new Image();img.src='./surface.png';await img.decode();\nwindow.stats=[];\nconst engine=await SceneEngine.create(document.querySelector('canvas'),buildWorld({scene,basemap,plan:null}),{img,origin:meta.origin,cell:meta.cell_m,width:meta.width,height:meta.height},{frame:s=>window.stats.push(s)});\nengine.apply({quality:'high',age:25,wind:0,people:0,hour:15,clouds:0.2});\nwindow.engine=engine;\nwindow.ready=true;\n</script></html>\n";

if (mode === "prepare") {
    if (!input)
        throw new Error(
            "Usage: node tools/scene-quality.mjs prepare RUN_OUTPUT_DIR [BASE_REF]",
        );
    const dest = "frontend/.scene-lab";
    mkdirSync(dest, { recursive: true });
    for (const name of [
        "scene.json",
        "basemap.geojson",
        "surface.json",
        "surface.png",
    ])
        copyFileSync(resolve(input, name), resolve(dest, name));
    const base = resolve(dest, "baseline");
    mkdirSync(base, { recursive: true });
    const archive = execFileSync("git", ["archive", ref, "frontend/src"], {
        maxBuffer: 32 * 1024 * 1024,
    });
    const unpack = spawnSync("tar", ["-x", "-C", base], { input: archive });
    if (unpack.status !== 0) throw new Error(unpack.stderr.toString());
    writeFileSync(resolve(dest, "index.html"), LAB_HTML);
    console.log(
        "Prepared. Start Vite, then open /.scene-lab/index.html or run capture with its URL.",
    );
    process.exit(0);
}
if (mode !== "capture" || !input)
    throw new Error(
        "Usage: node tools/scene-quality.mjs capture http://127.0.0.1:5178/.scene-lab/index.html",
    );
const out = "out/scene-quality";
mkdirSync(out, { recursive: true });
const browser = await chromium.launch({
    channel: "chrome",
    headless: true,
    args: ["--enable-gpu", "--ignore-gpu-blocklist"],
});
const report = [];
for (const variant of ["baseline", "enhanced", "standard-ao"]) {
    const page = await browser.newPage({
        viewport: { width: 1920, height: 1080 },
    });
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    page.on("console", (m) => {
        if (m.type() === "error" || m.type() === "warning")
            errors.push(m.text());
    });
    await page.goto(input + (variant === "baseline" ? "?baseline" : ""));
    await page.waitForFunction(() => window.ready, null, { timeout: 180000 });
    if (variant === "standard-ao")
        await page.evaluate(() =>
            engine.postprocessing.ao.setQualityMode("Medium"),
        );
    const poses = await page.evaluate(() => {
        const shots = engine.planShots({ kind: "street" });
        const trees = engine.world.plants.filter(
            (p) => !p.existing && p.type === "tree",
        );
        const close = trees
            .flatMap((p) => engine.planShots({ kind: "plant", id: p.id }))
            .find((s) => s.viewpoint === "ground");
        return { aerial: shots[0].pose, ground: close?.pose ?? shots[0].pose };
    });
    for (const [name, settings, pose] of [
        ["day", { hour: 15, season: "summer", rain: 0, snow: 0 }, poses.aerial],
        [
            "ground",
            { hour: 16, season: "summer", rain: 0, snow: 0 },
            poses.ground,
        ],
        [
            "night",
            { hour: 23, season: "summer", rain: 0, snow: 0 },
            poses.ground,
        ],
        [
            "winter",
            { hour: 13, season: "winter", rain: 0, snow: 0 },
            poses.ground,
        ],
        [
            "wet",
            { hour: 17, season: "summer", rain: 0.65, snow: 0 },
            poses.ground,
        ],
    ]) {
        await page.evaluate(
            ({ settings, pose }) => {
                engine.apply(settings);
                engine.setView(pose, "fly");
                window.stats = [];
            },
            { settings, pose },
        );
        await page.waitForTimeout(5500);
        await page.screenshot({ path: `${out}/${variant}-${name}.png` });
        const data = await page.evaluate(() => ({
            stats: window.stats,
            canvas: [engine.canvas.width, engine.canvas.height],
            memory: engine.renderer.info.memory,
            pose: engine.freecam.pose,
            neural: engine.postprocessing?.ao.configuration.neuralDenoise,
            adapter: engine.renderer
                .getContext()
                .getParameter(
                    engine.renderer
                        .getContext()
                        .getExtension("WEBGL_debug_renderer_info")
                        ?.UNMASKED_RENDERER_WEBGL ?? 7937,
                ),
        }));
        report.push({ variant, name, ...data, errors: [...errors] });
        console.log(
            JSON.stringify({
                variant,
                name,
                fps: data.stats.map((s) => s.fps),
                errors: errors.length,
                neural: data.neural,
            }),
        );
    }
    if (variant === "enhanced") {
        await page.evaluate(() =>
            engine.apply({ rain: 0, season: "summer", hour: 15 }),
        );
        for (const quality of ["low", "medium", "high", "medium", "high"]) {
            await page.evaluate((q) => {
                engine.apply({ quality: q });
                window.stats = [];
            }, quality);
            await page.waitForTimeout(2200);
            report.push({
                variant,
                quality,
                lifecycle: await page.evaluate(() => ({
                    stats: window.stats,
                    memory: engine.renderer.info.memory,
                    canvas: [engine.canvas.width, engine.canvas.height],
                })),
                errors: [...errors],
            });
        }
        const capture = await page.evaluate(async () => {
            engine.setPaused(true);
            const blob = await engine.capture(2);
            const img = await createImageBitmap(blob);
            const pngSize = [img.width, img.height];
            img.close();
            const shots = await engine.renderViews(
                [engine.freecam.pose],
                1024,
                576,
            );
            const snap = await createImageBitmap(shots[0]);
            const size = [snap.width, snap.height];
            snap.close();
            engine.setPaused(false);
            return {
                pngBytes: blob.size,
                pngSize,
                autoShotSize: size,
                canvas: [engine.canvas.width, engine.canvas.height],
            };
        });
        report.push({ variant, capture, errors: [...errors] });
    }
    await page.close();
    writeFileSync(`${out}/comparison.json`, JSON.stringify(report, null, 2));
}
await browser.close();
