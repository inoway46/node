# Fork-only experiment; not for upstream.
import json, os, pathlib, re, statistics, subprocess, sys, time

phase = sys.argv[1]
out = pathlib.Path(os.environ.get('BENCH_OUT', '/tmp/hashfiles-results'))
out.mkdir(parents=True, exist_ok=True)
patterns = ['eslint.config.mjs', '*/eslint.config_partial.mjs', 'tools/eslint/*', 'tools/eslint-rules/**', 'doc/api/errors.md', 'doc/api/deprecations.md']
rows = []
for trial in range(int(os.environ.get('REPEATS', '10'))):
    order = ['before', 'after'] if trial % 2 == 0 else ['after', 'before']
    for variant in order:
        env = os.environ.copy()
        env['patterns'] = '\n'.join(patterns + (['!**/node_modules/**'] if variant == 'after' else []))
        start = time.perf_counter()
        result = subprocess.run(['node', os.environ['HASH_SCRIPT']], env=env, capture_output=True, text=True, timeout=130)
        elapsed = time.perf_counter() - start
        assert result.returncode == 0, result.stderr
        count = int(re.search(r'Found (\d+) files to hash', result.stdout)[1])
        digest = re.search(r'__OUTPUT__(.*?)__OUTPUT__', result.stderr)[1]
        files = [line for line in result.stdout.splitlines() if line.startswith(os.getcwd() + '/') and pathlib.Path(line).is_file()]
        (out / f'{phase}-{variant}-files.json').write_text(json.dumps(files, indent=2))
        rows.append(dict(phase=phase, trial=trial, variant=variant, seconds=elapsed, count=count, digest=digest))
        print('RESULT', json.dumps(rows[-1]), flush=True)
(out / f'{phase}.json').write_text(json.dumps(rows, indent=2))
if phase == 'pre':
    assert len({r['digest'] for r in rows}) == 1
else:
    pre = json.loads((out / 'pre.json').read_text())[0]
    assert all(r['digest'] == pre['digest'] and r['count'] == pre['count'] for r in rows if r['variant'] == 'after')
    assert all(r['count'] > pre['count'] for r in rows if r['variant'] == 'before')
    before = set(json.loads((out / f'{phase}-before-files.json').read_text()))
    after = set(json.loads((out / f'{phase}-after-files.json').read_text()))
    assert after < before and all('/node_modules/' in f for f in before - after)
summary = ['| Phase | Variant | N | Median seconds | Max seconds | Files |', '|---|---|---:|---:|---:|---:|']
for variant in ['before', 'after']:
    values = [r['seconds'] for r in rows if r['variant'] == variant]
    summary.append(f'| {phase} | {variant} | {len(values)} | {statistics.median(values):.3f} | {max(values):.3f} | {next(r["count"] for r in rows if r["variant"] == variant)} |')
if os.environ.get('GITHUB_STEP_SUMMARY'):
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
        f.write('\n'.join(summary) + '\n\n')
