import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import time


ROOT = Path.cwd()
OUTPUT = ROOT / 'results'
OUTPUT.mkdir(exist_ok=True)
NODE = str(Path(os.environ['NODE_BINARY']).resolve())
ENV = os.environ.copy()
ENV.pop('NODE_OPTIONS', None)
SOURCE = ROOT / '.github/diagnostics/issue-66457/reproducer.txt'
CODE = SOURCE.read_bytes()
EXPECTED_SHA256 = '94ce50a5eb81b4f121eb67937f5a81da19f551c36f9b7561b2fa7d89f7cbfd84'
assert hashlib.sha256(CODE).hexdigest() == EXPECTED_SHA256
REPRODUCER = OUTPUT / 'maglev-osr-alias.mjs'
REPRODUCER.write_bytes(CODE)

metadata = json.loads(subprocess.check_output([
    NODE, '-p', 'JSON.stringify({version:process.version,v8:process.versions.v8,'
    'arch:process.arch,platform:process.platform,cpus:require("os").cpus().length})',
], env=ENV, text=True))
assert metadata['arch'] == os.environ.get('EXPECT_ARCH', 'arm64'), metadata
assert metadata['version'] == 'v' + os.environ['NODE_VERSION'], metadata
metadata.update(os=platform.platform(), parallelism=8,
                reproducer_sha256=EXPECTED_SHA256,
                run_id=os.environ.get('GITHUB_RUN_ID'),
                commit=os.environ.get('GITHUB_SHA'))
if platform.system() == 'Darwin':
    metadata['sysctl'] = subprocess.check_output([
        'sysctl', 'hw.logicalcpu', 'hw.physicalcpu', 'hw.memsize',
        'machdep.cpu.brand_string'], text=True)
(OUTPUT / 'environment.json').write_text(json.dumps(metadata, indent=2) + '\n')

count = int(os.environ.get('TRACE_RUNS', '3000'))
directory = OUTPUT / 'trace'
directory.mkdir(exist_ok=True)
command = [NODE, '--trace-opt', '--trace-deopt', str(REPRODUCER)]
(directory / 'command.json').write_text(json.dumps(command) + '\n')


def verdict(returncode, output):
    lines = output.splitlines()
    bug = 'BUG: results of earlier calls changed after later calls' in lines
    ok = returncode == 0 and 'ok' in lines and not bug
    return bug, ok, not ok and not (returncode == 1 and bug)


def run(index):
    started = time.monotonic()
    try:
        result = subprocess.run(command, env=ENV, capture_output=True, timeout=120)
        stdout, stderr, returncode = (
            result.stdout, result.stderr, result.returncode)
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout or b''
        stderr = error.stderr or b''
        returncode = 'timeout'
    (directory / f'{index:04d}.stdout').write_bytes(stdout)
    (directory / f'{index:04d}.stderr').write_bytes(stderr)
    bug, ok, error = verdict(returncode, stdout.decode(errors='replace'))
    return {'run': index, 'returncode': returncode, 'bug': bug, 'ok': ok,
            'error': error, 'seconds': round(time.monotonic() - started, 3)}


rows = []
with (directory / 'runs.jsonl').open('w') as record:
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for row in pool.map(run, range(1, count + 1)):
            rows.append(row)
            record.write(json.dumps(row) + '\n')
            record.flush()
            if len(rows) % 100 == 0:
                print(len(rows), 'bugs', sum(r['bug'] for r in rows),
                      'errors', sum(r['error'] for r in rows), flush=True)

with (OUTPUT / 'faceStats-bytecode.log').open('wb') as log:
    bytecode_result = subprocess.run([
        NODE, '--print-bytecode', '--print-bytecode-filter=faceStats',
        str(REPRODUCER)], env=ENV, stdout=log, stderr=subprocess.STDOUT,
        timeout=120)
bytecode = (OUTPUT / 'faceStats-bytecode.log').read_text(errors='replace')
bytecode_lines = bytecode.splitlines()
literal_index = next((i for i, line in enumerate(bytecode_lines)
                      if 'CreateObjectLiteral' in line), None)
literal = (re.search(r'@ (\d+) :', bytecode_lines[literal_index])
           if literal_index is not None else None)
store = next((re.search(r'@ (\d+) :', line)
              for line in bytecode_lines[literal_index + 1:]
              if 'DefineNamedOwnProperty' in line), None) if literal else None
literal_offset = int(literal.group(1)) if literal else None
store_offset = int(store.group(1)) if store else None

analyses = []
for row in rows:
    path = directory / f"{row['run']:04d}.stdout"
    lines = path.read_text(errors='replace').splitlines()
    groups = {}
    for line in lines:
        if ('bailout' not in line or 'faceStats' not in line or
                'Insufficient type feedback for generic named access' not in line):
            continue
        match = re.search(
            r'(0x[0-9a-f]+) <Code ([^>]+)>, opt id (\d+), bytecode offset (\d+)',
            line)
        if match:
            address, code, opt_id, offset = match.groups()
            key = (address, code, opt_id, offset)
            groups.setdefault(key, []).append(line)
    named_deopts = [
        {'code_address': address, 'code': code, 'opt_id': opt_id,
         'offset': int(offset),
         'count': len(entries), 'lines': entries}
        for (address, code, opt_id, offset), entries in groups.items()
    ]
    changed = [line for line in lines
               if line.startswith('call ') and 'the same object now reads' in line]
    analyses.append({
        'run': row['run'], 'bug': row['bug'], 'changed_objects': len(changed),
        'changed_lines': changed, 'named_deopts': named_deopts,
        'maglev_osr_compiled': any(
            'completed compiling' in line and 'faceStats' in line and
            '(target MAGLEV) OSR' in line for line in lines),
    })

(OUTPUT / 'trace-analysis.json').write_text(json.dumps(analyses, indent=2) + '\n')
summary = {
    'environment': metadata,
    'runs': count,
    'bugs': sum(row['bug'] for row in rows),
    'errors': sum(row['error'] for row in rows),
    'bug_runs': [row['run'] for row in rows if row['bug']],
    'error_runs': [row['run'] for row in rows if row['error']],
    'bytecode_returncode': bytecode_result.returncode,
    'literal_offset': literal_offset,
    'first_area_store_offset': store_offset,
    'maglev_osr_runs': sum(row['maglev_osr_compiled'] for row in analyses),
    'maglev_store_deopt_runs': sum(any(
        entry['code'] == 'MAGLEV' and entry['offset'] == store_offset
        for entry in row['named_deopts']) for row in analyses),
    'bug_and_maglev_store_deopt_runs': sum(
        row['bug'] and any(entry['code'] == 'MAGLEV' and
                           entry['offset'] == store_offset
                           for entry in row['named_deopts'])
        for row in analyses),
    'repeated_maglev_store_deopt_runs': [row['run'] for row in analyses
                                         if any(entry['code'] == 'MAGLEV' and
                                                entry['offset'] == store_offset and
                                                entry['count'] >= 2
                                                for entry in row['named_deopts'])],
}
(OUTPUT / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
print(json.dumps(summary, indent=2), flush=True)
if 'GITHUB_STEP_SUMMARY' in os.environ:
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as report:
        report.write(f"Node {metadata['version']} / V8 {metadata['v8']} / "
                     f"{metadata['os']} / {len(metadata['cpus'])} logical CPUs\n\n")
        report.write(f"Trace: {count} runs, {summary['bugs']} BUG, "
                     f"{summary['errors']} execution errors. "
                     f"Maglev deopt at area store: "
                     f"{summary['maglev_store_deopt_runs']} runs, "
                     f"with BUG: {summary['bug_and_maglev_store_deopt_runs']}.\n")
if summary['errors'] or bytecode_result.returncode or store_offset is None:
    raise SystemExit('Trace verification was incomplete')
