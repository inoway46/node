import json
import struct
import sys
from pathlib import Path

path, page = sys.argv[1], int(sys.argv[2])
data = Path(path).read_bytes()
assert data[:6] == b'\x7fELF\x02\x01'
assert struct.unpack_from('<H', data, 18)[0] == 183
phoff = struct.unpack_from('<Q', data, 32)[0]
stride, count = struct.unpack_from('<HH', data, 54)
loads = []
errors = []
for i in range(count):
    kind, flags, offset, va, pa, filesz, memsz, alignment = struct.unpack_from('<IIQQQQQQ', data, phoff+i*stride)
    if kind == 1 and memsz:
        loads.append(dict(index=i, offset=offset, va=va, filesz=filesz, memsz=memsz, alignment=alignment))
        if va % page != offset % page:
            errors.append(f'LOAD {i}: address/offset mismatch')
for i, a in enumerate(loads):
    for b in loads[i+1:]:
        if max(a['va']//page, b['va']//page) < min((a['va']+a['memsz']+page-1)//page, (b['va']+b['memsz']+page-1)//page):
            errors.append(f"LOAD {a['index']}/{b['index']}: overlapping virtual pages")
print(json.dumps(dict(path=path, page=page, loads=loads, errors=errors), indent=2))
sys.exit(0 if loads and not errors else 1)
