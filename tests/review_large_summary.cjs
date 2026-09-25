const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('src/green/interfaces/web/static/review.js', 'utf8');
const elements = new Map();
function element(name) {
  if (!elements.has(name)) elements.set(name, {
    value: '', textContent: '', hidden: name === 'output-label', disabled: false,
    options: [], handlers: {},
    addEventListener(type, callback) { this.handlers[type] = callback; },
    append(option) { this.options.push(option); if (!this.value) this.value = option.value; },
  });
  return elements.get(name);
}
element('canvas').getContext = () => ({});
element('canvas').getBoundingClientRect = () => ({width: 800, height: 600});
element('class').options = [{value: 'ignore', textContent: 'ignore'}];
element('layer-class').options = [{value: 'ignore', textContent: 'ignore'}];
element('layer-summary').hidden = true;
element('map-placeholder').hidden = true;
const calls = [];
const report = {
  source_sha256: 'sha', features: 50001, unresolved_features: 50000,
  work_boundary_present: true, unresolved_work_intersections: 40000,
  groups: [
    {layer: 'L', block: null, geometry: 'LineString', object_class: 'unknown',
      evidence: {method: 'unmatched'}, features: 50000, work_intersections: 40000},
    {layer: 'BOUNDARY', block: null, geometry: 'Polygon', object_class: 'work_boundary',
      evidence: {method: 'name_rule'}, features: 1, work_intersections: 1},
  ],
};
const record = {overrides: {placement_solver: 'greedy'}};
const context = {
  document: {
    querySelector: () => ({dataset: {runId: 'test'}}),
    getElementById: id => element(id.replace(/^review-/, '')),
    createElement: () => ({value: '', textContent: ''}),
  },
  fetch: async url => {
    calls.push(url);
    assert(!url.includes('semantic-review.geojson'), 'large map loaded automatically');
    return {ok: true, json: async () => url.endsWith('classification.json') ? report : record};
  },
  ResizeObserver: class { observe() {} },
};

(async () => {
  await vm.runInNewContext(`(async () => { ${source}\n})()`, context);
  assert.equal(calls.length, 2);
  assert.equal(element('layer-summary').hidden, false);
  assert.equal(element('layer').value, 'L');
  element('layer-class').value = 'ignore';
  element('layer-assign').handlers.click();
  element('show').handlers.click();
  const overrides = JSON.parse(element('output').value);
  assert.equal(overrides.layer_classes.L, 'ignore');
  assert.equal(overrides.semantic_source_sha256, 'sha');
  assert.equal(overrides.require_known_objects, true);
  assert.equal(overrides.placement_solver, 'greedy');
  assert.equal(overrides.feature_classes, undefined);
})().catch(error => { console.error(error); process.exitCode = 1; });
