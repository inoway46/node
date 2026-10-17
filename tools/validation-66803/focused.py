"""Exercise shared producers without building all V8 or Node libraries."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1]
PR_SHA = '55f21fa99021d3f4aed7e6472210e220a615bf5c'
GENERATOR, CPU = sys.argv[1:3]
GRAPH_ONLY = 'graph-only' in sys.argv[3:]
RESULTS = SOURCE / 'focused-results'
RESULTS.mkdir(exist_ok=True)
TREE = Path(os.environ.get('TASK_GRAPH_TREE', str(Path(os.environ['RUNNER_TEMP']) / ('focused-' + GENERATOR + '-' + CPU)))).resolve()
ENV = dict(os.environ, CC=os.environ.get('TASK_CC', 'clang-19'), CXX=os.environ.get('TASK_CXX', 'clang++-19'), PYTHONHASHSEED='0')
ENV.pop('GYP_CROSSCOMPILE', None)
PRODUCERS = ['run_torque', 'generate_bytecode_builtins_list', 'v8_inspector_headers', 'run_gen-regexp-special-case', 'postmortem-metadata']
STATUS = {'source': PR_SHA, 'generator': GENERATOR, 'cpu': CPU, 'graph_only': GRAPH_ONLY, 'commands': []}


def run(command, label, cwd=TREE):
    print('+', ' '.join(command), flush=True)
    with (RESULTS / (label + '.log')).open('w') as output:
        try:
            result = subprocess.run(command, cwd=cwd, env=ENV, stdout=output, stderr=subprocess.STDOUT, timeout=1500, check=False)
            code = result.returncode
        except subprocess.TimeoutExpired:
            code = 124
    STATUS['commands'].append({'label': label, 'returncode': code, 'command': command})
    (RESULTS / 'status.json').write_text(json.dumps(STATUS, indent=2))
    if code:
        print((RESULTS / (label + '.log')).read_text()[-15000:], flush=True)
        sys.exit(code)


def validate_graph():
    graph = json.loads((RESULTS / 'graph.json').read_text())
    nodes = {target['target_name'] + '#' + target['toolset']: key for key, target in graph.items()}
    for name in PRODUCERS:
        owners = [target for target in graph.values() if target['target_name'] == name]
        assert len(owners) == 1 and owners[0]['toolset'] == 'target', name
    for producer, executable in [('run_torque', 'torque'), ('generate_bytecode_builtins_list', 'bytecode_builtins_list_generator'),
                                 ('run_gen-regexp-special-case', 'gen-regexp-special-case')]:
        toolset = 'host' if CPU == 'riscv64' else 'target'
        assert nodes[executable + '#' + toolset] in graph[nodes[producer + '#target']]['dependencies']
    for toolset in (['host', 'target'] if CPU == 'riscv64' else ['target']):
        dependencies = graph[nodes['v8_base_without_compiler#' + toolset]]['dependencies']
        for name in PRODUCERS[:3] + ['run_gen-regexp-special-case']:
            assert nodes[name + '#target'] in dependencies, (toolset, name)
    visiting, visited = set(), set()

    def visit(key):
        assert key not in visiting, key
        if key in visited:
            return
        visiting.add(key)
        for dep in graph[key].get('dependencies', []):
            visit(dep)
        visiting.remove(key)
        visited.add(key)

    for key in graph:
        visit(key)
    STATUS['producer_ownership_and_dependencies'] = 'passed'


def compile_consumer(toolset):
    if GENERATOR == 'ninja':
        prefix = 'obj.host' if toolset == 'host' else 'obj'
        target = prefix + '/tools/v8_gypfiles/gen/torque-generated/v8_initializers.enum-verifiers.o'
        command = ['ninja', '-C', str(OUT / 'Release'), '-t', 'commands', target]
    else:
        target = str(OUT / ('Release/obj.' + toolset + '/v8_initializers/gen/torque-generated/enum-verifiers.o'))
        command = ['make', '-C', str(OUT), '-n', 'BUILDTYPE=Release', 'V=1', target]
    run(command, toolset + '-consumer-commands')
    lines = (RESULTS / (toolset + '-consumer-commands.log')).read_text().splitlines()
    candidates = [line.strip() for line in lines if 'enum-verifiers.cc' in line and line.strip().startswith('clang++') and '-c' in shlex.split(line)]
    assert candidates, target
    args = shlex.split(candidates[-1])
    args[args.index('-o') + 1] = str(RESULTS / (toolset + '-consumer.o'))
    if '-MF' in args:
        args[args.index('-MF') + 1] = str(RESULTS / (toolset + '-consumer.d'))
    if GRAPH_ONLY:
        STATUS[toolset + '_consumer_command_selected'] = True
        return
    run(args, toolset + '-consumer-compile', cwd=OUT / 'Release' if GENERATOR == 'ninja' else OUT)
    run(['readelf', '-h', str(RESULTS / (toolset + '-consumer.o'))], toolset + '-consumer-elf')
    expected = 'RISC-V' if CPU == 'riscv64' and toolset == 'target' else 'Advanced Micro Devices X86-64'
    assert expected in (RESULTS / (toolset + '-consumer-elf.log')).read_text()


if GRAPH_ONLY and 'TASK_GRAPH_TREE' in os.environ:
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=TREE, text=True).strip() == PR_SHA
else:
    run(['git', 'worktree', 'add', '--detach', str(TREE), PR_SHA], 'checkout', cwd=SOURCE)
flags = ['--v8-disable-temporal-support', '--dest-os=linux', '--dest-cpu=' + CPU,
         '--cross-compiling' if CPU == 'riscv64' else '--no-cross-compiling']
if CPU == 'riscv64':
    ENV['GYP_CROSSCOMPILE'] = '1'
    ENV.update(CC_host=ENV['CC'], CXX_host=ENV['CXX'], AR_host='ar')
    if not GRAPH_ONLY:
        flags_cc = ' --target=riscv64-linux-gnu --gcc-toolchain=/usr -march=rv64gc -mabi=lp64d'
        ENV.update(CC='clang-19' + flags_cc, CXX='clang++-19' + flags_cc, AR='riscv64-linux-gnu-ar')
if GENERATOR == 'ninja':
    flags.append('--ninja')
run(['./configure', *flags], 'configure')
ENV['TASK_GRAPH_JSON'] = str(RESULTS / 'graph.json')
run([sys.executable, str(HERE / 'capture.py'), '--no-parallel', '-Dconfiguring_node=1', '-Dbuild_type=Release',
     '-Dpython=' + sys.executable, '-f', GENERATOR + '-linux'], 'capture')
validate_graph()
OUT = TREE / 'out'
PREFIX = (['ninja', '-C', str(OUT / 'Release'), '-j4', '-v'] if GENERATOR == 'ninja' else
          ['make', '-C', str(OUT), '-j4', 'BUILDTYPE=Release', 'V=1'])
run([*PREFIX, '-n', 'node'], 'node-dry-run')
if not GRAPH_ONLY:
    run([*PREFIX, *PRODUCERS], 'generators-build')
    generated = OUT / ('Release/gen' if GENERATOR == 'ninja' else 'Release/obj/gen')
    paths = [p for p in generated.rglob('*') if p.is_file() and '.d' != p.suffix]
    before = {str(p): (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths}
    run([*PREFIX, *PRODUCERS], 'generators-incremental')
    assert before == {str(p): (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths}
    STATUS['generated_files_unchanged_on_rebuild'] = True
    for toolset in (['host', 'target'] if CPU == 'riscv64' else ['target']):
        compile_consumer(toolset)
    # A small direct generator/compiler probe; graph ownership was checked separately.
    zone = RESULTS / 'zoneinfo.cc'
    run([sys.executable, str(TREE / 'deps/v8/tools/include-file-as-bytes.py'),
         str(TREE / 'deps/crates/vendor/zoneinfo64-v0_3/src/data/zoneinfo64.res'), str(zone), 'zoneinfo64_static_data'], 'zoneinfo-generate')
    for toolset in (['host', 'target'] if CPU == 'riscv64' else ['target']):
        compiler = ENV.get('CXX_host', ENV['CXX']) if toolset == 'host' else ENV['CXX']
        run([*shlex.split(compiler), '-std=c++20', '-c', str(zone), '-o', str(RESULTS / (toolset + '-zoneinfo.o'))], toolset + '-zoneinfo-compile')
    STATUS['timezone_direct_generator_and_compile'] = 'passed'
if GRAPH_ONLY:
    for toolset in (['host', 'target'] if CPU == 'riscv64' else ['target']):
        compile_consumer(toolset)
STATUS['success'] = True
(RESULTS / 'status.json').write_text(json.dumps(STATUS, indent=2))
