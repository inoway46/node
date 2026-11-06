#!/usr/bin/env python3
# Fork-only experiment (inoway46/node); not for upstream.
"""Compare two V8 derivation outputs file by file, and static archives member
by member (member data only, so archive headers/timestamps are ignored).

Usage: manifest.py compare <store-path-a> <store-path-b>
lib/pkgconfig is skipped because v8.pc embeds $out.
"""
import hashlib
import os
import sys


def ar_members(data):
  if not data.startswith(b'!<arch>\n'):
    return None
  pos, longnames, members = 8, b'', []
  while pos + 60 <= len(data):
    hdr = data[pos:pos + 60]
    name = hdr[:16].decode('latin-1').rstrip()
    size = int(hdr[48:58].decode('latin-1').strip())
    pos += 60
    body = data[pos:pos + size]
    pos += size + (size & 1)
    if name.startswith('#1/'):  # BSD long name
      n = int(name[3:])
      name, body = body[:n].rstrip(b'\0').decode('latin-1'), body[n:]
    elif name in ('/', '/SYM64/'):  # GNU symbol table
      continue
    elif name == '//':  # GNU long name table
      longnames = body
      continue
    elif name.startswith('/') and name[1:].isdigit():
      off = int(name[1:])
      name = longnames[off:longnames.index(b'/\n', off)].decode('latin-1')
    else:
      name = name.rstrip('/')
    if name.startswith('__.SYMDEF'):
      continue  # symbol table: depends on member sizes only
    members.append((name, hashlib.sha256(body).hexdigest()))
  return members


def manifest(root):
  files = {}
  for dirpath, _, names in os.walk(root):
    for n in names:
      path = os.path.join(dirpath, n)
      rel = os.path.relpath(path, root)
      if rel.startswith('lib/pkgconfig/'):
        continue
      with open(path, 'rb') as f:
        data = f.read()
      files[rel] = (hashlib.sha256(data).hexdigest(), ar_members(data))
  return files


def compare(a, b):
  ma, mb = manifest(a), manifest(b)
  only = sorted(set(ma) ^ set(mb))
  same_files = diff_files = 0
  members_total = members_diff = 0
  details = []
  for rel in sorted(set(ma) & set(mb)):
    (ha, ama), (hb, amb) = ma[rel], mb[rel]
    if ha == hb:
      same_files += 1
      if ama:
        members_total += len(ama)
      continue
    diff_files += 1
    if ama is not None and amb is not None:
      members_total += max(len(ama), len(amb))
      if [n for n, _ in ama] != [n for n, _ in amb]:
        members_diff += max(len(ama), len(amb))
        details.append(f'{rel}: member lists differ ({len(ama)} vs {len(amb)})')
      else:
        bad = [n for (n, x), (_, y) in zip(ama, amb) if x != y]
        members_diff += len(bad)
        details.append(f'{rel}: {len(bad)}/{len(ama)} members differ'
                       + (f' e.g. {", ".join(bad[:5])}' if bad else ' (headers only)'))
    else:
      details.append(f'{rel}: differs')
  identical = not only and members_diff == 0 and all(
      'headers only' in d for d in details)
  print(f'COMPARE files_same={same_files} files_diff={diff_files} '
        f'files_only_in_one={len(only)} archive_members={members_total} '
        f'members_diff={members_diff} identical_content={str(identical).lower()}')
  for d in details[:40]:
    print('COMPARE-DETAIL ' + d)
  for o in only[:20]:
    print('COMPARE-ONLY ' + o)
  return identical


if __name__ == '__main__':
  if len(sys.argv) != 4 or sys.argv[1] != 'compare':
    sys.exit(__doc__)
  compare(sys.argv[2], sys.argv[3])
