'use strict';
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const cp = require('node:child_process');
const crypto = require('node:crypto');

// Invoke the actual Claude Code skill against an isolated copy of the fixture.
// Requires `claude` on PATH, authenticated, and permission to run locally.
class SkillProvider {
  id() { return 'github-actions-docs-skill'; }
  async callApi(prompt, context = {}) {
    const root = path.resolve(__dirname, '..');
    const source = path.join(__dirname, 'fixtures', 'example');
    const work = fs.mkdtempSync(path.join(os.tmpdir(), 'github-actions-docs-eval-'));
    const scenario = context.vars?.scenario || 'full';
    try {
      fs.cpSync(source, work, { recursive: true });
      const skillDir = path.join(work, '.claude', 'skills', 'github-actions-docs');
      fs.mkdirSync(path.dirname(skillDir), { recursive: true });
      // Symlink skill so execution uses the version under evaluation.
      fs.symlinkSync(root, skillDir, 'dir');
      if (scenario === 'regenerate') {
        const doc = path.join(work, 'docs/github-automation/workflows/ci.md');
        fs.mkdirSync(path.dirname(doc), { recursive: true });
        fs.writeFileSync(doc, '# Previous CI docs\n\n<!-- manual:start -->\nKEEP THIS HUMAN RUNBOOK UNCHANGED\n<!-- manual:end -->\n');
      }
      const cli = cp.spawnSync('claude', [
        '--print', '--output-format', 'text', '--dangerously-skip-permissions',
        '--model', 'claude-haiku-5-5',
        '--add-dir', root
      ], { cwd: work, input: prompt, encoding: 'utf8', timeout: Number(process.env.SKILL_EVAL_TIMEOUT_MS || 600000),
        maxBuffer: 16 * 1024 * 1024, env: { ...process.env, CI: 'true' } });
      if (cli.error || cli.status !== 0) {
        return { error: `Claude CLI failed (${cli.status ?? cli.error?.code}): ${(cli.stderr || cli.error?.message || '').slice(-2500)}` };
      }
      const docDir = scenario === 'custom-dir' ? 'docs/ci-reference' : 'docs/github-automation';
      const docs = {};
      const destination = path.join(work, docDir);
      if (fs.existsSync(destination)) {
        function collect(dir) {
          for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
            const full = path.join(dir, entry.name);
            if (entry.isDirectory()) collect(full);
            else if (entry.isFile() && entry.name.endsWith('.md')) {
              docs[path.relative(destination, full).split(path.sep).join('/')] = fs.readFileSync(full, 'utf8');
            }
          }
        }
        collect(destination);
      }
      // Limit file contents to known fixture docs; no secrets or local host paths exposed.
      return { output: JSON.stringify({ scenario, docDir, docs, response: cli.stdout.slice(-1500) }) };
    } finally {
      if (process.env.SKILL_EVAL_KEEP_WORKDIR === '1') {
        process.stderr.write(`Evaluation workdir: ${work}\n`);
      } else fs.rmSync(work, { recursive: true, force: true });
    }
  }
}
module.exports = SkillProvider;
