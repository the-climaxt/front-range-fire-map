/* rules.js — single source of truth for the fire-restriction rules engine.
 *
 * Inlined into the map page by build.py (placeholder __RULES__) and imported
 * directly by tests (node: require('./rules.js')). Keep this file free of
 * DOM / Leaflet code — pure data + pure functions only.
 *
 * Design decisions (see AUDIT.md):
 *  - ONE severity ladder: None < Stage 1 < Stage 2 < Stage 3 (= closure).
 *    "Burn Ban" is NOT a tier; normalizeStage() maps a declared ban to
 *    Stage 2 (conservative: a ban prohibits at least all open fire).
 *    (AUDIT A1.3 — the old two-ladder model let a vague county label mask
 *    federal Stage 2 prohibitions.)
 *  - Unknown is STICKY, never weakest: effective() reports anyUnknown so
 *    callers can refuse to show a green checklist off missing data.
 *    (AUDIT A1.6 — the old SEV.Unknown=-1 rendered unknown BLM parcels as
 *    "no restrictions".)
 *  - The activity matrix is monotonic: nothing prohibited at stage N is
 *    allowed at stage N+1. That makes "checklist at the strictest stage"
 *    exactly equal to the union of prohibitions across overlapping orders.
 *    A unit test enforces monotonicity.
 */
const FireRules = (function () {
  'use strict';

  const STAGES = ['None', 'Stage 1', 'Stage 2', 'Stage 3'];
  const SEV = { 'None': 0, 'Stage 1': 1, 'Stage 2': 2, 'Stage 3': 3 };
  const UNKNOWN = 'Unknown';

  function isKnown(s) { return Object.prototype.hasOwnProperty.call(SEV, s); }

  /* Map any input (feed codes, legacy labels, free text) onto the ladder. */
  function normalizeStage(s) {
    if (s === null || s === undefined) return UNKNOWN;
    const t = String(s).trim();
    if (isKnown(t)) return t;
    const l = t.toLowerCase();
    if (l === '' ) return UNKNOWN;
    if (l === '0' || l === 'none' || /^no (fire )?restriction/.test(l)) return 'None';
    if (l === '3' || /stage\s*(3|iii)\b/.test(l) || /clos(ed|ure)/.test(l)) return 'Stage 3';
    if (l === '2' || /stage\s*(2|ii)\b/.test(l)) return 'Stage 2';
    if (l === '1' || /stage\s*(1|i)\b/.test(l)) return 'Stage 1';
    if (/ban/.test(l)) return 'Stage 2'; // declared ban: at minimum no open fires
    return UNKNOWN;
  }

  /* Strictest of two stages, KNOWN stages only win; Unknown never outranks
   * a known stage here — use effective() when you must track uncertainty. */
  function strictest(a, b) {
    a = normalizeStage(a); b = normalizeStage(b);
    if (!isKnown(a)) return isKnown(b) ? b : UNKNOWN;
    if (!isKnown(b)) return a;
    return SEV[b] > SEV[a] ? b : a;
  }

  /* Aggregate any number of stages: strictest KNOWN stage + uncertainty flag.
   * Pass null/undefined/false for "authority not applicable here" (skipped);
   * pass the string 'Unknown' for "authority applies but level unverified".
   * Callers MUST check anyUnknown before rendering an all-clear answer. */
  function effective(stages) {
    let eff = 'None', anyUnknown = false;
    (stages || []).forEach(function (s) {
      if (s === false || s === null || s === undefined) return; // not applicable
      s = normalizeStage(s);
      if (!isKnown(s)) { anyUnknown = true; return; }
      if (SEV[s] > SEV[eff]) eff = s;
    });
    return { stage: eff, anyUnknown: anyUnknown };
  }

  /* BLM NIFC feed `restriction` field: strings "0".."3" ("3" = Closed),
   * occasionally null (one empty feature observed in the live layer). */
  function blmStage(code) {
    if (code === null || code === undefined || String(code).trim() === '') return UNKNOWN;
    return normalizeStage(code);
  }

  /* ------------------------------------------------------------------ *
   * Canonical activity matrix.
   * allow: [None, Stage 1, Stage 2, Stage 3] — 1 allowed, 0 prohibited.
   * notes: per stage; string, or {fed:…, cty:…} when federal-land wording
   * differs from county/private-land wording.
   * Sources: 36 CFR 261.5/.52; PSICC Order 02-12-00-26-07 (Stage 1, 2026);
   * White River Order CO-WRF-2026-14 (Stage 2, 2026); RMACC "Explanation of
   * Fire Restrictions"; Chaffee Ord. 2025-03; El Paso Ord. 22-001. See
   * AUDIT.md §A2 for the cell-by-cell citations.
   * ------------------------------------------------------------------ */
  const ACTIVITIES = [
    { key: 'fire_dispersed', label: 'Campfire — dispersed / backcountry',
      allow: [1, 0, 0, 0],
      notes: { 'None': { fed: 'legal, but clear flammables well back and never leave it — 36 CFR 261.5',
                         cty: 'landowner permission; contained ring; clear the area' } } },
    { key: 'fire_grate', label: 'Campfire in a developed-site fire grate',
      allow: [1, 1, 0, 0],
      notes: { 'Stage 1': { fed: 'permanent agency grates at developed recreation sites only',
                            cty: 'permanent grates at public or commercial campgrounds (some orders also allow private-property grates)' },
               'Stage 2': 'banned even in developed campgrounds' } },
    { key: 'charcoal', label: 'Charcoal grill',
      allow: [1, 0, 0, 0],
      notes: { 'Stage 1': { fed: 'only inside developed-site grates',
                            cty: 'often still allowed at private residences — check the county order' } } },
    { key: 'stove', label: 'Gas / propane stove or grill',
      allow: [1, 1, 1, 0],
      notes: { 'Stage 1': 'must have a shut-off valve; 3-ft cleared area',
               'Stage 2': 'shut-off valve + 3-ft cleared area — allowed by most orders; confirm yours',
               'Stage 3': 'closure — no use, area closed' } },
    { key: 'smoking', label: 'Smoking outdoors',
      allow: [1, 0, 0, 0],
      notes: { 'Stage 1': 'OK in a vehicle/building, a developed rec site, or a 3-ft cleared spot (some Stage 1 orders don’t restrict smoking)',
               'Stage 2': 'OK only inside an enclosed vehicle or building' } },
    { key: 'equipment', label: 'Chainsaw / generator / engine',
      allow: [1, 1, 0, 0],
      notes: { 'None': { fed: 'spark arrester required on federal land', cty: '' },
               'Stage 1': 'spark arrester required',
               'Stage 2': 'typically banned 1 p.m.–1 a.m., or requires spark arrester + water & shovel — check the order' } },
    { key: 'welding', label: 'Welding / open-flame torch',
      allow: [1, 1, 0, 0],
      notes: { 'Stage 1': 'cleared area + fire extinguisher rules may apply' } },
    { key: 'fireworks', label: 'Fireworks / exploding targets',
      allow: [0, 0, 0, 0],
      notes: { 'None': { fed: 'always prohibited on federal land — 36 CFR 261.5(h)',
                         cty: 'most consumer fireworks are illegal in Colorado; always prohibited on federal land' } } },
    { key: 'entry', label: 'Entering the area', onlyWhenBanned: true,
      allow: [1, 1, 1, 0],
      notes: { 'Stage 3': 'Stage 3 = closure — area closed to all entry (36 CFR 261.52(e))' } }
  ];

  function noteFor(act, stage, ctx) {
    const n = act.notes && act.notes[stage];
    if (!n) return '';
    if (typeof n === 'string') return n;
    return n[ctx === 'cty' ? 'cty' : 'fed'] || '';
  }

  /* Rows for the allowed/not-allowed checklist at a stage.
   * ctx: 'fed' (federal land — county + federal orders both apply) or
   *      'cty' (non-federal land inside a county).
   * Unknown stage → a single "not confirmed" row; NEVER a green checklist. */
  function activityRows(stage, ctx) {
    stage = normalizeStage(stage);
    if (!isKnown(stage)) {
      return [['Restriction level not confirmed', -1, 'open the official order links below before lighting anything']];
    }
    const idx = SEV[stage];
    const rows = [];
    ACTIVITIES.forEach(function (a) {
      const allowed = a.allow[idx];
      if (a.onlyWhenBanned && allowed === 1) return;
      rows.push([a.label, allowed, noteFor(a, stage, ctx)]);
    });
    return rows;
  }

  /* ------------------------------------------------------------------ *
   * Geometry: even-odd ray casting, with holes (AUDIT C5).
   * ------------------------------------------------------------------ */
  function pointInRing(pt, ring) {
    let x = pt[0], y = pt[1], inside = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const xi = ring[i][0], yi = ring[i][1], xj = ring[j][0], yj = ring[j][1];
      if (((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / ((yj - yi) || 1e-12) + xi)) inside = !inside;
    }
    return inside;
  }
  function pointInPoly(pt, rings) {           // rings[0] = outer, rest = holes
    if (!rings || !rings.length || !pointInRing(pt, rings[0])) return false;
    for (let i = 1; i < rings.length; i++) if (pointInRing(pt, rings[i])) return false;
    return true;
  }
  function pointInGeom(pt, geom) {
    if (!geom) return false;
    const ps = geom.type === 'MultiPolygon' ? geom.coordinates
             : (geom.type === 'Polygon' ? [geom.coordinates] : []);
    for (const poly of ps) if (pointInPoly(pt, poly)) return true;
    return false;
  }

  /* Sample points across a polygon for robust polygon-vs-polygon "touches"
   * tests (bbox grid, filtered to points actually inside the geometry).
   * Replaces the old bbox-center test that missed crescent shapes. */
  function samplePoints(geom, n) {
    n = n || 4;
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    const ps = geom.type === 'MultiPolygon' ? geom.coordinates
             : (geom.type === 'Polygon' ? [geom.coordinates] : []);
    ps.forEach(function (poly) { (poly[0] || []).forEach(function (c) {
      if (c[0] < minX) minX = c[0]; if (c[0] > maxX) maxX = c[0];
      if (c[1] < minY) minY = c[1]; if (c[1] > maxY) maxY = c[1]; }); });
    const out = [];
    if (minX > maxX) return out;
    for (let i = 0; i <= n; i++) for (let j = 0; j <= n; j++) {
      const p = [minX + (maxX - minX) * i / n, minY + (maxY - minY) * j / n];
      if (pointInGeom(p, geom)) out.push(p);
    }
    return out;
  }

  /* HTML-escape every feed-derived string before innerHTML (AUDIT D1). */
  function esc(s) {
    return String(s === null || s === undefined ? '' : s)
      .replace(/[&<>"']/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
      });
  }

  return {
    STAGES: STAGES, SEV: SEV, UNKNOWN: UNKNOWN, ACTIVITIES: ACTIVITIES,
    isKnown: isKnown, normalizeStage: normalizeStage, strictest: strictest,
    effective: effective, blmStage: blmStage, activityRows: activityRows,
    pointInRing: pointInRing, pointInGeom: pointInGeom, samplePoints: samplePoints,
    esc: esc
  };
})();
if (typeof module !== 'undefined' && module.exports) module.exports = FireRules;
