'use strict';
const $ = (id) => document.getElementById(id);
let report = null;
let demoDocuments = null;
const help = {
  demo: 'Three fictional documents let you explore the workflow. This is demonstration data.',
  local: 'Research your own documents locally. Excerpt mode does not send them to external services.',
  tavily: 'Search queries are sent to Tavily. Set TAVILY_API_KEY on the server before starting.',
  plan: 'Outline evidence needs only. No sources are collected and no findings are asserted.'
};
function element(tag, text, className) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (className) el.className = className;
  return el;
}
function activateTab(name) {
  document.querySelectorAll('[data-tab]').forEach(button => {
    const selected = button.dataset.tab === name;
    button.setAttribute('aria-selected', String(selected));
    button.tabIndex = selected ? 0 : -1;
  });
  ['findings', 'sources', 'plan'].forEach(id => { $(id).hidden = id !== name; });
}
document.querySelectorAll('[data-tab]').forEach((button, index, tabs) => {
  button.addEventListener('click', () => activateTab(button.dataset.tab));
  button.addEventListener('keydown', (event) => {
    let next;
    if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
    if (event.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = tabs.length - 1;
    if (next !== undefined) { event.preventDefault(); activateTab(tabs[next].dataset.tab); tabs[next].focus(); }
  });
});
function updateMode() {
  $('source-help').textContent = help[$('provider').value];
  $('upload-wrap').hidden = $('provider').value !== 'local';
  if ($('provider').value === 'plan') $('synthesis').value = 'extractive';
  $('synthesis').disabled = $('provider').value === 'plan' || $('team-enabled').checked;
  $('team-settings').hidden = !$('team-enabled').checked;
  $('model-wrap').hidden = $('synthesis').value !== 'openai' || $('team-enabled').checked;
}
$('provider').addEventListener('change', updateMode);
$('synthesis').addEventListener('change', updateMode);
$('example').addEventListener('click', () => {
  $('topic').value = 'How should we evaluate a research assistant for our team?';
  $('provider').value = 'demo';
  updateMode();
  $('topic').focus();
});
function render(result, demo) {
  report = result;
  $('results').hidden = false;
  const sources = result.sources.filter(source => source.status === 'collected');
  $('status').textContent = result.warnings.length ? 'Completed with warnings' : 'Research complete';
  $('mode-label').textContent = demo ? 'SAMPLE RESEARCH · FICTIONAL DATA' : result.mode === 'plan' ? 'RESEARCH PLAN' : 'EVIDENCE BRIEF';
  $('warnings').replaceChildren();
  const warnings = [...result.warnings];
  if (demo) warnings.unshift('Demonstration only. These documents describe a fictional team and do not support real-world conclusions.');
  if (!sources.length) warnings.push('No evidence was collected. This report does not support any conclusions.');
  warnings.forEach(warning => $('warnings').append(element('p', warning, 'notice')));
  $('metrics').replaceChildren();
  [[result.tasks.length, 'Research tasks'], [sources.length, 'Unique sources'], [result.findings.reduce((n, f) => n + f.citations.length, 0), 'Checked citations']].forEach(([value, label]) => {
    const metric = element('div', undefined, 'metric');
    metric.append(element('strong', value), element('span', label));
    $('metrics').append(metric);
  });
  $('result-title').textContent = result.question.topic;
  $('result-context').textContent = `For ${result.question.audience}. Citations match collected text; source accuracy and claim support still need review.`;
  $('findings').replaceChildren();
  result.findings.forEach(finding => {
    const card = element('article', undefined, 'finding');
    const title = element('h3', finding.task_title);
    title.append(element('span', `${finding.confidence} confidence`, 'confidence'));
    card.append(title, element('p', finding.insight));
    finding.citations.forEach(citation => {
      const quote = element('blockquote', citation.excerpt);
      const button = element('button', `View source ${citation.source_id} ↗`, 'citation-link');
      button.type = 'button';
      button.addEventListener('click', () => {
        activateTab('sources');
        const source = $(`source-${citation.source_id}`);
        source.scrollIntoView({ block: 'center', behavior: 'smooth' });
        source.focus({ preventScroll: true });
      });
      quote.append(button);
      card.append(quote);
    });
    if (finding.evidence_gaps.length) {
      const details = element('details', undefined, 'gaps');
      const list = element('ul');
      finding.evidence_gaps.forEach(gap => list.append(element('li', gap)));
      details.append(element('summary', `${finding.evidence_gaps.length} evidence gap${finding.evidence_gaps.length === 1 ? '' : 's'} to review`), list);
      card.append(details);
    }
    $('findings').append(card);
  });
  $('sources').replaceChildren();
  if (!sources.length) $('sources').append(element('p', 'Run with imported documents or live web search to collect sources.', 'empty-tab'));
  sources.forEach(source => {
    const card = element('article', undefined, 'source-card');
    card.id = `source-${source.source_id}`;
    card.tabIndex = -1;
    card.append(element('h3', `${source.source_id} · ${source.title}`));
    if (source.url && /^https?:\/\//i.test(source.url)) {
      const link = element('a', source.url);
      link.href = source.url; link.target = '_blank'; link.rel = 'noopener noreferrer';
      card.append(link);
    }
    card.append(element('p', `${source.metadata.content_kind} · Relevance ${source.score.toFixed(2)} · ${source.task_titles.join(', ')}`, 'source-meta'));
    const details = element('details');
    details.append(element('summary', 'Inspect collected source text'), element('div', source.content, 'source-content'));
    card.append(details);
    $('sources').append(card);
  });
  $('plan').replaceChildren();
  result.tasks.forEach((task, index) => {
    const card = element('article', undefined, 'task-card');
    card.append(element('h3', `${String(index + 1).padStart(2, '0')} · ${task.title}`), element('p', task.objective), element('p', `Evidence needed: ${task.evidence_to_collect.join('; ')}`, 'helper'));
    task.search_queries.forEach(query => card.append(element('p', `Search: ${query}`, 'helper')));
    $('plan').append(card);
  });
  $('saved').textContent = result.stored_session ? `Saved locally: ${result.stored_session.storage_dir}` : 'Not saved to disk. Download the brief to keep a copy.';
  renderAgentRuns(result.agent_runs || []);
  activateTab('findings');
}
$('research-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  $('error').hidden = true;
  const demo = $('provider').value === 'demo';
  try {
    let documents;
    if (demo) {
      if (!demoDocuments) {
        const response = await fetch('/demo.json');
        if (!response.ok) throw new Error('Sample documents could not be loaded.');
        demoDocuments = await response.json();
      }
      documents = demoDocuments;
    }
    if ($('provider').value === 'local') {
      const file = $('documents').files[0];
      if (!file) throw new Error('Choose a JSON document collection first.');
      if (file.size > 1900000) throw new Error('Use a document collection smaller than 1.9 MB.');
      try { documents = JSON.parse(await file.text()); } catch { throw new Error('The document file is not valid JSON.'); }
    }
    const payload = { topic: $('topic').value.trim(), audience: $('audience').value.trim(), outcome: $('outcome').value.trim(), provider: demo ? 'local' : $('provider').value, documents, synthesis: $('synthesis').value, model: $('model').value.trim(), max_sources: Number($('max-sources').value), persist: $('persist').checked };
    if ($('team-enabled').checked) {
      if (payload.provider === 'plan') throw new Error('Choose documents or web search for an agent team.');
      payload.agent_config = getTeamConfig();
      payload.synthesis = 'extractive'; payload.model = '';
    }
    $('submit').disabled = true;
    $('empty').hidden = true;
    $('results').hidden = true;
    $('loading').hidden = false;
    $('status').textContent = 'Research in progress';
    const response = await fetch('/api/research', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Research could not be completed.');
    render(result, demo);
  } catch (error) {
    $('error').textContent = error.message;
    $('error').hidden = false;
    $('status').textContent = 'Needs attention';
    $('empty').hidden = Boolean(report);
    $('results').hidden = !report;
  } finally {
    $('loading').hidden = true;
    $('submit').disabled = false;
  }
});
$('download').addEventListener('click', () => {
  if (!report) return;
  const url = URL.createObjectURL(new Blob([report.markdown], { type: 'text/markdown;charset=utf-8' }));
  const link = element('a'); link.href = url; link.download = 'research-brief.md';
  document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
});
$('copy').addEventListener('click', async () => {
  if (!report) return;
  try { await navigator.clipboard.writeText(report.markdown); $('copy').textContent = 'Copied ✓'; }
  catch { $('copy').textContent = 'Use Download instead'; }
  setTimeout(() => { $('copy').textContent = 'Copy brief'; }, 2000);
});
fetch('/api/config').then(response => response.json()).then(config => {
  $('model').value = config.model || '';
  team.models = config.models || {};
  renderTeam();
  if (config.tavily) help.tavily = 'Live web search is configured. Queries are sent to Tavily; API keys stay on the server.';
  updateMode();
}).catch(() => { /* The form still works; request errors are shown on submission. */ });

// A shared configuration document drives both form controls and CLI exports.
let team = { models: {}, research_agents: [{id: 'researcher-01', focus: 'Evidence and limitations', model: null}], planner_model: null, synthesizer_model: null, max_concurrency: 4, max_searches: 2, on_error: 'fallback' };
function field(parent, label, value, onChange, options) {
  const wrapper = element('label', label);
  const input = element(options ? 'select' : 'input');
  if (options) options.forEach(([id, text]) => { const option = element('option', text); option.value = id; input.append(option); });
  input.value = value || '';
  input.addEventListener('change', () => onChange(input.value));
  wrapper.append(input); parent.append(wrapper);
  return input;
}
function modelOptions(empty = 'Source excerpts · No model') {
  return [['', empty], ...Object.entries(team.models).map(([name, p]) => [name, `${name} · ${p.provider}`])];
}
function fillModelSelect(id, value, empty) {
  const select = $(id); select.replaceChildren();
  modelOptions(empty).forEach(([name, label]) => { const option = element('option', label); option.value = name; select.append(option); });
  select.value = value || '';
}
function teamSummary() {
  const counts = {};
  team.research_agents.forEach(agent => { const name = agent.model || 'excerpts'; counts[name] = (counts[name] || 0) + 1; });
  $('team-summary').textContent = `${team.research_agents.length} research agents · ` + Object.entries(counts).map(([name, n]) => `${n} on ${name}`).join(' · ');
}
function renderTeam() {
  $('model-profiles').replaceChildren();
  Object.entries(team.models).forEach(([name, profile]) => {
    $('model-profiles').append(element('p', `${name} · ${profile.provider} / ${profile.model}`, 'helper'));
  });
  if (!Object.keys(team.models).length) $('model-profiles').append(element('p', 'No model profiles configured. Excerpt-only agents are available.', 'helper'));
  $('agent-assignments').replaceChildren();
  team.research_agents.forEach((agent, index) => {
    const card = element('div', undefined, 'agent-editor');
    const heading = element('div', undefined, 'editor-title'); heading.append(element('strong', agent.id));
    const remove = element('button', 'Remove', 'remove-item'); remove.type = 'button'; remove.disabled = team.research_agents.length === 1;
    remove.addEventListener('click', () => { team.research_agents.splice(index, 1); renderTeam(); }); heading.append(remove); card.append(heading);
    field(card, 'Research focus', agent.focus, value => { agent.focus = value; });
    field(card, 'Assigned model', agent.model, value => { agent.model = value || null; teamSummary(); }, modelOptions());
    $('agent-assignments').append(card);
  });
  fillModelSelect('planner-profile', team.planner_model, 'Configured focuses · No model');
  fillModelSelect('synth-profile', team.synthesizer_model, 'Keep agent findings · No model');
  $('team-concurrency').value = team.max_concurrency;
  $('team-searches').value = team.max_searches;
  $('team-errors').value = team.on_error;
  teamSummary();
}
$('team-enabled').addEventListener('change', updateMode);
$('planner-profile').addEventListener('change', () => { team.planner_model = $('planner-profile').value || null; });
$('synth-profile').addEventListener('change', () => { team.synthesizer_model = $('synth-profile').value || null; });
$('team-concurrency').addEventListener('change', () => { team.max_concurrency = Number($('team-concurrency').value); });
$('team-searches').addEventListener('change', () => { team.max_searches = Number($('team-searches').value); });
$('team-errors').addEventListener('change', () => { team.on_error = $('team-errors').value; });
$('add-agent').addEventListener('click', () => {
  let n = 1; while (team.research_agents.some(a => a.id === `researcher-${n}`)) n++;
  team.research_agents.push({id:`researcher-${n}`,focus:'',model:null});
  team.max_searches = Math.max(team.max_searches, 2 * team.research_agents.length); renderTeam();
});
$('team-offline').addEventListener('click', () => {
  team.research_agents.forEach(a => { a.model = null; }); team.planner_model = null; team.synthesizer_model = null; renderTeam();
});
function getTeamConfig() {
  const result = structuredClone(team);
  delete result.models;
  return result;
}
$('export-team').addEventListener('click', () => {
  const url = URL.createObjectURL(new Blob([JSON.stringify(getTeamConfig(), null, 2)], {type:'application/json'}));
  const link = element('a'); link.href = url; link.download = 'agent-config.json'; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url),1000);
});
$('import-team').addEventListener('change', async () => {
  try {
    const file = $('import-team').files[0]; if (!file) return;
    if (file.size > 100000) throw new Error('Agent configuration must be smaller than 100 KB.');
    const imported = JSON.parse(await file.text());
    if (!imported || !Array.isArray(imported.research_agents) || imported.research_agents.length < 1) throw new Error('Invalid agent configuration.');
    if (Object.hasOwn(imported, 'models')) throw new Error('Configure model profiles locally; import a team file containing assignments only.');
    if (!imported.research_agents.every(a => a && typeof a.id === 'string' && typeof a.focus === 'string')) throw new Error('Invalid agent entry.');
    imported.research_agents.forEach(a => { if (!Object.hasOwn(a,'model')) a.model = imported.default_model ?? null; });
    imported.planner_model = Object.hasOwn(imported,'planner_model') ? imported.planner_model : imported.default_model ?? null;
    imported.synthesizer_model = Object.hasOwn(imported,'synthesizer_model') ? imported.synthesizer_model : imported.default_model ?? null;
    const assignments = [imported.planner_model, imported.synthesizer_model, ...imported.research_agents.map(a => a.model)];
    if (assignments.some(name => name !== null && !Object.hasOwn(team.models, name))) throw new Error('An assignment references a model not configured on this server.');
    team = {...imported, models: team.models, max_concurrency:imported.max_concurrency ?? 4, max_searches:imported.max_searches ?? imported.research_agents.length * 2, on_error:imported.on_error ?? 'fallback'};
    renderTeam();
  } catch (error) { $('error').textContent = error.message; $('error').hidden = false; }
});
function renderAgentRuns(runs) {
  $('team-results').hidden = !runs.length; $('agent-runs').replaceChildren();
  runs.forEach(run => {
    const row = element('div', undefined, 'agent-run');
    row.append(element('strong', `${run.agent_id} · ${run.status}`), element('p', `${run.provider} / ${run.model} · ${run.duration_ms} ms`));
    const usage = Object.entries(run.usage).map(([name, count]) => `${name.replace('_',' ')}: ${count}`).join(' · ');
    if (usage) row.append(element('p', usage));
    run.warnings.forEach(w => row.append(element('p', w)));
    $('agent-runs').append(row);
  });
}
renderTeam();
