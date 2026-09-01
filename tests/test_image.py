"""PNG: decoded with the stdlib, drawn as coloured half blocks."""

import io
import os
import shutil
import struct
import sys
import tempfile
import unittest
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tide.image import png                                    # noqa: E402

RED, GREEN, BLUE, WHITE = (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)


def chunk(tag, body):
    return (struct.pack('>I', len(body)) + tag + body +
            struct.pack('>I', zlib.crc32(tag + body) & 0xffffffff))


def build(width, height, depth, colour, rows, extra=b'', filter_kind=0):
    """A PNG of raw scanlines, so the tests own every byte of the input."""
    body = b''.join(bytes([filter_kind]) + row for row in rows)
    return (png.SIGNATURE
            + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, depth,
                                         colour, 0, 0, 0))
            + extra + chunk(b'IDAT', zlib.compress(body)) + chunk(b'IEND', b''))


def quadrants(w, h):
    """Red, green / blue, white - so a mix-up of rows or columns shows."""
    out = []
    for y in range(h):
        row = bytearray()
        for x in range(w):
            top, left = y < h // 2, x < w // 2
            row += bytes(RED if (top and left) else GREEN if top else
                         BLUE if left else WHITE)
        out.append(bytes(row))
    return out


class TestTheDecoder(unittest.TestCase):
    def pixel(self, image, x, y):
        return tuple(image.rows[y][x * 3:x * 3 + 3])

    def test_colour_and_the_five_filters_agree(self):
        rows = quadrants(8, 8)
        plain = png.decode(build(8, 8, 8, 2, rows))
        for kind in (1, 2, 3, 4):
            # re-filter the same picture and check it comes back the same
            filtered = []
            prev = bytearray(24)
            for row in rows:
                line = bytearray()
                for i, value in enumerate(row):
                    left = row[i - 3] if i >= 3 else 0
                    up = prev[i]
                    corner = prev[i - 3] if i >= 3 else 0
                    if kind == 1:
                        guess = left
                    elif kind == 2:
                        guess = up
                    elif kind == 3:
                        guess = (left + up) >> 1
                    else:
                        p = left + up - corner
                        dl, du, dc = (abs(p - left), abs(p - up),
                                      abs(p - corner))
                        guess = (left if dl <= du and dl <= dc else
                                 up if du <= dc else corner)
                    line.append((value - guess) & 255)
                filtered.append(bytes(line))
                prev = bytearray(row)
            got = png.decode(build(8, 8, 8, 2, filtered, filter_kind=kind))
            self.assertEqual(got.rows, plain.rows, 'filter %d decoded wrong'
                             % kind)

    def test_the_quadrants_are_where_they_should_be(self):
        image = png.decode(build(8, 8, 8, 2, quadrants(8, 8)))
        self.assertEqual(self.pixel(image, 1, 1), RED)
        self.assertEqual(self.pixel(image, 6, 1), GREEN)
        self.assertEqual(self.pixel(image, 1, 6), BLUE)
        self.assertEqual(self.pixel(image, 6, 6), WHITE)

    def test_grey_palette_and_alpha(self):
        grey = png.decode(build(2, 1, 8, 0, [bytes((0, 255))]))
        self.assertEqual(self.pixel(grey, 0, 0), (0, 0, 0))
        self.assertEqual(self.pixel(grey, 1, 0), WHITE)

        table = chunk(b'PLTE', bytes(RED + GREEN))
        paletted = png.decode(build(2, 1, 8, 3, [bytes((0, 1))], extra=table))
        self.assertEqual(self.pixel(paletted, 0, 0), RED)
        self.assertEqual(self.pixel(paletted, 1, 0), GREEN)

        # transparent pixels are laid over the checkerboard, opaque ones are not
        rgba = png.decode(build(2, 1, 8, 6,
                                [bytes((255, 0, 0, 255, 0, 255, 0, 0))]))
        self.assertEqual(self.pixel(rgba, 0, 0), RED)
        self.assertEqual(self.pixel(rgba, 1, 0), png.CHECK[0])

    def test_deep_and_shallow_samples(self):
        deep = png.decode(build(2, 1, 16, 2, [struct.pack(
            '>6H', 65535, 0, 0, 0, 65535, 0)]))
        self.assertEqual(self.pixel(deep, 0, 0), RED)
        self.assertEqual(self.pixel(deep, 1, 0), GREEN)
        # one bit per pixel: 0b10000000 is white then black
        shallow = png.decode(build(2, 1, 1, 0, [bytes([0b10000000])]))
        self.assertEqual(self.pixel(shallow, 0, 0), WHITE)
        self.assertEqual(self.pixel(shallow, 1, 0), (0, 0, 0))

    def test_what_it_will_not_read_it_says_so_about(self):
        for data, why in (
                (b'not a png at all', 'not a PNG'),
                (png.SIGNATURE, 'no header'),
                (png.SIGNATURE + chunk(b'IHDR', struct.pack(
                    '>IIBBBBB', 4, 4, 8, 2, 0, 0, 0)), 'no image data'),
                (build(4, 4, 8, 2, quadrants(4, 4)[:2]), 'stops early')):
            with self.assertRaises(png.Unsupported) as caught:
                png.decode(data)
            self.assertIn(why, str(caught.exception))

    def test_an_interlaced_file_is_refused_plainly(self):
        head = struct.pack('>IIBBBBB', 4, 4, 8, 2, 0, 0, 1)
        data = (png.SIGNATURE + chunk(b'IHDR', head)
                + chunk(b'IDAT', zlib.compress(b'\0' * 4)) + chunk(b'IEND', b''))
        with self.assertRaises(png.Unsupported) as caught:
            png.decode(data)
        self.assertIn('interlaced', str(caught.exception))


class TestTheTab(unittest.TestCase):
    def setUp(self):
        self.cfg = tempfile.mkdtemp()
        os.environ['TIDE_CONFIG_HOME'] = self.cfg
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, 'shot.png')
        with open(self.path, 'wb') as f:
            f.write(build(64, 32, 8, 2, quadrants(64, 32)))

    def tearDown(self):
        os.environ.pop('TIDE_CONFIG_HOME', None)
        shutil.rmtree(self.cfg, ignore_errors=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def app(self):
        from tide.app import App
        from tide.term import Screen
        app = App(root=self.tmp, paths=[], out=io.StringIO())
        app.screen = Screen(80, 24)
        app.show_term = False
        app.show_tree = False
        return app

    def test_a_png_opens_as_a_picture_not_as_bytes(self):
        app = self.app()
        tab = app.open_file(self.path)
        self.assertTrue(getattr(tab, 'is_image', False))
        self.assertEqual((tab.image.width, tab.image.height), (64, 32))
        app.render()
        cells = [app.screen.cells[y][x]
                 for y in range(tab.rect.y, tab.rect.y2 - 1)
                 for x in range(tab.rect.x, tab.rect.x2)]
        painted = [c for c in cells if c[0] == '\u2580']
        self.assertTrue(painted, 'nothing was drawn')
        self.assertGreater(len({c[1] for c in painted}), 1, 'one flat colour')

    def test_the_quadrants_land_in_the_right_corners(self):
        app = self.app()
        tab = app.open_file(self.path)
        app.render()
        grid = tab._grid[1]
        def corner(row, col):
            return tuple(grid[row][col][0])
        self.assertEqual(corner(0, 0), RED)
        self.assertEqual(corner(0, len(grid[0]) - 1), GREEN)
        self.assertEqual(corner(len(grid) - 1, 0), BLUE)
        self.assertEqual(corner(len(grid) - 1, len(grid[0]) - 1), WHITE)

    def test_zoomed_in_you_can_pan_around_it(self):
        app = self.app()
        tab = app.open_file(self.path)
        tab.zoom = 4.0
        seen = []
        for pan in ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)):
            tab.pan, tab._grid = pan, None
            app.render()
            colours = {tuple(cell[0]) for line in tab._grid[1] for cell in line}
            self.assertEqual(len(colours), 1,
                             'a corner showed more than its own quadrant')
            seen.append(colours.pop())
        self.assertEqual(seen, [RED, GREEN, BLUE, WHITE],
                         'panning did not move around the picture')

    def test_it_is_read_only_and_saves_nothing(self):
        app = self.app()
        tab = app.open_file(self.path)
        before = open(self.path, 'rb').read()
        self.assertFalse(app.save(tab))
        self.assertIsNone(app.text_editor(), 'an image counted as text')
        self.assertEqual(open(self.path, 'rb').read(), before)

    def test_zooming_and_fitting(self):
        from tide.keys import Key
        app = self.app()
        tab = app.open_file(self.path)
        app.render()
        fit = tab._fit_scale()
        tab.on_key(Key('char', char='+'))
        self.assertGreater(tab.zoom, fit)
        tab.on_key(Key('char', char='f'))
        self.assertIsNone(tab.zoom, 'f did not go back to fitting the pane')

    def test_a_file_that_goes_away_says_so_and_keeps_the_picture(self):
        app = self.app()
        tab = app.open_file(self.path)
        os.remove(self.path)
        tab.check_disk(force=True)
        self.assertTrue(tab.missing)
        self.assertIsNotNone(tab.image, 'the picture went with the file')
        self.assertEqual(tab.tab_mark()[0], '!')

    def test_a_broken_png_opens_as_a_message_not_a_crash(self):
        bad = os.path.join(self.tmp, 'broken.png')
        with open(bad, 'wb') as f:
            f.write(png.SIGNATURE + b'rubbish beyond this point')
        app = self.app()
        tab = app.open_file(bad)
        app.render()
        self.assertIsNone(tab.image)
        self.assertTrue(tab.trouble)
        painted = '\n'.join(''.join(c[0] or ' ' for c in row)
                             for row in app.screen.cells)
        self.assertIn('header', painted)


class TestRealPixels(unittest.TestCase):
    """Where the terminal can draw the picture itself, tide lets it."""

    def setUp(self):
        self.cfg = tempfile.mkdtemp()
        os.environ['TIDE_CONFIG_HOME'] = self.cfg
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, 'shot.png')
        with open(self.path, 'wb') as f:
            f.write(build(64, 32, 8, 2, quadrants(64, 32)))

    def tearDown(self):
        os.environ.pop('TIDE_CONFIG_HOME', None)
        shutil.rmtree(self.cfg, ignore_errors=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def app(self):
        from tide.app import App
        from tide.image.protocol import Kitty
        from tide.term import Screen
        app = App(root=self.tmp, paths=[], out=io.StringIO())
        app.screen = Screen(80, 24)
        app.show_term = False
        app.show_tree = False
        app.pictures = Kitty(app.out)        # as if the terminal had said yes
        return app

    @staticmethod
    def commands(app):
        """The graphics commands in what tide has written so far."""
        text = app.out.getvalue()
        return [piece.split('\x1b\\')[0].split(';')[0]
                for piece in text.split('\x1b_G')[1:]]

    def test_the_file_goes_over_once_and_is_placed_after(self):
        app = self.app()
        tab = app.open_file(self.path)
        app.render()
        sent = self.commands(app)
        self.assertTrue(any('a=t' in c for c in sent), 'the file was not sent')
        self.assertTrue(any('a=p' in c for c in sent), 'it was not placed')
        self.assertIn('f=100', sent[0], 'it was not sent as a PNG')
        app.out.truncate(0)
        app.out.seek(0)
        app.need_render = True
        app.render()
        self.assertEqual(self.commands(app), [],
                         'a frame that changed nothing drew it again')
        # but a picture that has moved, or been painted over, is placed again
        from tide.keys import Key
        app.editor.on_key(Key('char', char='+'))
        app.need_render = True
        app.render()
        again = self.commands(app)
        self.assertTrue(all('a=t' not in c for c in again),
                        'the file was sent a second time')
        self.assertTrue(any('a=p,i=%d' % tab.held in c for c in again))

    def test_it_comes_off_the_screen_when_something_else_is_in_front(self):
        app = self.app()
        tab = app.open_file(self.path)
        app.render()
        app.new_file()                       # another tab in front of it
        app.out.truncate(0)
        app.out.seek(0)
        app.need_render = True
        app.render()
        self.assertTrue(any('a=d' in c for c in self.commands(app)),
                        'the picture was left on screen')
        self.assertNotIn(tab.held, app.pictures.showing)

    def test_a_menu_over_it_hides_it_rather_than_going_under_it(self):
        app = self.app()
        app.open_file(self.path)
        app.render()
        app.open_menu('View')
        app.out.truncate(0)
        app.out.seek(0)
        app.need_render = True
        app.render()
        placed = [c for c in self.commands(app) if 'a=p' in c]
        self.assertFalse(placed, 'the picture stayed over the menu')

    def test_without_a_drawing_terminal_it_is_blocks_as_before(self):
        app = self.app()
        app.pictures = None
        tab = app.open_file(self.path)
        app.render()
        self.assertNotIn('\x1b_G', app.out.getvalue())
        self.assertIsNotNone(tab._grid, 'nothing was drawn in cells either')


if __name__ == '__main__':
    unittest.main()
