"""Global preferences: the store, the panel, and that they outlive a session."""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import ESC, Session
from tide import settings, theme
from tide.app import App
from tide.keys import Key

F9 = ESC + '[20~'
RIGHT, LEFT, DOWN, UP = ESC + '[C', ESC + '[D', ESC + '[B', ESC + '[A'


class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='tide-set-')
        self.path = os.path.join(self.tmp, 'tide', 'settings.json')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_defaults_when_there_is_no_file(self):
        values = settings.load(self.path)
        self.assertEqual(values, settings.DEFAULTS)

    def test_round_trip(self):
        values = settings.load(self.path)
        values.update(theme='light', max_mb=5.0, show_terminal=False)
        self.assertTrue(settings.save(values, self.path))
        again = settings.load(self.path)
        self.assertEqual(again['theme'], 'light')
        self.assertEqual(again['max_mb'], 5.0)
        self.assertFalse(again['show_terminal'])

    def test_only_known_keys_are_written(self):
        values = settings.load(self.path)
        values['nonsense'] = 42
        settings.save(values, self.path)
        with io.open(self.path, encoding='utf-8') as f:
            self.assertNotIn('nonsense', json.load(f))

    def test_a_broken_file_falls_back(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, 'w') as f:
            f.write('{ not json at all')
        self.assertEqual(settings.load(self.path), settings.DEFAULTS)

    def test_nonsense_values_are_repaired(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, 'w') as f:
            json.dump({'theme': 'neon', 'max_lines': 5, 'tab_width': 99,
                       'autosave_delay': 'soon'}, f)
        values = settings.load(self.path)
        self.assertEqual(values['theme'], 'dark')          # unknown theme
        self.assertEqual(values['max_lines'], 100)         # clamped up
        self.assertEqual(values['tab_width'], 16)          # clamped down
        self.assertEqual(values['autosave_delay'], 0.8)    # not a number

    def test_every_field_has_a_default_and_a_hint(self):
        for key, _label, options in settings.FIELDS:
            self.assertIn(key, settings.DEFAULTS)
            self.assertIn(settings.DEFAULTS[key], options,
                          '%s default is not one of its choices' % key)
            self.assertIn(key, settings.HINTS)


class TestThemes(unittest.TestCase):
    def tearDown(self):
        theme.apply('dark')

    def test_four_themes_are_offered(self):
        self.assertEqual(theme.NAMES, ['dark', 'midnight', 'ember', 'light'])

    def test_each_theme_defines_every_colour(self):
        keys = set(theme.DARK)
        for name in theme.NAMES:
            self.assertEqual(set(theme.PALETTES[name]), keys,
                             '%s is missing colours' % name)

    def test_applying_changes_the_live_colours(self):
        theme.apply('dark')
        dark_bg, dark_kw = theme.BG, theme.token_style('keyword')[0]
        theme.apply('light')
        self.assertNotEqual(theme.BG, dark_bg)
        self.assertNotEqual(theme.token_style('keyword')[0], dark_kw)
        self.assertGreater(theme.BG, 240, 'the light theme should be light')
        theme.apply('midnight')
        self.assertLess(theme.BG, 240)

    def test_unknown_theme_falls_back_to_dark(self):
        self.assertEqual(theme.apply('nope'), 'dark')
        self.assertEqual(theme.BG, theme.DARK['BG'])


class TestAppSettings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='tide-app-set-')
        self.old_home = os.environ.get('TIDE_CONFIG_HOME')
        os.environ['TIDE_CONFIG_HOME'] = self.tmp
        self.project = tempfile.mkdtemp(prefix='tide-proj-')
        with open(os.path.join(self.project, 'a.py'), 'w') as f:
            f.write('x = 1\n')

    def tearDown(self):
        if self.old_home is None:
            os.environ.pop('TIDE_CONFIG_HOME', None)
        else:
            os.environ['TIDE_CONFIG_HOME'] = self.old_home
        theme.apply('dark')
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.project, ignore_errors=True)

    def app(self):
        return App(root=self.project, paths=[os.path.join(self.project, 'a.py')],
                   out=io.StringIO())

    def test_changes_are_written_and_applied(self):
        app = self.app()
        app.set_setting('theme', 'forest')
        app.set_setting('max_mb', 5.0)
        app.set_setting('show_terminal', False)
        self.assertEqual(theme.current, 'forest')
        self.assertEqual(app.max_file_bytes, int(5 * 1024 * 1024))
        self.assertFalse(app.show_term)
        stored = settings.load(settings.config_path())
        self.assertEqual(stored['theme'], 'forest')
        self.assertEqual(stored['max_mb'], 5.0)
        self.assertFalse(stored['show_terminal'])

    def test_a_new_session_picks_them_up(self):
        first = self.app()
        first.set_setting('theme', 'light')
        first.set_setting('max_lines', 2000)
        first.set_setting('show_tree', False)
        second = self.app()
        self.assertEqual(second.settings['theme'], 'light')
        self.assertEqual(second.max_file_lines, 2000)
        self.assertFalse(second.show_tree)
        self.assertEqual(theme.current, 'light')

    def test_autosave_toggle_persists(self):
        app = self.app()
        app.toggle_autosave()
        self.assertFalse(app.autosave)
        self.assertFalse(settings.load(settings.config_path())['autosave'])
        self.assertFalse(self.app().autosave)

    def test_indent_width_applies_to_files_without_indentation(self):
        app = self.app()
        self.assertEqual(app.editor.tab_width, 4)
        app.set_setting('tab_width', 2)
        self.assertEqual(app.editor.tab_width, 2)

    def test_a_detected_indent_wins_over_the_setting(self):
        deep = os.path.join(self.project, 'deep.py')
        with open(deep, 'w') as f:
            f.write('def f():\n        return 1\n')      # eight space indent
        app = self.app()
        ed = app.open_file(deep)
        self.assertTrue(ed.indent_detected)
        self.assertEqual(ed.tab_width, 8)
        app.set_setting('tab_width', 2)
        self.assertEqual(ed.tab_width, 8, 'the file should keep its own indentation')


class TestSettingsPanel(unittest.TestCase):
    cols, rows = 92, 24

    def setUp(self):
        self.cfg = tempfile.mkdtemp(prefix='tide-panel-cfg-')
        self.project = tempfile.mkdtemp(prefix='tide-panel-')
        with open(os.path.join(self.project, 'a.py'), 'w') as f:
            f.write('def hello():\n    return 1\n')
        self.s = self.session()

    def session(self):
        s = Session(['a.py', self.project], cols=self.cols, rows=self.rows,
                    cwd=self.project, env={'TIDE_CONFIG_HOME': self.cfg})
        s.pump(0.8)
        return s

    def tearDown(self):
        self.s.close()
        shutil.rmtree(self.cfg, ignore_errors=True)
        shutil.rmtree(self.project, ignore_errors=True)

    def stored(self):
        return settings.load(os.path.join(self.cfg, 'tide', 'settings.json'))

    def click_row(self, label):
        """Click the right half of a settings row, which advances its value."""
        for y, line in enumerate(self.s.text()):
            if line[11:].startswith(label):
                self.s.click(self.cols // 2 + 6, y)
                return True
        raise AssertionError('no %r row on screen' % label)

    def test_f9_opens_and_escape_closes(self):
        self.s.key(F9)
        self.assertIn('Settings', self.s.screen())
        self.assertIn('Theme', self.s.screen())
        self.assertIn('Indent width', self.s.screen())
        self.s.key(ESC)
        self.assertNotIn('Indent width', self.s.screen())

    def test_alt_comma_opens_it_too(self):
        self.s.key(ESC + ',')
        self.assertIn('Theme', self.s.screen())

    def test_ctrl_t_is_not_the_settings_any_more(self):
        # it switches to the tab you were on before; the settings are f9,
        # alt+, or the button in the top right
        self.s.key(chr(ord('t') - 96))
        self.assertNotIn('Indent width', self.s.screen())

    def test_f9_toggles(self):
        self.s.key(F9)
        self.assertIn('Indent width', self.s.screen())
        self.s.key(F9)
        self.assertNotIn('Indent width', self.s.screen())

    def test_the_settings_chip_is_clickable(self):
        top = self.s.text()[0]
        self.assertIn('settings', top, 'no settings affordance in the top bar')
        self.s.click(top.rindex('settings') + 2, 0)
        self.assertIn('Indent width', self.s.screen())

    def test_changing_the_theme_repaints_and_persists(self):
        before = self.s.cell(60, 4)[2]
        self.s.key(F9)
        self.s.key(RIGHT)                    # dark -> alien
        self.s.key(ESC)
        self.s.pump(0.4)
        self.assertNotEqual(self.s.cell(60, 4)[2], before, 'the screen did not repaint')
        self.assertEqual(self.stored()['theme'], 'alien')

    def test_light_theme_really_is_light(self):
        self.s.key(F9)
        for _ in range(5):    # dark -> alien -> forest -> parchment -> octopus
                              #      -> light
            self.s.key(RIGHT)
        self.s.key(ESC)
        self.s.pump(0.4)
        self.assertEqual(self.stored()['theme'], 'light')
        self.assertGreater(self.s.cell(60, 4)[2], 240)

    def test_turning_the_terminal_panel_off(self):
        self.assertIn('TERMINAL', self.s.screen())
        self.s.key(F9)
        self.click_row('Terminal panel')
        self.s.key(ESC)
        self.s.pump(0.4)
        self.assertNotIn('TERMINAL', self.s.screen())
        self.assertFalse(self.stored()['show_terminal'])

    def test_turning_the_explorer_off(self):
        self.s.key(F9)
        self.click_row('Explorer')
        self.s.key(ESC)
        self.s.pump(0.4)
        self.assertNotIn('EXPLORER', self.s.screen())
        self.assertFalse(self.stored()['show_tree'])

    def test_clicking_a_row_changes_it(self):
        self.s.key(F9)
        target = None
        for y, line in enumerate(self.s.text()):
            label = line[11:].rstrip()
            if label.startswith('Auto-save') and not label.startswith('Auto-save after'):
                target = y
                break
        self.assertIsNotNone(target, 'no Auto-save row on screen')
        self.s.click(self.cols // 2 + 6, target)         # right half: next value
        self.s.key(ESC)
        self.s.pump(0.3)
        self.assertFalse(self.stored()['autosave'])
        self.assertIn('manual save', self.s.screen())

    def test_settings_survive_a_restart(self):
        self.s.key(F9)
        self.s.key(RIGHT)                    # theme -> alien
        self.s.key(ESC)
        self.s.pump(0.4)
        self.s.close()
        self.s = self.session()
        self.s.key(F9)
        self.assertIn('alien', self.s.screen())

    def test_the_file_is_the_documented_one(self):
        self.s.key(F9)
        self.s.key(RIGHT)
        self.s.pump(0.3)
        self.assertTrue(os.path.exists(os.path.join(self.cfg, 'tide', 'settings.json')))


if __name__ == '__main__':
    unittest.main(verbosity=2)
