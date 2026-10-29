import struct
from collections import namedtuple

Bitmap = namedtuple('Bitmap', 'width height pixels')
PCS, PDS, ODS = 0x16, 0x14, 0x15


def segments(data):
    offset = 0
    while offset < len(data):
        if len(data) - offset < 13:
            raise ValueError('Truncated PGS header')
        magic, _, _, kind, size = struct.unpack_from('>2sIIBH', data, offset)
        payload = data[offset + 13:offset + 13 + size]
        if magic != b'PG' or len(payload) != size:
            raise ValueError('Invalid or truncated PGS segment')
        yield kind, payload
        offset += 13 + size


def decode_rle(data, width, height):
    pixels = bytearray()
    row_start = rows = position = 0
    try:
        while position < len(data):
            byte = data[position]
            position += 1
            if byte:
                pixels.append(byte)
                continue
            flags = data[position]
            position += 1
            if not flags:
                if len(pixels) - row_start != width:
                    raise ValueError('PGS line width mismatch')
                row_start = len(pixels)
                rows += 1
                continue
            length = flags & 0x3f
            if flags & 0x40:
                length = length << 8 | data[position]
                position += 1
            color = 0
            if flags & 0x80:
                color = data[position]
                position += 1
            pixels += bytes([color]) * length
    except IndexError:
        raise ValueError('Truncated PGS run-length data') from None
    if rows != height or len(pixels) != width * height:
        raise ValueError('PGS object size mismatch')
    return bytes(pixels)


def decode(display_set):
    """Return palette indices, palette, and placed objects for one display set."""
    composition = palette_id = None
    palettes, objects, partial = {}, {}, {}
    for kind, payload in segments(display_set):
        if kind == PCS:
            palette_id = payload[9]
            composition, offset = [], 11
            for _ in range(payload[10]):
                object_id, _, flags, x, y = struct.unpack_from('>HBBHH', payload, offset)
                if flags & 0x80:
                    raise ValueError('Cropped PGS objects are unsupported')
                composition.append((object_id, x, y))
                offset += 8
        elif kind == PDS:
            if (len(payload) - 2) % 5:
                raise ValueError('Invalid PGS palette')
            palette = palettes.setdefault(payload[0], {})
            for offset in range(2, len(payload), 5):
                entry, luma, _, _, alpha = payload[offset:offset + 5]
                palette[entry] = (luma, alpha)
        elif kind == ODS:
            object_id, _, sequence = struct.unpack_from('>HBB', payload)
            if sequence & 0x80:
                length = int.from_bytes(payload[4:7], 'big') - 4
                width, height = struct.unpack_from('>HH', payload, 7)
                partial[object_id] = [length, width, height, bytearray(payload[11:])]
            elif object_id in partial:
                partial[object_id][3] += payload[4:]
            else:
                raise ValueError('PGS object continuation without start')
            if sequence & 0x40:
                length, width, height, data = partial.pop(object_id)
                if len(data) != length:
                    raise ValueError('PGS object length mismatch')
                objects[object_id] = (width, height, decode_rle(bytes(data), width, height))
    if not composition:
        raise ValueError('PGS display set has no visible composition')
    if palette_id not in palettes:
        raise ValueError('PGS composition palette is missing')
    try:
        placed = [(x, y, *objects[object_id]) for object_id, x, y in composition]
    except KeyError:
        raise ValueError('PGS composition object is missing') from None
    return palettes[palette_id], placed


def render(display_set, padding=30):
    """Render one display set as dark text on white, 8-bit grayscale, for OCR."""
    palette, placed = decode(display_set)
    # Composite luma over black, then invert: transparent -> white, bright text -> dark.
    table = bytes(255 - (palette[i][0] * palette[i][1] + 127) // 255 if i in palette else 255
                  for i in range(256))
    left = min(x for x, *_ in placed)
    top = min(y for _, y, *_ in placed)
    width = max(x + w for x, _, w, _, _ in placed) - left + 2 * padding
    height = max(y + h for _, y, _, h, _ in placed) - top + 2 * padding
    canvas = bytearray(b'\xff' * (width * height))
    for x, y, w, h, indices in placed:
        for row in range(h):
            start = (y - top + padding + row) * width + x - left + padding
            canvas[start:start + w] = indices[row * w:(row + 1) * w].translate(table)
    return Bitmap(width, height, bytes(canvas))


def pgm(bitmap):
    return b'P5\n%d %d\n255\n' % (bitmap.width, bitmap.height) + bitmap.pixels
