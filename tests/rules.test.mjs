// Unit tests for rules.js — run from _autopublish/:  node --test tests/
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const R = require('../rules.js');

test('normalizeStage maps feed codes and text onto the single ladder', () => {
  assert.equal(R.normalizeStage('0'), 'None');
  assert.equal(R.normalizeStage('1'), 'Stage 1');
  assert.equal(R.normalizeStage('2'), 'Stage 2');
  assert.equal(R.normalizeStage('3'), 'Stage 3');          // BLM "3" = Closed
  assert.equal(R.normalizeStage('Closed'), 'Stage 3');
  assert.equal(R.normalizeStage('Stage II'), 'Stage 2');
  assert.equal(R.normalizeStage('Burn Ban'), 'Stage 2');   // ban is not a tier (AUDIT A1.3)
  assert.equal(R.normalizeStage('Fire Ban'), 'Stage 2');
  assert.equal(R.normalizeStage(null), R.UNKNOWN);
  assert.equal(R.normalizeStage('garbage-value'), R.UNKNOWN);
});

test('strictest: known stages ladder correctly; Unknown never outranks known', () => {
  assert.equal(R.strictest('None', 'Stage 2'), 'Stage 2');
  assert.equal(R.strictest('Stage 3', 'Stage 1'), 'Stage 3');
  // THE old masking bug: Burn Ban (sev 3) hid federal Stage 2 rows.
  assert.equal(R.strictest('Stage 2', 'Burn Ban'), 'Stage 2'); // ban == Stage 2 now
  assert.equal(R.strictest('Unknown', 'Stage 1'), 'Stage 1');
  assert.equal(R.strictest('Unknown', 'Unknown'), R.UNKNOWN);
});

test('effective: Unknown is sticky, null means "not applicable"', () => {
  // THE old A1.6 bug: Unknown + None rendered as a green "no restrictions".
  let e = R.effective(['Unknown', 'None']);
  assert.equal(e.stage, 'None');
  assert.equal(e.anyUnknown, true);          // caller must refuse the green checklist
  e = R.effective([null, 'Stage 2', undefined, false]);
  assert.equal(e.stage, 'Stage 2');
  assert.equal(e.anyUnknown, false);         // null/undefined/false = authority absent
  e = R.effective(['Stage 1', 'Unknown']);
  assert.equal(e.stage, 'Stage 1');
  assert.equal(e.anyUnknown, true);
});

test('blmStage: feed strings, null feature, demo-proof', () => {
  assert.equal(R.blmStage('0'), 'None');
  assert.equal(R.blmStage('3'), 'Stage 3');
  assert.equal(R.blmStage(null), R.UNKNOWN);   // OBJECTID 82 null-attribute feature
  assert.equal(R.blmStage(''), R.UNKNOWN);
});

test('activity matrix is monotonic — strictest-label == union of prohibitions', () => {
  // Nothing prohibited at stage N may be allowed at stage N+1. This is the
  // property that makes a single-ladder checklist safe (AUDIT A1.3).
  for (const a of R.ACTIVITIES) {
    for (let i = 1; i < a.allow.length; i++) {
      assert.ok(a.allow[i] <= a.allow[i - 1],
        `matrix not monotonic for "${a.label}" between stage ${i - 1} and ${i}`);
    }
  }
});

test('activityRows: key cells match the audited orders', () => {
  const at = (stage, label) => R.activityRows(stage, 'fed').find(r => r[0].includes(label));
  // Stage 1: grate fires OK, dispersed banned (PSICC 02-12-00-26-07)
  assert.equal(at('Stage 1', 'developed-site fire grate')[1], 1);
  assert.equal(at('Stage 1', 'dispersed')[1], 0);
  // Stage 2: NO fire rows allowed at all, stove still OK (CO-WRF-2026-14)
  assert.equal(at('Stage 2', 'developed-site fire grate')[1], 0);
  assert.equal(at('Stage 2', 'Gas / propane stove')[1], 1);
  assert.equal(at('Stage 2', 'Welding')[1], 0);
  // Fireworks: never allowed, cites 261.5(h) at stage None
  for (const s of R.STAGES) assert.equal(at(s, 'Fireworks')[1], 0);
  assert.match(at('None', 'Fireworks')[2], /261\.5\(h\)/);
  // Entry row appears only when banned (Stage 3 = closure)
  assert.ok(at('Stage 3', 'Entering'), 'entry row must exist at Stage 3');
  assert.equal(at('Stage 3', 'Entering')[1], 0);
  assert.equal(at('Stage 1', 'Entering'), undefined);
  assert.equal(at('None', 'Entering'), undefined);
});

test('activityRows: Unknown stage yields a single not-confirmed row, never a checklist', () => {
  const rows = R.activityRows('Unknown', 'fed');
  assert.equal(rows.length, 1);
  assert.equal(rows[0][1], -1);
  const rows2 = R.activityRows('total garbage', 'cty');
  assert.equal(rows2.length, 1);
});

test('context notes: federal vs county wording', () => {
  const fed = R.activityRows('None', 'fed').find(r => r[0].includes('Fireworks'))[2];
  const cty = R.activityRows('None', 'cty').find(r => r[0].includes('Fireworks'))[2];
  assert.match(fed, /federal land/);
  assert.match(cty, /Colorado/);
});

test('pointInGeom: polygon, hole, MultiPolygon', () => {
  const square = { type: 'Polygon', coordinates: [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]] };
  assert.equal(R.pointInGeom([5, 5], square), true);
  assert.equal(R.pointInGeom([15, 5], square), false);
  const donut = { type: 'Polygon', coordinates: [
    [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
    [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]] };
  assert.equal(R.pointInGeom([5, 5], donut), false, 'point in hole must be OUTSIDE');
  assert.equal(R.pointInGeom([2, 2], donut), true);
  const multi = { type: 'MultiPolygon', coordinates: [
    [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]],
    [[[8, 8], [10, 8], [10, 10], [8, 10], [8, 8]]]] };
  assert.equal(R.pointInGeom([9, 9], multi), true);
  assert.equal(R.pointInGeom([5, 5], multi), false);
});

test('samplePoints: all samples fall inside the geometry (crescent-safe)', () => {
  // L-shape whose bbox center is OUTSIDE the polygon — the old bbox-center
  // test failed exactly here (AUDIT B2).
  const ell = { type: 'Polygon', coordinates: [[[0, 0], [10, 0], [10, 3], [3, 3], [3, 10], [0, 10], [0, 0]]] };
  const pts = R.samplePoints(ell, 4);
  assert.ok(pts.length > 0);
  for (const p of pts) assert.equal(R.pointInGeom(p, ell), true);
  assert.equal(R.pointInGeom([5, 5], ell), false, 'bbox center is outside — the old method missed this shape');
});

test('esc neutralizes HTML in feed strings', () => {
  assert.equal(R.esc('<img src=x onerror=alert(1)>'), '&lt;img src=x onerror=alert(1)&gt;');
  assert.equal(R.esc('a & "b"'), 'a &amp; &quot;b&quot;');
  assert.equal(R.esc("it's"), 'it&#39;s');
  assert.equal(R.esc(null), '');
});
