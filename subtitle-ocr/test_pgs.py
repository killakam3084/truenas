from itertools import groupby
from pathlib import Path
import struct
import tempfile
import unittest

from pgs import Bitmap, decode_rle, pgm, regions, render
from worker import presentations


def segment(kind, payload, timestamp=90000):
    return struct.pack('>2sIIBH', b'PG', timestamp, 0, kind, len(payload)) + payload


def rle(rows):
    data = b''
    for row in rows:
        for color, run in groupby(row):
            count = len(list(run))
            if color == 0:
                data += b'\0' + (bytes([count]) if count < 64 else bytes([0x40 | count >> 8, count & 0xff]))
            elif count < 3:
                data += bytes([color]) * count
            elif count < 64:
                data += bytes([0, 0x80 | count, color])
            else:
                data += bytes([0, 0xc0 | count >> 8, count & 0xff, color])
        data += b'\0\0'
    return data


def composition(objects, palette_id=0, cropped=False):
    payload = struct.pack('>HHBHBBBB', 1920, 1080, 0x10, 1, 0x80, 0, palette_id, len(objects))
    for object_id, x, y in objects:
        payload += struct.pack('>HBBHH', object_id, 0, 0x80 if cropped else 0, x, y)
    return segment(0x16, payload)


def palette(entries, palette_id=0):
    return segment(0x14, bytes([palette_id, 0]) + b''.join(
        bytes([entry, luma, 128, 128, alpha]) for entry, (luma, alpha) in entries.items()))


def objects(object_id, rows, fragments=1):
    data = rle(rows)
    header = struct.pack('>HB', object_id, 0)
    cut = len(data) // fragments
    chunks = [data[i * cut:(i + 1) * cut if i < fragments - 1 else len(data)] for i in range(fragments)]
    result = b''
    for index, chunk in enumerate(chunks):
        sequence = (0x80 if index == 0 else 0) | (0x40 if index == fragments - 1 else 0)
        if index == 0:
            chunk = (len(data) + 4).to_bytes(3, 'big') + struct.pack('>HH', len(rows[0]), len(rows)) + chunk
        result += segment(0x15, header + bytes([sequence]) + chunk)
    return result


END = segment(0x80, b'')
WHITE_TEXT_BLACK_EDGE = {1: (235, 255), 2: (16, 255), 3: (235, 0)}


class PgsTests(unittest.TestCase):
    def test_renders_dark_text_on_white_with_padding(self):
        display_set = (composition([(0, 100, 900)]) + palette(WHITE_TEXT_BLACK_EDGE)
                       + objects(0, [[1, 0, 2], [3, 1, 1]]) + END)
        bitmap = render(display_set, padding=1)
        self.assertEqual((bitmap.width, bitmap.height), (5, 4))
        self.assertEqual(bitmap.pixels, bytes([255] * 5 + [255, 20, 255, 239, 255]
                                              + [255, 255, 20, 20, 255] + [255] * 5))
        self.assertTrue(pgm(bitmap).startswith(b'P5\n5 4\n255\n'))

    def test_decodes_short_long_and_color_runs(self):
        rows = [[0] * 70 + [5] * 2 + [6] * 10 + [7] * 300, [0] * 3 + [9] * 379]
        self.assertEqual(decode_rle(rle(rows), 382, 2), bytes(rows[0] + rows[1]))

    def test_fragmented_objects_match_single_segment(self):
        rows = [[1] * 40 + [0] * 30 + [2] * 50] * 6
        whole = composition([(0, 0, 0)]) + palette(WHITE_TEXT_BLACK_EDGE) + objects(0, rows) + END
        split = composition([(0, 0, 0)]) + palette(WHITE_TEXT_BLACK_EDGE) + objects(0, rows, 3) + END
        self.assertEqual(render(whole), render(split))

    def test_composes_multiple_objects_at_relative_positions(self):
        display_set = (composition([(0, 10, 50), (1, 14, 53)]) + palette(WHITE_TEXT_BLACK_EDGE)
                       + objects(0, [[1, 1]]) + objects(1, [[2]]) + END)
        bitmap = render(display_set, padding=0)
        self.assertEqual((bitmap.width, bitmap.height), (5, 4))
        self.assertEqual(bitmap.pixels, bytes([20, 20, 255, 255, 255] + [255] * 10
                                              + [255, 255, 255, 255, 239]))

    def test_splits_lines_and_separately_placed_speakers_in_reading_order(self):
        width, height = 200, 60
        pixels = bytearray(b'\xff' * (width * height))

        def ink(x, y, w, h):
            for row in range(y, y + h):
                pixels[row * width + x:row * width + x + w] = b'\0' * w

        ink(150, 5, 20, 10)   # right speaker, top line
        ink(10, 30, 20, 10)   # left speaker, second line: two words with a narrow gap
        ink(35, 30, 20, 10)
        ink(10, 45, 30, 10)   # third line, separated from the second by blank rows
        found = regions(Bitmap(width, height, bytes(pixels)), padding=2, line_bridge=4)
        self.assertEqual([(r.width, r.height) for r in found], [(24, 14), (49, 14), (34, 14)])
        self.assertEqual(found[0].pixels[2 * 24 + 2], 0)

    def test_splits_same_line_speakers_separated_by_a_wide_gap(self):
        width = 120
        row = [255] * width
        for x in list(range(5, 15)) + list(range(80, 90)):
            row[x] = 0
        found = regions(Bitmap(width, 10, bytes(row * 10)), padding=0)
        self.assertEqual([(r.width, r.height) for r in found], [(10, 10), (10, 10)])

    def test_rejects_malformed_or_unsupported_display_sets(self):
        good = objects(0, [[1, 1]])
        cases = {
            'width': rle([[1, 1, 1]]),
            'truncated': rle([[1, 1]])[:-1],
        }
        for name, data in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                decode_rle(data, 2, 1)
        invalid = {
            'cropped': composition([(0, 0, 0)], cropped=True) + palette(WHITE_TEXT_BLACK_EDGE) + good,
            'palette': composition([(0, 0, 0)], palette_id=4) + palette(WHITE_TEXT_BLACK_EDGE) + good,
            'object': composition([(1, 0, 0)]) + palette(WHITE_TEXT_BLACK_EDGE) + good,
            'continuation': composition([(0, 0, 0)]) + segment(0x15, struct.pack('>HBB', 0, 0, 0x40)),
            'hidden': composition([]) + palette(WHITE_TEXT_BLACK_EDGE),
        }
        for name, display_set in invalid.items():
            with self.subTest(name), self.assertRaises(ValueError):
                render(display_set + END)

    def test_renders_display_sets_read_by_worker(self):
        visible = composition([(0, 0, 0)]) + palette(WHITE_TEXT_BLACK_EDGE) + objects(0, [[1]]) + END
        hidden = segment(0x16, struct.pack('>HHBHBBBB', 1920, 1080, 0x10, 2, 0, 0, 0, 0), 180000)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'stream.sup'
            path.write_bytes(visible + hidden + segment(0x80, b'', 180000))
            shown = [data for _, data, is_visible in presentations(path) if is_visible]
        self.assertEqual(render(shown[0], padding=0).pixels, bytes([20]))


if __name__ == '__main__':
    unittest.main()
