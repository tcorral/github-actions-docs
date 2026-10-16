'use strict';
const path = require('node:path').posix;
const expectedWorkflows = ['_lint', 'ci', 'deploy', 'release', 'nightly'];
const expectedActions = ['cache-deps', 'unused-helper', 'setup-project', 'notify-slack'];
const expected = [
  'README.md', ...expectedWorkflows.map(n => `workflows/${n}.md`),
  ...expectedActions.map(n => `actions/${n}.md`),
];
function check(output, context = {}) {
  const problems = [];
  let data;
  try { data = JSON.parse(output); } catch { return { pass: false, score: 0, reason: 'Provider did not return JSON documentation snapshot' }; }
  const docs = data.docs || {};
  const checkOne = (condition, description) => { if (!condition) problems.push(description); };
  for (const name of expected) checkOne(typeof docs[name] === 'string', `Missing ${name}`);
  checkOne(Object.keys(docs).length === expected.length, 'Unexpected or stale documentation files');
  for (const [file, contents] of Object.entries(docs)) {
    if (file === 'README.md') checkOne(/##\s+Workflows/i.test(contents) && /##\s+Actions/i.test(contents), 'Index missing workflow/action tables');
    else checkOne(/##\s+Overview/i.test(contents), `${file}: missing Overview`);
    if (file !== 'README.md') {
      for (const header of ['Dependencies', 'Dependency graph', 'Configuration', 'Examples', 'Notes and caveats'])
        checkOne(new RegExp(`#{2,3}\\s+${header}`, 'i').test(contents), `${file}: missing ${header}`);
      // Only the fixture's truly standalone action may omit its graph.
      // It has neither callers nor local/external dependencies.
      const graph = /```mermaid\s*\n\s*flowchart\b/i.test(contents);
      const section = contents.match(/^#{2,3}\s+Dependency graph\s*$([\s\S]*?)(?=^#{2,3}\s+|$(?![\s\S]))/im);
      // Only allow the exception for the fixture's known standalone action.
      // Both "no dependencies or callers" and "no dependencies and no callers"
      // mean there are no outgoing dependencies and no incoming callers.
      const standaloneExplanation = /Not applicable:\s*[^\n]*(?:\bno\s+dependencies\s+(?:or|and)\s+(?:no\s+)?callers\b|\bno\s+callers\s+(?:or|and)\s+(?:no\s+)?dependencies\b|\bno\s+dependencies\s+(?:and|,)\s+(?:is\s+)?not\s+(?:used|referenced)\b|\bnot\s+(?:used|referenced)\s+(?:and|,)\s+(?:has\s+)?no\s+dependencies\b)/i;
      const exception = file === 'actions/unused-helper.md' &&
        Boolean(section && standaloneExplanation.test(section[1]));
      checkOne(graph || exception, `${file}: missing Mermaid dependency graph or valid standalone-action exception`);
      checkOne(/```mermaid\s*\n\s*sequenceDiagram/i.test(contents) || /Not applicable:\s*\S/i.test(contents), `${file}: missing sequence diagram or reason`);
    }
    for (const match of contents.matchAll(/\]\(([^)#]+)(?:#[^)]*)?\)/g)) {
      const target = match[1];
      if (/^(?:https?:|mailto:|\/|#)/.test(target)) continue;
      const dest = path.normalize(path.join(path.dirname(file), decodeURIComponent(target)));
      // Only check generated-doc markdown links; references to repository YAML are allowed.
      if (dest.endsWith('.md')) checkOne(Boolean(docs[dest]), `${file}: broken Markdown link ${target}`);
    }
  }
  const index = docs['README.md'] || '';
  for (const name of expected.slice(1)) checkOne(index.includes(name), `Index missing ${name}`);
  const ci = docs['workflows/ci.md'] || '';
  checkOne(/pull_request/.test(ci) && /push/.test(ci) && /main/.test(ci), 'CI triggers/branch not described');
  checkOne(/_lint\.md/.test(ci) && /setup-project\.md/.test(ci) && /notify-slack\.md/.test(ci), 'CI local dependencies not linked');
  checkOne(/3\.12/.test(ci) && /ubuntu-latest/.test(ci) && /windows-latest/.test(ci) && /18/.test(ci) && /20/.test(ci), 'CI matrix/inputs absent');
  checkOne(/CODECOV_TOKEN/.test(ci) && /SLACK_WEBHOOK/.test(ci), 'CI secret names omitted');
  const deploy = docs['workflows/deploy.md'] || '';
  checkOne(/workflow_run/.test(deploy) && /Release/.test(deploy), 'Deploy workflow_run chain absent');
  checkOne(/DEPLOY_KEY/.test(deploy) && /DEPLOY_TARGET/.test(deploy), 'Deployment secret/var absent');
  const nightly = docs['workflows/nightly.md'] || '';
  checkOne(/0 2 \* \* \*/.test(nightly) || /02:00/.test(nightly), 'Nightly cron absent');
  checkOne(/missing-action/.test(nightly), 'Broken local action reference not flagged');
  const action = docs['actions/setup-project.md'] || '';
  checkOne(/node-version/.test(action) && /install-command/.test(action) && /cache-deps\.md/.test(action), 'Composite action interface/dependency absent');
  checkOne(/unused-helper/i.test(index), 'Unused local action not covered in index');
  checkOne(/sonarcloud-github-action@master/i.test(docs['workflows/_lint.md'] || ''), 'Floating branch reference omitted');
  if (data.scenario === 'regenerate') checkOne(/KEEP THIS HUMAN RUNBOOK UNCHANGED/.test(ci), 'Manual block not preserved');
  if (data.scenario === 'custom-dir') checkOne(data.docDir === 'docs/ci-reference', 'Incorrect custom doc directory');
  return { pass: !problems.length, score: problems.length ? Math.max(0, 1 - problems.length / 40) : 1, reason: problems.length ? problems.join('\n') : 'All fixture-grounded documentation checks passed' };
}
module.exports = check;
