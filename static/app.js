'use strict';

const state = {
  meta: {}, crew: [], id: null, snapshot: null, tab: 'overview', history: null,
  monitor: {}, selectedSymptoms: new Set(), selectedContext: new Set(), symptomSearch: '',
  symptomDirty: false, seenAlerts: new Set(), forecast: null, polling: false, sound: false,
  connected: false, audio: null, openDetails: new Set(), crewAlertCounts: {},
};
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const human = value => String(value ?? '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
const arr = value => Array.isArray(value) ? value : [];
const fmt = value => typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString(undefined, { maximumFractionDigits: 3 }) : '—';
const date = value => { if (!value) return 'Not recorded'; const d = new Date(value); return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString(); };
const statusLabel = value => ({ good: 'Within limits', normal: 'Within limits', within_configured_reference: 'Within limits', missing: 'Missing', unassessed: 'Needs context', needs_context: 'Needs context', needs_coverage: 'Needs coverage', stale: 'Stale', invalid: 'Invalid', caution: 'Caution', critical: 'Critical', UNKNOWN: 'Awaiting data', NORMAL: 'Within limits', MONITOR: 'Monitor', SUSPECTED: 'Suspected', URGENT: 'Urgent', EMERGENCY: 'Emergency' }[value] || human(value));
const pill = value => `<span class="pill ${esc(String(value || 'unknown').toLowerCase())}">${esc(statusLabel(value || 'UNKNOWN'))}</span>`;
const profileName = profile => profile?.personal_information?.name || profile?.name || profile?.astronaut_id || 'Astronaut';
const idPath = () => `/astronauts/${encodeURIComponent(state.id)}`;
const safeUrl = value => { try { const u = new URL(value); return ['http:', 'https:'].includes(u.protocol) ? u.href : ''; } catch (_) { return ''; } };
const sourceBadge = source => `<span class="source-badge ${/simulat/i.test(source || '') ? 'simulation' : ''}">${esc((source || 'No source').toUpperCase())}</span>`;
function toast(message) { const t = $('#toast'); t.textContent = message; t.classList.add('visible'); clearTimeout(toast.timer); toast.timer = setTimeout(() => t.classList.remove('visible'), 4500); }
function guard(fn) { return async (...args) => { try { await fn(...args); } catch (e) { toast(e.message || String(e)); } }; }
async function api(method, path, body) {
  const headers = { 'Content-Type': 'application/json' };
  if (state.meta.csrf_token) headers['X-CSRF-Token'] = state.meta.csrf_token;
  const response = await fetch('/api' + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
  return payload;
}
function connection(ok) {
  state.connected = ok;
  $('#connection').textContent = ok ? 'Monitor connected' : 'Monitor disconnected';
  $('#connection-dot').className = 'dot ' + (ok ? 'connected' : 'offline');
  $('#connection-detail').textContent = ok ? 'Checks every incoming reading' : 'Start the local application to reconnect';
}
function renderCrew() {
  $('#crew-count').textContent = state.crew.length;
  $('#crew-list').innerHTML = state.crew.length ? state.crew.map(c => {
    const id = c.id || c.astronaut_id;
    return `<button class="crew-button ${id === state.id ? 'selected' : ''}" data-crew="${esc(id)}"><span class="avatar">${esc(String(id).replace('A-', ''))}</span><span><span class="crew-name">${esc(c.name || id)}</span><span class="crew-meta">${esc(human(c.gender || c.sex))} · ${c.mission_day ? 'Day ' + esc(c.mission_day) : 'Awaiting first reading'}</span></span><span class="crew-state ${esc((c.overall || 'unknown').toLowerCase())}" title="${esc(statusLabel(c.overall))}"></span>${c.active_alerts ? '<span class="crew-warning-count" title="Unacknowledged warnings">' + esc(c.active_alerts) + '</span>' : ''}</button>`;
  }).join('') : '<div class="empty compact">Import a baseline profile to begin.</div>';
  $$('[data-crew]').forEach(button => button.onclick = guard(() => selectCrew(button.dataset.crew)));
}
function renderHeading() {
  const s = state.snapshot;
  if (!s) { $('#crew-heading').innerHTML = ''; $('#tabs').innerHTML = ''; return; }
  const p = s.profile || {}, personal = p.personal_information || {}, mission = p.mission_details || {};
  $('#page-title').textContent = mission.mission_name || 'Mission overview';
  $('#crew-heading').innerHTML = `<div class="crew-heading"><div class="profile-heading"><span class="avatar">${esc(String(state.id).replace('A-', ''))}</span><div><h2>${esc(profileName(p))}</h2><div class="subtitle">${esc(human(personal.gender))} · ${esc(personal.age ?? '—')} years${mission.destination ? ' · ' + esc(mission.destination) : ''}</div></div></div><div class="mission-facts"><div class="fact"><small>Mission day</small><strong>${s.mission_day ? esc(s.mission_day) : 'Not started'} <span class="muted">/ ${esc(mission.duration_days || '—')}</span></strong></div><div class="fact"><small>Session</small><strong>${esc(s.session_id || '—')}</strong></div>${pill(s.assessment?.overall || 'UNKNOWN')}</div></div>`;
  const tabs = [['overview', 'Overview'], ['findings', 'Findings & treatments'], ['symptoms', 'Symptoms'], ['history', 'Session history'], ['forecasts', 'Forecasts'], ['profile', 'Baseline profile']];
  $('#tabs').innerHTML = tabs.map(([key, label]) => `<button class="tab ${state.tab === key ? 'active' : ''}" data-tab="${key}">${label}${key === 'findings' && arr(s.assessment?.findings).length ? ' (' + arr(s.assessment.findings).length + ')' : ''}</button>`).join('');
  $$('[data-tab]').forEach(b => b.onclick = guard(async () => { state.tab = b.dataset.tab; renderHeading(); if (state.tab === 'history') state.history = await api('GET', idPath() + '/history'); renderContent(); }));
}
function alerts() { return arr(state.snapshot?.alerts).filter(a => !a.acknowledged); }
function alertMessage(a) { return a.message || a.title || a.kind || 'Threshold warning'; }
function alertSeverity(a) { return a.severity || a.level || 'caution'; }
function alertId(a) { return String(a.id ?? a.event_id ?? `${a.timestamp}-${a.key}-${a.kind}`); }
function renderWarnings() {
  const warnings = alerts();
  if (!warnings.length) { $('#warning-region').innerHTML = ''; return; }
  const critical = warnings.some(a => /critical|urgent|emergency/i.test(alertSeverity(a)));
  $('#warning-region').innerHTML = `<div class="warning-banner ${critical ? 'critical' : ''}"><span class="warning-icon">⚠</span><div class="warning-text"><strong>${warnings.length} unacknowledged ${warnings.length === 1 ? 'warning' : 'warnings'}</strong><p>${esc(alertMessage(warnings[0]))}</p></div><button class="button ${critical ? 'danger' : ''}" id="review-warnings">Review warnings</button></div>`;
  $('#review-warnings').onclick = showWarnings;
  const fresh = warnings.filter(a => !state.seenAlerts.has(state.id + ':' + alertId(a)));
  fresh.forEach(a => state.seenAlerts.add(state.id + ':' + alertId(a)));
  if (fresh.length) {
    if (state.sound) beep();
    if ('Notification' in window && Notification.permission === 'granted') {
      const n = new Notification('AstroHealth · ' + state.id, { body: alertMessage(fresh[0]), tag: state.id + ':' + alertId(fresh[0]) });
      n.onclick = () => { window.focus(); showWarnings(); n.close(); };
    }
    showWarnings();
  }
}
function showWarnings() {
  const dialog = $('#warning-dialog');
  dialog.innerHTML = `<button class="modal-close" aria-label="Close">×</button><span class="eyebrow">${esc(state.id)} · LIVE MONITOR</span><h2 class="warning-title">Warnings need attention</h2><p>Acknowledging records that you have seen the warning. It does not change the reading or clear an ongoing condition.</p>${alerts().map(a => `<article class="event"><div class="event-body"><strong>${esc(alertMessage(a))}</strong><p>${esc(date(a.timestamp))}${a.source ? ' · ' + esc(a.source) : ''}</p>${a.key ? `<p>${esc(human(a.key))}: ${fmt(a.value)} ${esc(a.unit || '')}</p>` : ''}</div>${pill(alertSeverity(a))}<button class="chip-button" data-ack="${esc(alertId(a))}">Acknowledge</button></article>`).join('') || '<div class="empty">All warnings acknowledged.</div>'}<div class="form-actions"><button class="button" id="close-warnings">Close</button></div>`;
  $('.modal-close', dialog).onclick = () => dialog.close(); $('#close-warnings').onclick = () => dialog.close();
  $$('[data-ack]', dialog).forEach(b => b.onclick = guard(async () => { await api('POST', idPath() + '/ack', { event_id: b.dataset.ack }); await refresh(); showWarnings(); }));
  if (!dialog.open) dialog.showModal();
}
function beep() {
  try { const ctx = state.audio || (state.audio = new (window.AudioContext || window.webkitAudioContext)()); ctx.resume(); const osc = ctx.createOscillator(), gain = ctx.createGain(); osc.connect(gain); gain.connect(ctx.destination); osc.frequency.value = 660; gain.gain.setValueAtTime(.08, ctx.currentTime); gain.gain.exponentialRampToValueAtTime(.001, ctx.currentTime + .45); osc.start(); osc.stop(ctx.currentTime + .45); } catch (_) { /* Browser sound requires a user gesture. */ }
}
function readingRows() {
  const rows = state.snapshot?.readings;
  if (Array.isArray(rows)) return rows;
  return Object.entries(rows || {}).map(([key, value]) => ({ key, ...(typeof value === 'object' ? value : { value }) }));
}
function readingCard(row) {
  const baseline = row.baseline;
  return `<article class="reading-card ${esc(row.status || 'missing')}"><div class="reading-top"><h3>${esc(row.label || human(row.key))}</h3>${pill(row.status || 'missing')}</div><div class="reading-values"><div class="reading-current">${fmt(row.value)}<small>${esc(row.unit || '')}</small></div><div class="baseline"><small>Personal baseline</small><span>${baseline?.value != null ? fmt(baseline.value) + ' <small>' + esc(baseline.unit || row.unit || '') + '</small>' : 'Not supplied'}</span></div></div><div class="reading-note">${sourceBadge(row.source)}<br>${esc(row.reason || (row.timestamp ? date(row.timestamp) : 'Awaiting measurement'))}${row.reason && row.timestamp ? '<br>' + esc(date(row.timestamp)) : ''}${baseline?.timestamp ? '<br>Baseline: ' + esc(date(baseline.timestamp)) : ''}</div></article>`;
}
function rowCategory(row) {
  return row.category || arr(state.meta.readings).find(r => r.key === row.key)?.category || '';
}
function compactRows(rows) {
  return summaryTable(rows, [['Measurement', r => esc(r.label || human(r.key))], ['Current', r => fmt(r.value) + ' ' + esc(r.unit || '')], ['Personal baseline', r => r.baseline?.value != null ? fmt(r.baseline.value) + ' ' + esc(r.baseline.unit || r.unit || '') : 'Not supplied'], ['Status', r => pill(r.status || 'missing')], ['Context', r => esc(r.reason || date(r.timestamp))]]);
}
function renderOverview() {
  const rows = readingRows(), vitals = rows.filter(r => ['cardiovascular', 'respiratory', 'vital', 'environment'].includes(rowCategory(r))), labs = rows.filter(r => r.type === 'lab' || rowCategory(r) === 'blood_panel'), radiation = rows.filter(r => rowCategory(r) === 'radiation'), manual = rows.filter(r => rowCategory(r) === 'symptom' && r.value != null);
  const monitoring = state.snapshot.monitoring || {};
  const sim = state.monitor.simulation?.active?.[state.id];
  const labCount = labs.filter(r => r.value != null).length;
  const radiationCount = radiation.filter(r => r.value != null).length;
  return `<div class="section-header"><div><h2>Current measurements</h2><p>Current value and preflight baseline · assessed against the supplied limits</p></div><span class="simulation-label">${monitoring.synthetic ? '● SIMULATED DATA' : '● ' + esc(String(monitoring.source || 'AWAITING SOURCE').toUpperCase())}</span></div>${!state.snapshot.mission_day ? '<div class="inline-message">Monitoring begins with the first valid in-mission measurement. Preflight baselines are reference values and do not populate current readings.</div>' : ''}<div class="grid vitals-grid">${vitals.map(readingCard).join('') || '<div class="empty">No current sensor measurements. Start a simulation or supply sensor packets.</div>'}</div>${manual.length ? '<div class="grid vitals-grid spaced-top">' + manual.map(readingCard).join('') + '</div>' : ''}<details class="panel overview-details" data-detail="overview-labs" ${state.openDetails.has('overview-labs') ? 'open' : ''}><summary><strong>Laboratory results</strong><span class="muted small">${labCount ? labCount + ' imported measurements' : 'No results imported'} · Expand</span></summary><p class="hint spaced-top">Manually imported results retain their collection dates. Baselines remain separate from current results.</p>${compactRows(labs)}</details><details class="panel overview-details" data-detail="overview-radiation" ${state.openDetails.has('overview-radiation') ? 'open' : ''}><summary><strong>Radiation & exposure windows</strong><span class="muted small">${radiationCount} quantities reported · Expand</span></summary><p class="hint spaced-top">Required windows and exposure provenance must be available before comparison. Career baseline values do not establish complete history.</p>${compactRows(radiation)}</details><section class="panel"><div class="section-header"><div><h2>Simulation console</h2><p>Explicit test data, isolated from observed measurements. No physical device is required.</p></div><span class="pill projected">${sim ? 'Running' : 'Stopped'}</span></div><div class="simulation-controls"><select id="simulation-mode" aria-label="Simulation mode"><option value="normal">Within limits</option><option value="caution">Caution values</option><option value="critical">Critical values</option><option value="qtc">Prolonged QTc</option><option value="cardiac_arrest">Heart-rate collapse</option></select><button class="button primary" data-simulation="start">Start continuous</button><button class="button" data-simulation="once">One reading / scenario</button><button class="button" data-simulation="stop">Stop</button></div><p class="hint simulation-hint">Heart-rate collapse plays an increase followed by zero within the 60-second buffer. A zero vital value raises a warning; poor signal remains distinct from a possible arrest.</p></section><div class="panel"><div class="section-header"><div><h2>Session storage</h2><p>Normal sensor samples remain in memory for ${esc(monitoring.buffer_seconds || 60)} seconds.</p></div><button class="button subtle" id="import-packet">Import sensor packet</button></div><div class="forecast-numbers"><div><small>Buffer samples</small>${esc(monitoring.buffer_samples ?? 0)}</div><div><small>Daily retention</small>Averages & totals</div><div><small>Warnings</small>Saved as events</div></div><p class="hint no-margin">${esc(monitoring.retention_note || 'Longer-term session history stores derived summaries and exposure coverage. A missing exposure window remains unassessed.')}</p></div>`;
}

function bulletList(items) { return arr(items).length ? '<ul>' + items.map(x => '<li>' + esc(typeof x === 'string' ? x : JSON.stringify(x)) + '</li>').join('') + '</ul>' : ''; }
function sourceLinks(sources) {
  const items = Array.isArray(sources) ? sources : sources ? [sources] : [];
  return items.map(s => {
    if (typeof s === 'object') { const url = safeUrl(s.url); return url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(s.reference || s.document || url)} ↗</a>` : esc(s.reference || s.document || JSON.stringify(s)); }
    const match = String(s).match(/https?:\/\/\S+/), url = match ? safeUrl(match[0]) : '';
    return url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(s)} ↗</a>` : '<p>' + esc(s) + '</p>';
  }).join('');
}
function treatmentHtml(t) {
  const detailKey = "treatment:" + (t.treatment_name || t.name || "reference");
  return `<details class="treatment" data-detail="${esc(detailKey)}" ${state.openDetails.has(detailKey) ? "open" : ""}><summary><h4>${esc(t.treatment_name || t.name || 'Treatment reference')}</h4><span class="muted tiny">${esc(t.indication || t.context || 'Supplied treatment reference')} · Expand details</span></summary><div class="treatment-detail">${t.diagnostic_markers ? '<p><strong>Indication context:</strong> ' + esc(t.diagnostic_markers) + '</p>' : ''}${bulletList(t.instructions)}${t.dosage ? '<p><strong>Dosage in source:</strong> ' + esc(t.dosage) + '</p>' : ''}${t.warnings_and_interactions ? '<p class="warning-copy"><strong>Warnings & interactions:</strong> ' + esc(t.warnings_and_interactions) + '</p>' : ''}${t.context ? '<p><strong>Context:</strong> ' + esc(t.context) + '</p>' : ''}<div class="sources">${sourceLinks(t.sources)}</div></div></details>`;
}
function findingHtml(f) {
  const key = f.rule_id || f.condition_id || f.name;
  const evidence = arr(f.evidence).map(e => e.kind === 'symptom' ? state.meta.symptoms_en?.[e.id] || human(e.id) : e.kind === 'context' ? state.meta.context_en?.[e.id] || human(e.id) : `${human(e.key)} ${fmt(e.value)}${e.level ? ' · ' + human(e.level) : ''}`);
  return `<details class="finding" data-detail="${esc(key)}" ${state.openDetails.has(key) ? 'open' : ''}><summary>${pill(f.level || f.numeric_level || 'MONITOR')}<div><div class="finding-name">${esc(f.name || human(f.condition_id))}</div><div class="finding-id">${esc(key)} · ${esc(f.group || 'Decision support')}${f.privacy_sensitive ? ' · Sensitive' : ''}</div></div></summary><div class="finding-body">${f.escalation_only ? '<p class="warning-copy">Warning signs associated with this condition. The base condition has not been established.</p>' : ''}<div class="evidence">${evidence.map(e => '<span>' + esc(e) + '</span>').join('')}</div>${f.logic ? '<p class="spaced-top">' + esc(f.logic) + '</p>' : ''}${f.red_flag_text ? '<p class="warning-copy">' + esc(f.red_flag_text) + '</p>' : ''}${arr(f.severity_markers).length ? '<h3>Severity markers</h3>' + bulletList(f.severity_markers) : ''}${arr(f.confirmation).length ? '<h3>Confirmation</h3>' + bulletList(f.confirmation) : ''}${arr(f.do_not).length ? '<h3>Do not</h3>' + bulletList(f.do_not) : ''}${f.hide_therapy ? '<p class="warning-copy">Routine treatment guidance is withheld because warning signs require evaluation.</p>' : '<h3>Linked treatment references</h3>' + (arr(f.treatments).length ? f.treatments.map(treatmentHtml).join('') : '<p>No detailed treatment entry is linked to this finding.</p>')}${f.limitations ? '<p>' + esc(f.limitations) + '</p>' : ''}${f.source ? '<h3>Diagnostic source</h3><div class="sources">' + sourceLinks(f.source) + '</div>' : ''}</div></details>`;
}
function renderFindings() {
  const findings = arr(state.snapshot.assessment?.findings);
  const library = state.meta.treatments_reference || state.meta.treatment_library || state.meta.treatments || [];
  return `<div class="section-header"><div><h2>Findings & treatment references</h2><p>Findings explain the evidence that triggered a supplied diagnostic rule.</p></div>${pill(state.snapshot.assessment?.overall)}</div><div class="findings-list">${findings.map(findingHtml).join('') || '<div class="empty panel">No diagnostic findings are active.<br>Missing measurements do not establish that a condition is absent.</div>'}</div>${arr(library).length ? '<section class="panel"><h2>Treatment reference library</h2><p class="hint">Reference entries are not automatic diagnoses. Potassium and magnesium have no supplied thresholds and do not trigger automatic findings.</p><input class="search library-search" id="library-search" placeholder="Search treatment topics…" aria-label="Search treatment topics"><div id="library-items">' + library.map((item, i) => `<details class="finding library-item" data-detail="${esc("library:" + (item.condition_id || i))}" ${state.openDetails.has("library:" + (item.condition_id || i)) ? "open" : ""} data-library-text="${esc((item.condition_name || item.name || item.condition_id || '').toLowerCase())}"><summary><div><div class="finding-name">${esc(item.condition_name || item.name || human(item.condition_id))}</div><div class="finding-id">${esc(item.condition_id || '')}</div></div></summary><div class="finding-body">${arr(item.treatments).map(treatmentHtml).join('')}</div></details>`).join('') + '</div></section>' : ''}`;
}
function choiceHtml(key, label, set, kind) { return `<label class="choice"><input type="checkbox" data-choice="${kind}" value="${esc(key)}" ${set.has(key) ? 'checked' : ''}><span>${esc(label)}</span></label>`; }
function renderSymptoms() {
  const symptoms = Object.entries(state.meta.symptoms_en || {}), context = Object.entries(state.meta.context_en || {}), derived = [...Object.entries(state.meta.derived || {}), ...arr(state.meta.readings).filter(r => r.category === 'symptom').map(r => [r.key, r])];
  const saved = state.snapshot.state?.readings || {};
  return `<div class="section-header"><div><h2>Reported symptoms & context</h2><p>These are manual reports. Sensor readings continue independently.</p></div><span class="selection-count" id="selection-count">${state.selectedSymptoms.size} symptoms selected</span></div><div class="symptom-toolbar"><input class="search" id="symptom-search" placeholder="Find a symptom…" value="${esc(state.symptomSearch)}" aria-label="Search symptoms"><button class="button subtle" id="clear-symptoms">Clear</button></div><div class="choices" id="symptom-choices">${symptoms.map(([k, v]) => choiceHtml(k, v, state.selectedSymptoms, 'symptom')).join('')}</div><section class="panel"><h2>Context</h2><div class="choices spaced-top">${context.map(([k, v]) => choiceHtml(k, v, state.selectedContext, 'context')).join('')}</div></section>${derived.length ? '<section class="panel"><h2>Manual measurements</h2><p class="hint">Only enter values that were actually measured or reported. Leave unavailable values blank.</p><div class="form-grid">' + derived.map(([k, v]) => `<label class="field">${esc(v.label || v.description || human(k))}${v.unit ? ' (' + esc(v.unit) + ')' : ''}<input type="number" step="any" data-derived="${esc(k)}" value="${esc(saved[k] ?? '')}" placeholder="Not supplied"></label>`).join('') + '</div></section>' : ''}<div class="form-actions"><span class="hint" id="symptom-save-state">${state.symptomDirty ? 'Unsaved changes' : 'Reports saved independently of sensor samples'}</span><button class="button primary" id="save-symptoms">Save reports & assess</button></div>`;
}
function summaryTable(rows, columns) {
  if (!rows.length) return '<div class="empty">No records yet.</div>';
  return `<div class="table-scroll"><table><thead><tr>${columns.map(c => '<th>' + esc(c[0]) + '</th>').join('')}</tr></thead><tbody>${rows.map(r => '<tr>' + columns.map(c => '<td>' + c[1](r) + '</td>').join('') + '</tr>').join('')}</tbody></table></div>`;
}
function jsonDetails(row, label = 'Details') { return `<details><summary>${esc(label)}</summary><pre>${esc(JSON.stringify(row, null, 2))}</pre></details>`; }
function renderHistory() {
  const h = state.history;
  if (!h) return '<div class="empty">Loading session history…</div>';
  const daily = arr(h.daily), sessions = arr(h.sessions), events = arr(h.events), labs = arr(h.lab_reports);
  return `<div class="section-header"><div><h2>Session history</h2><p>Daily summaries, accumulated exposure, imported tests and abnormal events.</p></div><button class="button subtle" id="refresh-history">Refresh</button></div><section class="history-section"><h3>Abnormal events · ${events.length}</h3><div class="event-list">${events.slice().reverse().map(e => `<article class="event">${pill(e.severity || e.level || 'MONITOR')}<div class="event-body"><strong>${esc(e.message || human(e.kind) || human(e.key))}</strong><p>${esc(date(e.timestamp || e.started_at))}${e.source ? ' · ' + esc(e.source) : ''}${e.acknowledged ? ' · Acknowledged' : ''}</p>${e.key ? '<p>' + esc(human(e.key)) + ': ' + fmt(e.value) + ' ' + esc(e.unit || '') + '</p>' : ''}${e.details || e.sequence ? jsonDetails(e.details || e.sequence, 'Event evidence') : ''}</div></article>`).join('') || '<div class="empty">No abnormal events recorded.</div>'}</div></section><section class="history-section"><h3>Daily summaries · ${daily.length}</h3><p class="hint">Completed days and closed sessions are retained. Today’s running summary stays in memory until rollover or clean shutdown.</p>${summaryTable(daily, [['Day', r => esc(r.day || r.date || r.utc_date || r.day_utc || '—')], ['Source', r => sourceBadge(r.source || r.origin || 'recorded')], ['Measurement', r => esc(r.key || r.measurement_key || r.measurement_type || 'Summary')], ['Average', r => fmt(r.mean ?? r.average ?? r.avg)], ['Min / max', r => fmt(r.min ?? r.minimum) + ' / ' + fmt(r.max ?? r.maximum)], ['Coverage / details', r => jsonDetails(r, 'View summary')]])}</section><section class="history-section"><h3>Sessions · ${sessions.length}</h3>${summaryTable(sessions, [['Session', r => esc(r.id || r.session_id || '—')], ['Started', r => esc(date(r.started_at || r.start_time))], ['Ended', r => r.ended_at || r.end_time ? esc(date(r.ended_at || r.end_time)) : 'Active'], ['Source', r => sourceBadge(r.source || 'recorded')], ['Details', r => jsonDetails(r)]])}</section><section class="history-section"><h3>Imported laboratory reports · ${labs.length}</h3>${labs.map(l => '<div class="panel history-lab"><strong class="small">' + esc(date(l.timestamp || l.collected_at || l.imported_at)) + '</strong>' + jsonDetails(l, 'View dated report') + '</div>').join('') || '<div class="empty">No laboratory reports imported.</div>'}</section>`;
}
function forecastHtml(f) {
  if (!f) return '';
  const projected = f.projected_value ?? f.projected_total ?? f.projected;
  const limit = f.limit ?? f.threshold;
  const days = f.days_to_limit ?? f.days_to_threshold;
  const crossing = f.crossing_date || f.estimated_crossing_date;
  const number = typeof projected === 'number' && typeof limit === 'number' && limit > 0 ? Math.max(0, Math.min(100, projected / limit * 100)) : null;
  return `<article class="forecast-card"><div class="forecast-title">${pill(f.status && /insufficient|unassessed|needs|missing|unavailable/i.test(f.status) ? 'needs_context' : 'projected')}<h3>${esc(f.label || human(f.key || f.measurement_type || 'Exposure scenario'))}</h3></div>${f.status && /insufficient|unassessed|needs|missing|unavailable/i.test(f.status) ? '<div class="forecast-result">More context needed</div>' : days != null ? '<div class="forecast-result">' + fmt(days) + ' days to reference limit</div>' : projected != null ? '<div class="forecast-result">' + fmt(projected) + ' ' + esc(f.unit || '') + ' projected</div>' : ''}<p>${esc(f.message || f.reason || f.explanation || 'Conditional estimate assuming the specified exposure rate continues.')}</p><div class="forecast-numbers">${f.current_value != null || f.current_total != null ? '<div><small>Current total</small>' + fmt(f.current_value ?? f.current_total) + ' ' + esc(f.unit || '') + '</div>' : ''}${limit != null ? '<div><small>Reference limit</small>' + fmt(limit) + ' ' + esc(f.unit || '') + '</div>' : ''}${f.daily_rate != null ? '<div><small>Daily rate</small>' + fmt(f.daily_rate) + ' ' + esc(f.unit || '') + '/day</div>' : ''}${projected != null ? '<div><small>Projected total</small>' + fmt(projected) + ' ' + esc(f.unit || '') + '</div>' : ''}${crossing ? '<div><small>Conditional crossing</small>' + esc(date(crossing)) + '</div>' : ''}</div>${number != null ? '<progress class="forecast-progress" max="100" value="' + number + '"></progress>' : ''}${f.assumptions || f.assumption ? '<p class="hint spaced-top">' + esc(Array.isArray(f.assumptions) ? f.assumptions.join(' · ') : f.assumptions || f.assumption) + '</p>' : ''}<details><summary class="tiny muted">Calculation context</summary><pre>${esc(JSON.stringify(f, null, 2))}</pre></details></article>`;
}
function renderForecasts() {
  const radiation = arr(state.meta.readings).filter(r => r.category === 'radiation');
  const trends = arr(state.snapshot.forecasts), supported = trends.filter(f => !/insufficient|unassessed|needs|missing|unavailable/i.test(f.status || '')), pending = trends.filter(f => /insufficient|unassessed|needs|missing|unavailable/i.test(f.status || ''));
  return `<div class="section-header"><div><h2>Exposure forecasts</h2><p>Conditional estimates remain separate from current measurements and alerts.</p></div></div><div class="inline-message">A projected crossing does not mean the limit has already been exceeded. Unknown coverage or missing dose context remains unassessed. Career, mission and organ doses use their own quantities and units.</div><section class="panel"><h2>Measured exposure trend</h2><p class="hint">A trend requires sufficient dated exposure history and usable coverage. Normal daily sensor readings alone cannot establish organ dose.</p>${supported.map(forecastHtml).join('') || '<div class="empty">No supported trend yet. Continue monitoring with dated exposure reports, or explore a hypothetical rate below.</div>'}${pending.length ? '<details><summary class="small muted">Coverage needed for ' + pending.length + ' dose quantities</summary><div class="spaced-top">' + summaryTable(pending, [['Quantity', f => esc(human(f.key))], ['Missing context', f => esc(f.reason || f.message)]]) + '</div></details>' : ''}</section><section class="panel"><h2>What-if exposure scenario</h2><p class="hint">Use an explicit future daily exposure rate. Mission limits use the planned ${esc(state.snapshot.profile?.mission_details?.duration_days || '—')}-day duration.</p><form id="forecast-form"><div class="form-grid"><label class="field">Dose quantity<select id="forecast-key">${(radiation.length ? radiation : [{ key: 'nuclear_source_dose', label: 'Extra dose from nuclear technologies', unit: 'mSv' }]).map(r => `<option value="${esc(r.key)}" data-unit="${esc(r.unit)}" ${r.key === 'nuclear_source_dose' ? 'selected' : ''}>${esc(r.label || human(r.key))}</option>`).join('')}</select></label><label class="field">Daily exposure rate<input type="number" id="forecast-rate" step="any" min="0" value="0.1" required><small id="forecast-unit">mSv per day</small></label><label class="field">Days ahead<input type="number" id="forecast-days" min="1" max="3650" value="21" required></label></div><div class="form-actions"><button class="button primary" type="submit">Calculate scenario</button></div></form><div id="scenario-result">${forecastHtml(state.forecast)}</div></section>`;
}
function kv(label, value) { return `<div class="kv"><dt>${esc(label)}</dt><dd>${esc(value ?? 'Not supplied')}</dd></div>`; }
function tags(values) { return arr(values).length ? '<div class="tag-list">' + values.map(v => '<span class="tag">' + esc(human(v)) + '</span>').join('') + '</div>' : '<span class="muted small">None reported</span>'; }
function renderProfile() {
  const p = state.snapshot.profile || {}, info = p.personal_information || {}, med = p.medical_history || {}, mission = p.mission_details || {};
  const allergies = arr(med.allergies).filter(x => String(x).toLowerCase() !== 'none');
  return `<div class="section-header"><div><h2>Personal baseline profile</h2><p>Preserved preflight values, dates and medical history for this astronaut.</p></div><button class="button subtle" id="export-profile">Export profile JSON</button></div><div class="profile-grid"><section class="panel"><h2>Astronaut</h2><dl>${kv('ID', p.astronaut_id)}${kv('Age', info.age)}${kv('Gender', human(info.gender))}${kv('Blood group', info.blood_type)}${kv('Weight', info.weight_kg != null ? info.weight_kg + ' kg' : null)}${kv('Height', info.height_cm != null ? info.height_cm + ' cm' : null)}</dl></section><section class="panel"><h2>Mission</h2><dl>${kv('Name', mission.mission_name)}${kv('Destination', mission.destination)}${kv('Planned duration', mission.duration_days ? mission.duration_days + ' days' : null)}${kv('Current mission day', state.snapshot.mission_day || 'Awaiting first measurement')}${kv('Day one', 'UTC date of first valid in-mission measurement')}</dl></section><section class="panel"><h2>Medical history</h2><h3 class="spaced-top">Past conditions</h3>${tags(med.past_conditions)}<h3 class="spaced-top">Current medications</h3>${tags(med.current_medications)}<h3 class="spaced-top">Allergies</h3>${tags(allergies)}<dl>${kv('VTE history', med.vte_history === true ? 'Reported' : med.vte_history === false ? 'Not reported' : null)}</dl></section><section class="panel"><h2>Preflight baseline</h2><p class="hint">Baseline readings stay separate from in-mission samples. Values with no threshold are retained as profile information and do not trigger automatic findings.</p><dl>${kv('Blood tests collected', date(p.pre_flight_baseline?.blood_tests?.date))}${kv('Cardiovascular baseline', date(p.pre_flight_baseline?.cardiovascular?.date))}${kv('Career dose at start', p.pre_flight_baseline?.radiation_exposure?.career_effective_dose_start?.value != null ? p.pre_flight_baseline.radiation_exposure.career_effective_dose_start.value + ' ' + p.pre_flight_baseline.radiation_exposure.career_effective_dose_start.unit : null)}</dl><p class="hint">A supplied career baseline does not by itself verify complete dosimetry history.</p></section></div><section class="panel"><details><summary class="small">View complete original profile document</summary><pre>${esc(JSON.stringify(p, null, 2))}</pre></details></section>`;
}
function renderContent() {
  if (!state.snapshot) { $('#content').innerHTML = '<div class="empty large">Import a baseline profile to begin monitoring.</div>'; return; }
  const renderer = { overview: renderOverview, findings: renderFindings, symptoms: renderSymptoms, history: renderHistory, forecasts: renderForecasts, profile: renderProfile }[state.tab] || renderOverview;
  $('#content').innerHTML = renderer();
  bindContent();
}
function bindContent() {
  $$('[data-simulation]').forEach(b => b.onclick = guard(async () => {
    const mode = $('#simulation-mode').value;
    await api('POST', idPath() + '/simulate', { action: b.dataset.simulation, mode, interval_seconds: 2 });
    toast(b.dataset.simulation === 'stop' ? 'Simulation stopped. Buffered samples expire after 60 seconds.' : mode === 'cardiac_arrest' ? 'Heart-rate collapse scenario started.' : 'Simulation data submitted.');
    await refresh();
  }));
  if ($('#import-packet')) $('#import-packet').onclick = () => openImport('packet');
  $$('[data-detail]').forEach(d => d.ontoggle = () => d.open ? state.openDetails.add(d.dataset.detail) : state.openDetails.delete(d.dataset.detail));
  if ($('#library-search')) $('#library-search').oninput = e => $$('.library-item').forEach(item => item.hidden = !item.dataset.libraryText.includes(e.target.value.toLowerCase()));
  if ($('#symptom-search')) {
    $('#symptom-search').oninput = e => { state.symptomSearch = e.target.value; filterSymptoms(); };
    filterSymptoms();
    $$('[data-choice]').forEach(input => input.onchange = () => {
      const set = input.dataset.choice === 'symptom' ? state.selectedSymptoms : state.selectedContext;
      input.checked ? set.add(input.value) : set.delete(input.value); state.symptomDirty = true;
      $('#selection-count').textContent = `${state.selectedSymptoms.size} symptoms selected`; $('#symptom-save-state').textContent = 'Unsaved changes';
    });
    $$('[data-derived]').forEach(i => i.oninput = () => { state.symptomDirty = true; $('#symptom-save-state').textContent = 'Unsaved changes'; });
    $('#clear-symptoms').onclick = () => { state.selectedSymptoms.clear(); state.selectedContext.clear(); state.symptomDirty = true; $$('[data-choice]').forEach(i => i.checked = false); $('#selection-count').textContent = '0 symptoms selected'; $('#symptom-save-state').textContent = 'Unsaved changes'; };
    $('#save-symptoms').onclick = guard(async () => {
      const readings = {}; $$('[data-derived]').forEach(i => { readings[i.dataset.derived] = i.value.trim() === '' ? null : Number(i.value); });
      state.snapshot = await api('PUT', idPath() + '/symptoms', { symptoms: [...state.selectedSymptoms], context: [...state.selectedContext], readings });
      state.symptomDirty = false; toast('Reports saved. Findings updated.'); renderHeading(); renderWarnings(); renderContent();
    });
  }
  if ($('#refresh-history')) $('#refresh-history').onclick = guard(async () => { state.history = await api('GET', idPath() + '/history'); renderContent(); });
  if ($('#forecast-form')) {
    const updateUnit = () => { $('#forecast-unit').textContent = ($('#forecast-key').selectedOptions[0]?.dataset.unit || '') + ' per day'; };
    $('#forecast-key').onchange = updateUnit; updateUnit();
    $('#forecast-form').onsubmit = guard(async e => { e.preventDefault(); const select = $('#forecast-key'); state.forecast = await api('POST', idPath() + '/forecast', { key: select.value, daily_rate: Number($('#forecast-rate').value), unit: select.selectedOptions[0]?.dataset.unit, horizon_days: Number($('#forecast-days').value) }); $('#scenario-result').innerHTML = forecastHtml(state.forecast); });
  }
  if ($('#export-profile')) $('#export-profile').onclick = () => { const blob = new Blob([JSON.stringify(state.snapshot.profile, null, 2)], { type: 'application/json' }); const link = document.createElement('a'); const url = URL.createObjectURL(blob); link.href = url; link.download = state.id + '_profile.json'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); };
}
function filterSymptoms() { const query = state.symptomSearch.toLowerCase(); $$('#symptom-choices .choice').forEach(choice => choice.hidden = !choice.textContent.toLowerCase().includes(query)); }
function openImport(kind) {
  if (kind !== 'profile' && !state.id) return toast('Import a crew profile first.');
  const title = { profile: 'Import astronaut baseline', lab: 'Import laboratory results', packet: 'Import sensor packet' }[kind];
  const description = { profile: 'Use one baseline JSON document per astronaut. Importing a baseline does not create live measurements.', lab: 'Select a dated JSON blood-test report. Only measurements with supplied thresholds are automatically assessed. Existing personal baseline files are not current lab reports.', packet: 'Import a normalized sensor packet or a supported Fresh packet. Each measurement needs its explicit unit and acquisition timestamp.' }[kind];
  const dialog = $('#import-dialog');
  dialog.innerHTML = `<button class="modal-close" aria-label="Close">×</button><h2>${title}</h2><p>${description}</p><label class="field">JSON file<input type="file" id="json-file" accept=".json,application/json"></label><label class="field">Or paste JSON<textarea id="json-text" spellcheck="false" placeholder="Paste a JSON document…"></textarea></label><div class="form-actions"><button class="button" id="cancel-import">Cancel</button><button class="button primary" id="submit-import">Import ${kind === 'profile' ? 'profile' : kind === 'lab' ? 'results' : 'packet'}</button></div>`;
  $('.modal-close', dialog).onclick = () => dialog.close(); $('#cancel-import').onclick = () => dialog.close();
  $('#json-file').onchange = guard(async e => { if (e.target.files[0]) $('#json-text').value = await e.target.files[0].text(); });
  $('#submit-import').onclick = guard(async () => {
    const text = $('#json-text').value.trim(); if (!text) throw new Error('Select a JSON file or paste its contents.');
    let payload; try { payload = JSON.parse(text); } catch (_) { throw new Error('The document is not valid JSON.'); }
    const result = await api('POST', kind === 'profile' ? '/astronauts' : idPath() + (kind === 'lab' ? '/lab' : '/ingest'), payload);
    dialog.close();
    if (kind === 'profile') { state.crew = await api('GET', '/astronauts'); await selectCrew(result.id || result.astronaut_id || payload.astronaut_id); }
    else { await refresh(); if (kind === 'lab') { state.tab = 'overview'; renderHeading(); renderContent(); } }
    toast(title.replace('Import', 'Imported') + '.');
  });
  dialog.showModal();
}
async function selectCrew(id) {
  state.id = id; state.snapshot = await api('GET', idPath()); state.history = null; state.forecast = null; state.symptomDirty = false; state.openDetails.clear();
  syncReports(); renderCrew(); renderHeading(); renderWarnings();
  if (state.tab === 'history') state.history = await api('GET', idPath() + '/history');
  renderContent();
}
function syncReports() {
  if (state.symptomDirty) return;
  state.selectedSymptoms = new Set(state.snapshot?.state?.symptoms || state.snapshot?.symptoms || []);
  state.selectedContext = new Set(state.snapshot?.state?.context || state.snapshot?.context || []);
}
async function refresh() {
  if (state.polling) return; state.polling = true;
  try {
    const [crew, monitor] = await Promise.all([api('GET', '/astronauts'), api('GET', '/monitor')]);
    state.crew = crew; state.monitor = monitor;
    for (const member of crew) {
      const memberId = member.id || member.astronaut_id, count = member.active_alerts || 0;
      if (memberId !== state.id && count > (state.crewAlertCounts[memberId] || 0) && state.id) {
        toast(memberId + ': ' + count + ' warning(s) need attention. Select this crew member to review.');
        if (state.sound) beep();
        if ('Notification' in window && Notification.permission === 'granted') { const n = new Notification('AstroHealth · ' + memberId, { body: count + ' warning(s) need attention.', tag: memberId + ':crew' }); n.onclick = () => { window.focus(); selectCrew(memberId).catch(e => toast(e.message)); n.close(); }; }
      }
      state.crewAlertCounts[memberId] = count;
    }
    if (!state.id && crew.length) { const requested = new URLSearchParams(location.search).get('astronaut'); const first = crew.find(c => (c.id || c.astronaut_id) === requested) || crew.find(c => c.active_alerts > 0) || crew[0]; state.id = first.id || first.astronaut_id; }
    if (state.id && !crew.some(c => (c.id || c.astronaut_id) === state.id)) state.id = crew[0]?.id || crew[0]?.astronaut_id || null;
    if (state.id) state.snapshot = await api('GET', idPath()); else state.snapshot = null;
    connection(true); syncReports(); renderCrew(); renderHeading(); renderWarnings();
    // Preserve forms, open treatment references, and scroll position during background updates.
    if (state.tab === 'overview') {
      const mode = $('#simulation-mode')?.value;
      const top = window.scrollY; renderContent(); if (mode && $('#simulation-mode')) $('#simulation-mode').value = mode; window.scrollTo(0, top);
    } else if (state.tab === 'findings') {
      const top = window.scrollY; renderContent(); window.scrollTo(0, top);
    } else if (!$('#content').children.length) renderContent();
  } catch (e) { connection(false); if (!state.snapshot) $('#content').innerHTML = `<div class="empty large">The local monitor is unavailable.<br>${esc(e.message)}<br>Keep the Python application running, then this page will reconnect.</div>`; }
  finally { state.polling = false; }
}
$('#import-profile').onclick = () => openImport('profile');
$('#import-lab').onclick = () => openImport('lab');
$('#sound-toggle').onchange = e => { state.sound = e.target.checked; if (state.sound) beep(); };
$('#notification-toggle').onclick = guard(async () => {
  if (!('Notification' in window)) return toast('This browser does not support desktop notifications.');
  const permission = await Notification.requestPermission();
  $('#notification-toggle').textContent = permission === 'granted' ? 'Notifications enabled' : 'Notifications unavailable';
  toast(permission === 'granted' ? 'Browser notifications enabled while this page is open.' : 'Allow notifications in browser settings, or use the background warning launcher.');
});
async function initialize() {
  try { state.meta = await api('GET', '/meta'); await refresh(); if (state.snapshot) { renderContent(); } }
  catch (e) { connection(false); $('#content').innerHTML = `<div class="empty large">Unable to connect to the monitor.<br>${esc(e.message)}</div>`; }
  setInterval(async () => { if (!Object.keys(state.meta).length) { try { state.meta = await api('GET', '/meta'); } catch (_) { /* Retried next poll. */ } } await refresh(); }, 2000);
}
initialize();
