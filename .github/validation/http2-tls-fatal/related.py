from pathlib import Path
import subprocess
import sys

source = Path(sys.argv[1]).resolve()
output = Path(sys.argv[2]).resolve()
output.mkdir(parents=True, exist_ok=True)
cases = sorted(str(p.relative_to(source / 'test')).removesuffix('.js')
               for suite in ('parallel', 'sequential')
               for p in (source / 'test' / suite).glob('test-*.js')
               if p.name.startswith(('test-net-', 'test-tls-', 'test-https-', 'test-http2-')))
(output / 'related-cases.txt').write_text('\n'.join(cases) + '\n')
with (output / 'related.tap').open('w') as log:
    result = subprocess.run([sys.executable, 'tools/test.py', '-j', '2', '-p', 'tap', *cases],
                            cwd=source, stdout=log, stderr=subprocess.STDOUT)
sys.exit(result.returncode)
