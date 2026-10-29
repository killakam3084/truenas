from collections import namedtuple
from concurrent.futures import ProcessPoolExecutor
import ctypes
import math
import os
from pathlib import Path

from pgs import pgm, regions, render

TESSDATA = Path('/opt/subtitle-ocr/tessdata')
SINGLE_LINE = 7
Recognition = namedtuple('Recognition', 'text unread')


def library():
    lib = ctypes.CDLL('libtesseract.so.5')
    lib.TessVersion.restype = ctypes.c_char_p
    lib.TessBaseAPICreate.restype = ctypes.c_void_p
    lib.TessBaseAPIInit3.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
    lib.TessBaseAPISetPageSegMode.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.TessBaseAPISetImage.argtypes = [ctypes.c_void_p, ctypes.c_char_p] + [ctypes.c_int] * 4
    lib.TessBaseAPISetSourceResolution.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.TessBaseAPIGetUTF8Text.argtypes = [ctypes.c_void_p]
    lib.TessBaseAPIGetUTF8Text.restype = ctypes.c_void_p
    lib.TessDeleteText.argtypes = [ctypes.c_void_p]
    lib.TessBaseAPIEnd.argtypes = [ctypes.c_void_p]
    lib.TessBaseAPIDelete.argtypes = [ctypes.c_void_p]
    return lib


def version():
    return library().TessVersion().decode()


class Tesseract:
    def __init__(self, tessdata=TESSDATA, language='eng'):
        self.lib = library()
        self.api = self.lib.TessBaseAPICreate()
        if self.lib.TessBaseAPIInit3(self.api, str(tessdata).encode(), language.encode()):
            self.close()
            raise RuntimeError(f'Unable to load Tesseract {language} model from {tessdata}')

    def read(self, bitmap, mode):
        self.lib.TessBaseAPISetPageSegMode(self.api, mode)
        self.lib.TessBaseAPISetImage(self.api, bitmap.pixels, bitmap.width, bitmap.height, 1, bitmap.width)
        self.lib.TessBaseAPISetSourceResolution(self.api, 300)
        pointer = self.lib.TessBaseAPIGetUTF8Text(self.api)
        try:
            text = ctypes.string_at(pointer).decode()
        finally:
            self.lib.TessDeleteText(pointer)
        return '\n'.join(line.strip() for line in text.splitlines() if line.strip())

    def recognize(self, display_set):
        # Tesseract's block layout analysis can drop separately placed speaker lines.
        lines, unread = [], []
        for region in regions(render(display_set)):
            text = self.read(region, SINGLE_LINE)
            if text:
                lines.append(text)
            else:
                unread.append(pgm(region))
        return Recognition('\n'.join(lines), unread)

    def close(self):
        self.lib.TessBaseAPIEnd(self.api)
        self.lib.TessBaseAPIDelete(self.api)


_engine = None


def _start(tessdata):
    global _engine
    _engine = Tesseract(tessdata)


def _recognize(display_set):
    return _engine.recognize(display_set)


def recognize_all(display_sets, workers, tessdata=TESSDATA):
    with ProcessPoolExecutor(max(1, min(workers, len(display_sets))),
                             initializer=_start, initargs=(tessdata,)) as pool:
        return list(pool.map(_recognize, display_sets, chunksize=16))


def worker_count(cpu_max=Path('/sys/fs/cgroup/cpu.max')):
    try:
        quota, period = Path(cpu_max).read_text().split()
        return max(1, math.ceil(int(quota) / int(period)))
    except (OSError, ValueError):
        return os.cpu_count() or 1
