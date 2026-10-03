import re


def inspect_heap(output):
    """Read two consecutive DebugPrint passes over the eight retained objects."""
    blocks = re.split(r'^DebugPrint: ', output, flags=re.MULTILINE)[1:]
    objects = []
    for block in blocks:
        header = re.match(r'(0x[0-9a-f]+): \[JS_OBJECT_TYPE\]', block)
        if not header:
            raise ValueError('Missing JSObject address in DebugPrint')
        fields = {}
        for name in ('area', 'maxOff'):
            field = re.search(
                rf'#{name}: (0x[0-9a-f]+) <HeapNumber ([^>]+)>', block)
            if not field:
                raise ValueError(f'Missing raw HeapNumber for {name}')
            fields[name] = {
                'address': hex(int(field[1], 16)), 'value': field[2],
            }
        objects.append({'address': hex(int(header[1], 16)), 'fields': fields})
    if len(objects) != 16:
        raise ValueError(f'Expected 16 object dumps, got {len(objects)}')
    if objects[:8] != objects[8:]:
        raise ValueError('Object addresses or fields changed between dump passes')
    if len({obj['address'] for obj in objects[:8]}) != 8:
        raise ValueError('The eight returned objects are not distinct')
    shared = []
    for name in ('area', 'maxOff'):
        groups = {}
        for index, obj in enumerate(objects[:8], 1):
            address = obj['fields'][name]['address']
            groups.setdefault(address, []).append(index)
        shared.extend({'field': name, 'address': address, 'calls': calls}
                      for address, calls in groups.items() if len(calls) > 1)
    changed_calls = [int(index) for index in re.findall(
        r'^call (\d+): returned .*; the same object now reads ',
        output, flags=re.MULTILINE)]
    shared_changed_calls = sorted({
        index for group in shared for index in group['calls']
        if index in changed_calls
    })
    return {'objects': objects[:8], 'stable_two_passes': True,
            'shared_heap_numbers': shared, 'changed_calls': changed_calls,
            'shared_changed_calls': shared_changed_calls}
