"""PNG, decoded with zlib and struct.

The standard library has no image reader - tkinter's needs a display, which
is no use over ssh - so tide reads PNG itself. It is a short format: a header,
a deflate stream of scanlines, and five filters to undo. What comes back is
plain RGB rows, which the viewer turns into coloured cells.

Not handled: interlaced (Adam7) files, which say so plainly rather than
guessing. Everything a screenshot or an exported image is made of - 8 and 16
bit, grey, palette, colour, with or without alpha - is here.
"""

import struct
import zlib

SIGNATURE = b'\x89PNG\r\n\x1a\n'
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}      # by colour type
MAX_PIXELS = 40 << 20                          # 40 megapixels is plenty

# what shows through a transparent pixel, as every image viewer does it
CHECK = (0x28, 0x28, 0x28), (0x38, 0x38, 0x38)
CHECK_SIZE = 8


class Unsupported(Exception):
    """This file is a PNG tide cannot read, and here is why."""


class Image(object):
    def __init__(self, width, height, rows, kind):
        self.width = width
        self.height = height
        self.rows = rows            # one bytes of R,G,B triples per row
        self.kind = kind            # how it was stored, for the status line


def _chunks(data):
    pos = 8
    while pos + 8 <= len(data):
        size = struct.unpack('>I', data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        yield tag, data[pos + 8:pos + 8 + size]
        pos += size + 12
        if tag == b'IEND':
            return


def _unfilter(raw, height, stride, bpp):
    """Undo the five scanline filters; every row depends on the one above."""
    rows = []
    prev = bytearray(stride)
    at = 0
    for _y in range(height):
        if at + 1 + stride > len(raw):
            raise Unsupported('the image data stops early')
        kind = raw[at]
        line = bytearray(raw[at + 1:at + 1 + stride])
        at += 1 + stride
        if kind == 1:                                    # each byte + its left
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 255
        elif kind == 2:                                  # + the one above
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif kind == 3:                                  # + their average
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 255
        elif kind == 4:                                  # Paeth's predictor
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                up = prev[i]
                corner = prev[i - bpp] if i >= bpp else 0
                guess = left + up - corner
                dl, du, dc = (abs(guess - left), abs(guess - up),
                              abs(guess - corner))
                if dl <= du and dl <= dc:
                    near = left
                elif du <= dc:
                    near = up
                else:
                    near = corner
                line[i] = (line[i] + near) & 255
        elif kind != 0:
            raise Unsupported('filter %d is not a PNG filter' % kind)
        rows.append(line)
        prev = line
    return rows


def _samples(line, width, channels, depth):
    """One scanline as a flat list of samples, whatever the bit depth."""
    if depth == 8:
        return line
    if depth == 16:
        return line[0::2]                       # the high byte is enough
    out = bytearray()
    per_byte = 8 // depth
    mask = (1 << depth) - 1
    scale = 255 // mask                         # 1 bit -> 0/255, 4 bit -> x17
    wanted = width * channels
    for byte in line:
        for slot in range(per_byte):
            shift = 8 - depth * (slot + 1)
            out.append(((byte >> shift) & mask) * scale)
            if len(out) == wanted:
                return out
    return out


def _to_rgb(rows, width, colour, depth, palette, trns):
    """Every row as R,G,B bytes, with transparency laid over a checkerboard."""
    channels = CHANNELS[colour]
    alpha_of = None
    if colour == 3:
        if not palette:
            raise Unsupported('a palette image with no palette in it')
        table = [palette[i:i + 3] for i in range(0, len(palette), 3)]
        alpha_of = trns or b''
    out = []
    for y, line in enumerate(rows):
        s = _samples(line, width, channels, depth)
        row = bytearray()
        for x in range(width):
            alpha = 255
            if colour == 2:
                i = x * 3
                r, g, b = s[i], s[i + 1], s[i + 2]
            elif colour == 6:
                i = x * 4
                r, g, b, alpha = s[i], s[i + 1], s[i + 2], s[i + 3]
            elif colour == 0:
                r = g = b = s[x]
            elif colour == 4:
                r = g = b = s[x * 2]
                alpha = s[x * 2 + 1]
            else:                                        # palette
                index = s[x]
                if index >= len(table):
                    raise Unsupported('a colour outside the palette')
                r, g, b = table[index]
                if index < len(alpha_of):
                    alpha = alpha_of[index]
            if alpha != 255:
                under = CHECK[((x // CHECK_SIZE) + (y // CHECK_SIZE)) & 1]
                r = (r * alpha + under[0] * (255 - alpha)) // 255
                g = (g * alpha + under[1] * (255 - alpha)) // 255
                b = (b * alpha + under[2] * (255 - alpha)) // 255
            row += bytes((r, g, b))
        out.append(bytes(row))
    return out


NAMES = {0: 'grey', 2: 'colour', 3: 'palette', 4: 'grey+alpha', 6: 'colour+alpha'}


def decode(data):
    """A PNG's bytes in, an Image of RGB rows out."""
    if data[:8] != SIGNATURE:
        raise Unsupported('this is not a PNG')
    head = None
    palette = b''
    trns = None
    parts = []
    for tag, body in _chunks(data):
        if tag == b'IHDR':
            if len(body) < 13:
                raise Unsupported('the header is too short')
            head = struct.unpack('>IIBBBBB', body[:13])
        elif tag == b'PLTE':
            palette = body
        elif tag == b'tRNS':
            trns = body
        elif tag == b'IDAT':
            parts.append(body)
    if head is None:
        raise Unsupported('there is no header in this PNG')
    width, height, depth, colour, compression, _filter, interlace = head
    if not width or not height:
        raise Unsupported('the image has no size')
    if width * height > MAX_PIXELS:
        raise Unsupported('%d by %d is more than tide will decode'
                          % (width, height))
    if interlace:
        raise Unsupported('interlaced PNGs are not supported')
    if compression != 0 or colour not in CHANNELS:
        raise Unsupported('colour type %d is not a PNG colour type' % colour)
    if depth not in (1, 2, 4, 8, 16) or (depth != 8 and colour in (2, 4, 6)
                                         and depth != 16):
        raise Unsupported('%d bits per sample is not supported here' % depth)
    if not parts:
        raise Unsupported('there is no image data in this PNG')
    try:
        raw = zlib.decompress(b''.join(parts))
    except zlib.error as exc:
        raise Unsupported('the image data is damaged (%s)' % exc)
    channels = CHANNELS[colour]
    stride = (width * channels * depth + 7) // 8
    bpp = max(1, channels * depth // 8)
    rows = _unfilter(raw, height, stride, bpp)
    kind = '%s %d-bit' % (NAMES.get(colour, '?'), depth)
    return Image(width, height, _to_rgb(rows, width, colour, depth, palette,
                                        trns), kind)


def read(path):
    with open(path, 'rb') as f:
        return decode(f.read())
