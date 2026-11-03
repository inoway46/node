import json
import os
from pathlib import Path
import subprocess
import sys

source = Path(sys.argv[1]).resolve()
phase = sys.argv[2]
assert phase in ('before', 'after')
output = Path(sys.argv[3]).resolve() / phase
output.mkdir(parents=True, exist_ok=True)
assets = Path(__file__).resolve().parent
binary = Path(os.environ.get('VALIDATION_BINARY', source / 'out/Release/node'))
env = {k: v for k, v in os.environ.items() if k not in ('NODE_OPTIONS', 'NODE_DEBUG', 'NODE_DEBUG_NATIVE')}
env['NODE_SOURCE_DIR'] = str(source)
checks = []

def run(name, args, native=False, expected_timeout=False):
    child_env = dict(env)
    if native:
        child_env.update(NODE_DEBUG_NATIVE='TLS,HTTP2SESSION', NODE_DEBUG='http2,tls')
    with (output / (name + '.stdout')).open('w') as out, (output / (name + '.stderr')).open('w') as err:
        try:
            result = subprocess.run([str(binary), *map(str, args)], cwd=source, env=child_env, stdout=out, stderr=err, timeout=16)
            ok = result.returncode == 0 and not expected_timeout
            detail = {'exit': result.returncode}
        except subprocess.TimeoutExpired:
            ok = expected_timeout
            detail = {'timeout': True}
    checks.append({'name': name, 'ok': ok, **detail})
    return ok

for mode in ('plain', 'fatal', 'control'):
    if not run(mode, ['--expose-gc', assets / 'repro.cjs', mode], native=mode == 'fatal'):
        continue
    try:
        rows = [json.loads(line) for line in (output / (mode + '.stdout')).read_text().splitlines()]
        snap = {r['event']: r for r in rows}
        baseline = snap['baseline']['fds']['count']
        observed = snap['observed-3s']
        sessions = observed['sessions']
        assert len(sessions) == 3
        assert sum(r['event'] == 'connect' for r in rows) == 3
        if mode != 'control':
            assert sum(r['event'] == 'server-tls-error' and r['code'] == 'ERR_SSL_PEER_DID_NOT_RETURN_A_CERTIFICATE' for r in rows) == 3
        leaked = phase == 'before' and mode != 'control'
        for s in sessions:
            errors = [e for e in s['events'] if e.startswith('session-error:')]
            closes = s['events'].count('session-close')
            if leaked:
                assert s['alive'] and s['destroyed'] and not s['closed'] and not s['socketDestroyed']
                assert not errors and closes == 0
            else:
                assert closes == 1 and s['socketDestroyedAtClose']
                assert errors == ([] if mode == 'control' else ['session-error:ERR_SSL_TLSV13_ALERT_CERTIFICATE_REQUIRED'])
                assert not s['alive']
        assert observed['fds']['count'] == baseline + (3 if leaked else 0)
        clean = snap['cleanup-complete']
        assert clean['fds']['count'] == baseline - 1
        assert not clean['handles']
        assert all(not s['alive'] for s in clean['sessions'])
        checks.append({'name': mode + '-observations', 'ok': True})
    except (AssertionError, KeyError, ValueError) as error:
        checks.append({'name': mode + '-observations', 'ok': False, 'error': repr(error)})

for name in ('goaway', 'nonfatal-goaway'):
    run(name, [assets / (name + '.cjs')])

for name in ('goaway-opaquedata', 'goaway-delayed-request',
             'propagate-session-destroy-code', 'client-destroy',
             'client-socket-destroy', 'server-socket-destroy', 'destroy-after-write'):
    run(name, ['--require', assets / 'loopback.cjs', source / ('test/parallel/test-http2-' + name + '.js')])

# Copy the same regression into the baseline tree too; no source patch is applied.
regression = source / 'test/parallel/test-http2-tls-fatal-alert.js'
if not regression.exists():
    regression.write_bytes((assets / regression.name).read_bytes())
for i in range(20 if phase == 'after' else 1):
    run('regression-' + str(i), [regression], expected_timeout=phase == 'before')

(output / 'summary.json').write_text(json.dumps(checks, indent=2) + '\n')
for check in checks:
    print(('PASS' if check['ok'] else 'FAIL'), check['name'])
sys.exit(0 if all(c['ok'] for c in checks) else 1)
