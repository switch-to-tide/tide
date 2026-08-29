"""End-to-end tests: the IDE runs in a real pty and we read back the screen."""

import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import (ALT_A, ALT_LEFT, ALT_RIGHT, ALT_UP, BACKSPACE, CTRL, CTRL_RIGHT,
                     DOWN, END, ENTER, ESC, ESCAPE, F1, F2, F4, F6, HOME, SHIFT_DOWN,
                     SHIFT_RIGHT, Session, UP)

SAMPLE = '''def greet(name):
    """Say hello."""
    msg = "hi " + name   # a comment
    print(msg)
    return 42


class Thing:
    value = 3.14
'''

NOTES = '# Notes\n\nSome *markdown* text.\n'


class IDETest(unittest.TestCase):
    """Base class: a temp project and a running IDE session."""

    cols, rows = 100, 30
    open_args = ('hello.py',)

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='tide-test-')
        with open(os.path.join(self.tmp, 'hello.py'), 'w') as f:
            f.write(SAMPLE)
        with open(os.path.join(self.tmp, 'notes.md'), 'w') as f:
            f.write(NOTES)
        os.mkdir(os.path.join(self.tmp, 'sub'))
        with open(os.path.join(self.tmp, 'sub', 'deep.txt'), 'w') as f:
            f.write('deep file\n')
        self.make_files()          # subclasses add fixtures before the IDE starts
        args = [os.path.join(self.tmp, a) for a in self.open_args] + [self.tmp]
        self.s = Session(args, cols=self.cols, rows=self.rows, cwd=self.tmp)

    def make_files(self):
        pass

    def tearDown(self):
        self.s.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def read(self, name):
        with open(os.path.join(self.tmp, name)) as f:
            return f.read()


class TestLayout(IDETest):
    def test_panels_are_visible(self):
        screen = self.s.screen()
        self.assertIn('EXPLORER', screen)
        self.assertIn('hello.py', screen)
        self.assertIn('TERMINAL', screen)
        self.assertIn('def greet(name):', screen)
        self.assertIn('Ln 1, Col 1', screen)
        self.assertIn('Python', screen)

    def test_line_numbers_and_tree(self):
        self.assertIsNotNone(self.s.find('1 def greet'))
        self.assertIsNotNone(self.s.find('notes.md'))
        self.assertIsNotNone(self.s.find('sub'))

    def test_syntax_colours(self):
        x, y = self.s.find('def greet')
        self.assertEqual(self.s.cell(x, y)[1], 75)          # keyword blue
        xs, ys = self.s.find('"hi "')
        self.assertEqual(self.s.cell(xs, ys)[1], 173)       # string orange
        xc, yc = self.s.find('# a comment')
        self.assertEqual(self.s.cell(xc, yc)[1], 71)        # comment green
        xn, yn = self.s.find('3.14')
        self.assertEqual(self.s.cell(xn, yn)[1], 151)       # number

    def test_toggle_panels(self):
        self.s.key(CTRL('b'))
        self.assertNotIn('EXPLORER', self.s.screen())
        self.s.key(CTRL('b'))
        self.assertIn('EXPLORER', self.s.screen())
        self.s.key(CTRL('j'))       # focus terminal
        self.s.key(CTRL('j'))       # hide it
        self.assertNotIn('TERMINAL', self.s.screen())

    def test_help_overlay(self):
        self.s.key(F1)
        # the list is longer than a 24 row window, so check something the
        # second section shows before it runs off the bottom
        self.assertIn('undo / redo', self.s.screen())
        self.s.key(ESCAPE)
        self.assertNotIn('toggle comment', self.s.screen())


class TestEditing(IDETest):
    def test_click_moves_cursor_and_types(self):
        x, y = self.s.find('print(msg)')
        self.s.click(x + 10, y)
        self.assertIn('Ln 4, Col 15', self.s.screen())
        self.s.type('  # typed')
        self.assertIn('print(msg)  # typed', self.s.line(y))

    def test_double_click_selects_word(self):
        x, y = self.s.find('greet')
        self.s.click(x + 1, y, count=2)
        self.assertIn('(5 selected)', self.s.screen())

    def test_drag_select_and_delete_chunk(self):
        x, y = self.s.find('print(msg)')
        self.s.drag(x, y, x + 10, y)
        self.assertIn('(10 selected)', self.s.screen())
        self.s.key(BACKSPACE)
        self.assertNotIn('print(msg)', self.s.screen())
        self.s.key(CTRL('z'))
        self.assertIn('print(msg)', self.s.screen())

    def test_multiline_selection_delete(self):
        x, y = self.s.find('msg = ')
        self.s.click(x, y)
        self.s.key(SHIFT_DOWN)
        self.s.key(SHIFT_DOWN)
        self.s.key(BACKSPACE)
        screen = self.s.screen()
        self.assertNotIn('print(msg)', screen)
        self.assertIn('return 42', screen)

    def test_undo_redo(self):
        x, y = self.s.find('return 42')
        self.s.click(x, y)
        self.s.key(END)
        self.s.type('0')
        self.assertIn('return 420', self.s.screen())
        self.s.key(CTRL('z'))
        self.assertIn('return 42', self.s.screen())
        self.assertNotIn('return 420', self.s.screen())
        self.s.key(CTRL('y'))
        self.assertIn('return 420', self.s.screen())

    def test_comment_toggle_and_duplicate(self):
        x, y = self.s.find('return 42')
        self.s.click(x, y)
        self.s.key('\x1f')                     # ctrl+/
        self.assertIn('# return 42', self.s.screen())
        self.s.key('\x1f')
        self.assertNotIn('# return 42', self.s.screen())
        self.s.key(CTRL('d'))                  # duplicate line
        self.assertEqual(self.s.screen().count('return 42'), 2)

    def test_move_line_with_alt_arrow(self):
        x, y = self.s.find('print(msg)')
        self.s.click(x, y)
        self.s.key(ALT_UP)
        moved = self.s.text()
        idx_print = next(i for i, l in enumerate(moved) if 'print(msg)' in l)
        idx_msg = next(i for i, l in enumerate(moved) if 'msg = ' in l)
        self.assertLess(idx_print, idx_msg)

    def test_save_writes_to_disk(self):
        x, y = self.s.find('return 42')
        self.s.click(x, y)
        self.s.key(END)
        self.s.type('  # saved')
        self.s.key(CTRL('s'))
        self.assertTrue(self.s.wait_for('Saved hello.py'))
        self.assertIn('return 42  # saved', self.read('hello.py'))
        self.assertNotIn('hello.py*', self.s.screen())     # dirty marker cleared

    def test_indent_selection_with_tab(self):
        x, y = self.s.find('value = 3.14')
        self.s.click(x, y)
        self.s.key(HOME)
        self.s.key(SHIFT_DOWN)
        self.s.key('\t')
        self.assertIn('        value = 3.14', self.s.screen())

    def test_copy_paste(self):
        x, y = self.s.find('return 42')
        self.s.click(x, y)
        self.s.key(CTRL('c'))                  # no selection: copies the line
        self.s.key(END)
        self.s.key(ENTER)
        self.s.key(CTRL('v'))
        self.assertEqual(self.s.screen().count('return 42'), 2)


class TestTerminal(IDETest):
    def test_runs_a_command(self):
        self.s.key(CTRL('j'))
        self.s.type('echo TIDE_OK_123' + ENTER)
        self.assertTrue(self.s.wait_for('TIDE_OK_123'))

    def test_command_output_and_cwd(self):
        self.s.key(CTRL('j'))
        self.s.type('ls' + ENTER)
        self.assertTrue(self.s.wait_for('notes.md'))

    def test_scrollback_with_wheel(self):
        self.s.key(CTRL('j'))
        self.s.type('for i in $(seq 1 40); do echo LINE_$i; done' + ENTER)
        self.assertTrue(self.s.wait_for('LINE_40'))
        self.assertNotIn('LINE_2 ', self.s.screen())      # scrolled off the panel
        term_y = self.s.find('TERMINAL')[1] + 3
        self.s.wheel(50, term_y, up=True, times=4)
        self.assertIn('scrolled', self.s.screen())
        self.assertIn('LINE_2', self.s.screen())          # scrollback is visible
        self.s.wheel(50, term_y, up=False, times=8)
        self.assertIn('LINE_40', self.s.screen())

    def test_ctrl_c_reaches_the_shell(self):
        self.s.key(CTRL('j'))
        self.s.type('sleep 30' + ENTER, settle=0.4)
        self.s.key(CTRL('c'), settle=0.5)
        self.s.type('echo BACK_AGAIN' + ENTER)
        self.assertTrue(self.s.wait_for('BACK_AGAIN'))

    def test_typing_goes_to_editor_after_focus_switch(self):
        self.s.key(CTRL('j'))          # terminal
        self.s.key(F6)                 # -> back around to a pane
        self.s.key(F6)
        screen = self.s.screen()
        self.assertTrue('[tree]' in screen or 'Ln ' in screen)


class TestMouse(IDETest):
    def test_wheel_scrolls_the_editor(self):
        big = os.path.join(self.tmp, 'big.txt')
        with open(big, 'w') as f:
            f.write(''.join('row %d\n' % i for i in range(200)))
        self.s.key(CTRL('p'))
        self.s.type('big.txt')
        self.s.key(ENTER)
        self.assertTrue(self.s.wait_for('row 0'))
        self.s.wheel(60, 5, up=False, times=4)
        self.assertNotIn('row 0 ', self.s.screen())
        self.assertIn('row 12', self.s.screen())

    def test_drag_in_terminal_copies(self):
        self.s.key(CTRL('j'))
        self.s.type('echo COPY_ME_PLEASE' + ENTER)
        self.assertTrue(self.s.wait_for('COPY_ME_PLEASE'))
        # the command output line, not the echoed command line
        y = [y for y, line in enumerate(self.s.text()) if 'COPY_ME_PLEASE' in line][-1]
        x = self.s.line(y).index('COPY_ME_PLEASE')
        self.s.drag(x, y, x + 13, y)
        self.assertIn('Copied 14 chars from terminal', self.s.screen())

    def test_drag_terminal_header_resizes_panel(self):
        header_y = self.s.find('TERMINAL')[1]
        self.s.drag(60, header_y, 60, header_y - 5)
        new_y = self.s.find('TERMINAL')[1]
        self.assertEqual(new_y, header_y - 5)
        self.assertIn('TERMINAL', self.s.screen())

    def test_click_tab_switches_files(self):
        self.s.key(CTRL('p'))
        self.s.type('notes')
        self.s.key(ENTER)
        self.assertTrue(self.s.wait_for('markdown'))
        self.s.click_tab('hello.py')
        self.assertIn('def greet', self.s.screen())

    def test_tab_close_button(self):
        self.s.key(CTRL('p'))
        self.s.type('notes')
        self.s.key(ENTER)
        self.assertTrue(self.s.wait_for('markdown'))
        self.assertIn('notes.md', self.s.line(self.s.TAB_ROW))
        self.s.click_tab_close('notes.md')
        self.assertNotIn('notes.md', self.s.line(self.s.TAB_ROW))
        self.assertIn('def greet', self.s.screen())

    def test_close_button_asks_about_unsaved_work(self):
        self.s.key(CTRL('n'))                      # untitled: auto-save cannot write it
        self.s.type('scratch')
        self.s.click_tab_close('untitled')
        self.assertIn('before closing?', self.s.screen())
        self.s.key('n')
        self.assertNotIn('untitled', self.s.line(self.s.TAB_ROW))

    def test_switch_sits_above_the_tabs(self):
        self.assertIn('Editor', self.s.line(self.s.SWITCH_ROW))
        self.assertIn('Terminals', self.s.line(self.s.SWITCH_ROW))
        self.assertIn('f2 switch', self.s.line(self.s.SWITCH_ROW))
        self.assertIn('hello.py', self.s.line(self.s.TAB_ROW))
        self.assertNotIn('hello.py', self.s.line(self.s.SWITCH_ROW))


class TestAutoSave(IDETest):
    def test_typing_is_written_after_a_pause(self):
        x, y = self.s.find('return 42')
        self.s.click(x, y)
        self.s.key(END)
        self.s.type('  # autosaved')
        self.assertIn('hello.py*', self.s.screen())        # unsaved for a moment
        time.sleep(1.2)
        self.s.pump(0.4)
        self.assertIn('return 42  # autosaved', self.read('hello.py'))
        self.assertNotIn('hello.py*', self.s.screen())     # marker cleared
        self.assertIn('auto-save', self.s.screen())

    def test_further_typing_is_written_too(self):
        x, y = self.s.find('return 42')
        self.s.click(x, y)
        self.s.key(END)
        self.s.type('AAA')
        time.sleep(1.1)
        self.s.pump(0.3)
        self.s.type('BBB')
        time.sleep(1.1)
        self.s.pump(0.3)
        self.assertIn('return 42AAABBB', self.read('hello.py'))

    def test_terminal_sees_the_saved_file(self):
        x, y = self.s.find('return 42')
        self.s.click(x, y)
        self.s.key(END)
        self.s.type('  # from the editor')
        time.sleep(1.2)
        self.s.key(CTRL('j'))
        self.s.type('grep -c "from the editor" hello.py' + ENTER)
        self.assertTrue(self.s.wait_for('1'))

    def test_untitled_buffer_is_not_written(self):
        self.s.key(CTRL('n'))
        self.s.type('scratch text')
        time.sleep(1.2)
        self.s.pump(0.3)
        self.assertIn('untitled*', self.s.screen())        # still unsaved, no crash

    def test_alt_a_turns_it_off(self):
        self.s.key(ALT_A)
        self.assertIn('Auto-save off', self.s.screen())
        x, y = self.s.find('return 42')
        self.s.click(x, y)
        self.s.key(END)
        self.s.type('  # manual only')
        time.sleep(1.2)
        self.s.pump(0.3)
        self.assertNotIn('manual only', self.read('hello.py'))
        self.assertIn('hello.py*', self.s.screen())
        self.s.key(CTRL('s'))
        self.assertTrue(self.s.wait_for('Saved hello.py'))
        self.assertIn('manual only', self.read('hello.py'))


class TestNoAutoSaveFlag(IDETest):
    def setUp(self):
        IDETest.setUp(self)
        self.s.close()
        args = ['--no-autosave', os.path.join(self.tmp, 'hello.py'), self.tmp]
        self.s = Session(args, cols=self.cols, rows=self.rows, cwd=self.tmp)

    def test_dirty_marker_shows_on_the_tab(self):
        x, y = self.s.find('print(msg)')
        self.s.click(x, y)
        self.s.type('# ')
        self.assertIn('hello.py*', self.s.screen())
        self.s.key(CTRL('s'))
        self.assertTrue(self.s.wait_for('Saved hello.py'))
        self.assertNotIn('hello.py*', self.s.screen())

    def test_flag_disables_writing(self):
        self.assertIn('manual save', self.s.screen())
        self.s.type('# ')
        time.sleep(1.2)
        self.s.pump(0.3)
        self.assertNotIn('# def greet', self.read('hello.py'))
        self.assertIn('hello.py*', self.s.screen())

    def test_quit_still_asks(self):
        self.s.type('# ')
        self.s.key(CTRL('q'))
        self.assertIn('before quitting?', self.s.screen())


class TestFullSizeTerminal(IDETest):
    """The terminal that takes over the editor area, with its own sessions."""

    def test_f2_switches_the_main_area(self):
        self.assertIn('def greet', self.s.screen())
        self.s.key(F2)
        self.assertIn('Terminal 1/1', self.s.screen())
        self.assertNotIn('def greet', self.s.screen())
        self.s.type('echo IN_BIG_TERMINAL' + ENTER)
        self.assertTrue(self.s.wait_for('IN_BIG_TERMINAL'))
        self.s.key(F2)
        self.assertIn('def greet', self.s.screen())      # editor is back, untouched
        self.assertIn('Ln 1, Col 1', self.s.screen())

    def test_toggle_chips_are_clickable(self):
        self.s.click_switch('Terminals')
        self.assertIn('Terminal 1/1', self.s.screen())
        self.s.click_switch('Editor')
        self.assertIn('def greet', self.s.screen())

    def test_sessions_are_independent(self):
        self.s.key(F2)
        self.s.type('echo SESSION_ONE' + ENTER)
        self.assertTrue(self.s.wait_for('SESSION_ONE'))
        self.s.key(F4)                                   # a second session
        self.assertIn('Terminal 2/2', self.s.screen())
        self.assertNotIn('SESSION_ONE', self.s.screen())
        self.s.type('echo SESSION_TWO' + ENTER)
        self.assertTrue(self.s.wait_for('SESSION_TWO'))
        self.s.key(ALT_LEFT)                             # back to the first
        self.assertIn('Terminal 1/2', self.s.screen())
        self.assertIn('SESSION_ONE', self.s.screen())
        self.assertNotIn('SESSION_TWO', self.s.screen())
        self.s.key(ALT_RIGHT)
        self.assertIn('SESSION_TWO', self.s.screen())

    def test_separate_from_the_bottom_panel(self):
        self.s.key(F2)
        self.s.type('MARKER=big_only' + ENTER)
        self.s.type('echo "big=[$MARKER]"' + ENTER)
        self.assertTrue(self.s.wait_for('big=[big_only]'))
        self.s.key(CTRL('j'))                            # bottom panel: another shell
        self.s.type('echo "bottom=[$MARKER]"' + ENTER)
        self.assertTrue(self.s.wait_for('bottom=[]'))

    def test_plus_tab_adds_and_close_button_removes(self):
        self.s.key(F2)
        self.s.key(F4)
        self.assertIn('sh 2', self.s.line(self.s.TAB_ROW))
        self.s.click_plus()
        self.assertIn('Terminal 3/3', self.s.screen())
        self.s.click_tab_close('sh 3')                   # the x button
        self.assertIn('Terminal 2/2', self.s.screen())
        self.s.click_tab('sh 2', button=1)               # middle-click still closes
        self.assertIn('Terminal 1/1', self.s.screen())
        self.assertNotIn('sh 2', self.s.line(self.s.TAB_ROW))

    def test_exit_closes_the_session(self):
        self.s.key(F2)
        self.s.key(F4)
        self.s.type('exit' + ENTER, settle=0.7)
        self.assertIn('Terminal 1/1', self.s.screen())
        self.s.type('exit' + ENTER, settle=0.7)
        self.assertIn('def greet', self.s.screen())      # last one closed -> editor
        self.assertNotIn(' sh ', self.s.line(self.s.TAB_ROW))

    def test_hidden_session_keeps_running(self):
        self.s.key(F2)
        self.s.type('(sleep 1; echo WOKE_UP_LATER) &' + ENTER)
        self.s.key(F4)
        self.s.type('echo OTHER' + ENTER)
        self.assertTrue(self.s.wait_for('OTHER'))
        time.sleep(1.2)
        self.s.key(ALT_LEFT)
        self.assertTrue(self.s.wait_for('WOKE_UP_LATER'))

    def test_editor_keeps_its_state_across_switches(self):
        x, y = self.s.find('return 42')
        self.s.click(x, y)
        self.s.key(END)
        self.s.type('0')
        self.s.key(F2)
        self.s.key(F2)
        self.assertIn('return 420', self.s.screen())


class TestScrolling(IDETest):
    """Every window scrolls on its own and remembers where it was."""

    def make_files(self):
        for name in ('long_a.txt', 'long_b.txt'):
            with open(os.path.join(self.tmp, name), 'w') as f:
                for i in range(300):
                    f.write('%s row %d\n' % (name[5], i))

    def editor_top(self):
        """The first real text line the editor is showing."""
        for line in self.s.text()[self.s.BODY_ROW:16]:
            text = line[26:].strip()
            if text and not text.startswith('~'):
                return text
        return ''

    def terminal_rows(self):
        y = self.s.find('TERMINAL')[1]
        return [l[26:].strip() for l in self.s.text()[y + 1:] if l[26:].strip()]

    def open_quick(self, name):
        self.s.key(CTRL('p'))
        self.s.type(name)
        self.s.key(ENTER)
        self.s.pump(0.4)

    def test_editor_tabs_scroll_independently(self):
        self.open_quick('long_a')
        self.s.wheel(60, 6, up=False, times=8)
        a_top = self.editor_top()
        self.open_quick('long_b')
        self.s.wheel(60, 6, up=False, times=3)
        b_top = self.editor_top()
        self.assertNotEqual(a_top, b_top)
        self.s.click_tab('long_a.txt')
        self.assertEqual(self.editor_top(), a_top, 'tab a lost its scroll position')
        self.s.click_tab('long_b.txt')
        self.assertEqual(self.editor_top(), b_top, 'tab b lost its scroll position')

    def test_editor_scroll_survives_a_trip_to_the_terminal_view(self):
        self.open_quick('long_a')
        self.s.wheel(60, 6, up=False, times=6)
        top = self.editor_top()
        self.s.key(F2)
        self.s.pump(0.4)
        self.s.key(F2)
        self.s.pump(0.4)
        self.assertEqual(self.editor_top(), top)

    def test_terminal_stays_put_while_output_arrives(self):
        self.s.key(CTRL('j'))
        self.s.type('for i in $(seq 1 60); do echo TICK_$i; done' + ENTER)
        self.assertTrue(self.s.wait_for('TICK_60'))
        self.s.type('(sleep 1; echo LATE_ONE; echo LATE_TWO) &' + ENTER)
        self.s.pump(0.4)
        y = self.s.find('TERMINAL')[1]
        self.s.wheel(60, y + 3, up=True, times=4)
        before = self.terminal_rows()[:3]
        self.assertIn('scrolled', self.s.screen())
        time.sleep(1.6)
        self.s.pump(0.8)
        self.assertEqual(self.terminal_rows()[:3], before,
                         'background output dragged the view to the bottom')
        self.assertIn('scrolled', self.s.screen())

    def test_typing_returns_the_terminal_to_the_live_end(self):
        self.s.key(CTRL('j'))
        self.s.type('for i in $(seq 1 60); do echo TICK_$i; done' + ENTER)
        self.assertTrue(self.s.wait_for('TICK_60'))
        y = self.s.find('TERMINAL')[1]
        self.s.wheel(60, y + 3, up=True, times=4)
        self.assertIn('scrolled', self.s.screen())
        self.s.type('echo AT_THE_END' + ENTER)
        self.assertTrue(self.s.wait_for('AT_THE_END'))
        self.assertNotIn('scrolled', self.s.screen())

    def test_bottom_terminal_keeps_its_scroll_across_focus_changes(self):
        self.s.key(CTRL('j'))
        self.s.type('for i in $(seq 1 60); do echo TICK_$i; done' + ENTER)
        self.assertTrue(self.s.wait_for('TICK_60'))
        y = self.s.find('TERMINAL')[1]
        self.s.wheel(60, y + 3, up=True, times=4)
        before = self.terminal_rows()[:3]
        self.s.key(F6)                       # focus elsewhere and come back
        self.s.key(F6)
        self.s.key(F6)
        self.assertEqual(self.terminal_rows()[:3], before)

    def test_full_size_sessions_scroll_independently(self):
        self.s.key(F2)
        self.s.type('for i in $(seq 1 60); do echo ONE_$i; done' + ENTER)
        self.assertTrue(self.s.wait_for('ONE_60'))
        self.s.wheel(60, 8, up=True, times=4)
        top = self.s.BODY_ROW
        first = [l[26:].strip() for l in self.s.text()[top:top + 4]]
        self.s.key(F4)                       # a second session, at its own bottom
        self.s.type('for i in $(seq 1 60); do echo TWO_$i; done' + ENTER)
        self.assertTrue(self.s.wait_for('TWO_60'))
        second = [l[26:].strip() for l in self.s.text()[top:top + 4]]
        self.assertNotEqual(first, second)
        self.s.click_tab('sh')
        self.assertEqual([l[26:].strip() for l in self.s.text()[top:top + 4]],
                         first, 'session 1 lost its scrollback position')
        self.s.click_tab('sh 2')
        self.assertEqual([l[26:].strip() for l in self.s.text()[top:top + 4]],
                         second)


class TestScrollbar(IDETest):
    """A scrollbar down the right of the editor - and only the editor."""

    def make_files(self):
        with open(os.path.join(self.tmp, 'long.txt'), 'w') as f:
            for i in range(400):
                f.write('L%d\n' % i)
        with open(os.path.join(self.tmp, 'wide.txt'), 'w') as f:
            f.write(('W' * 300 + '\n') * 200)

    def bar_column(self):
        """Which column the scrollbar is in, whatever the pane is framed with."""
        from tide import theme
        theme.apply('dark', 'modern')
        wanted = (theme.SCROLL_TRACK, theme.SCROLL_THUMB, theme.SCROLL_THUMB_HL)
        top, bottom = self.s.BODY_ROW, self.s.find('TERMINAL')[1] - 2
        best, where = 0, self.cols - 1
        for x in range(self.cols - 1, self.cols - 5, -1):
            marks = sum(1 for y in range(top, bottom)
                        if self.s.cell(x, y)[2] in wanted)
            if marks > best:
                best, where = marks, x
        return where

    def bar(self):
        """The scrollbar column as a picture: # thumb, | track, . nothing.

        Which column it is depends on the appearance - a boxed pane keeps a
        border and a margin to the right of it - so the column is found by
        looking for the track rather than assumed.
        """
        from tide import theme
        theme.apply('dark', 'modern')          # what a session comes up as
        thumbs = (theme.SCROLL_THUMB, theme.SCROLL_THUMB_HL)
        track = theme.SCROLL_TRACK
        top = self.s.BODY_ROW
        bottom = self.s.find('TERMINAL')[1] - (2 if self.s.BOXED else 0)
        x = self.bar_column()
        out = []
        for y in range(top, bottom):
            bg = self.s.cell(x, y)[2]
            out.append('#' if bg in thumbs else ('|' if bg == track else '.'))
        return ''.join(out)

    def open_long(self):
        self.s.key(CTRL('p'))
        self.s.type('long')
        self.s.key(ENTER)
        self.s.pump(0.5)

    def test_long_file_gets_a_bar_and_short_files_do_not(self):
        self.open_long()
        picture = self.bar()
        self.assertIn('#', picture, 'no thumb drawn for a 400 line file')
        self.assertIn('|', picture, 'no track drawn')
        self.s.click_tab('hello.py')         # nine lines: nothing to scroll
        self.assertNotIn('#', self.bar())
        self.assertNotIn('|', self.bar())

    def test_thumb_moves_as_you_scroll(self):
        self.open_long()
        self.assertEqual(self.bar().index('#'), 0, 'thumb should start at the top')
        self.s.wheel(40, 6, up=False, times=20)
        middle = self.bar().index('#')
        self.assertGreater(middle, 0)
        self.s.key(ESC + '[1;5F')            # ctrl+end
        picture = self.bar()
        self.assertEqual(picture.rindex('#'), len(picture.rstrip('.')) - 1,
                         'thumb should reach the bottom')
        self.s.key(ESC + '[1;5H')            # ctrl+home
        self.assertEqual(self.bar().index('#'), 0)

    def test_clicking_the_track_jumps(self):
        self.open_long()
        x = self.bar_column()
        self.s.click(x, self.s.BODY_ROW + 5)
        row = self.s.text()[self.s.BODY_ROW]
        found = [word for word in row.split()
                 if word.startswith('L') and word[1:].isdigit()]
        self.assertTrue(found, 'expected to jump into the file: %r' % row)
        self.assertNotEqual(int(found[0][1:]), 0, 'it did not move')
        self.assertNotEqual(self.bar().index('#'), 0)

    def test_dragging_the_thumb_reaches_both_ends(self):
        self.open_long()
        x = self.bar_column()
        bottom_row = self.s.find('TERMINAL')[1] - (3 if self.s.BOXED else 1)
        top_row = self.s.BODY_ROW
        self.s.drag(x, top_row, x, bottom_row)
        self.assertIn('L391', self.s.screen(), 'drag to the end should show the last lines')
        self.s.drag(x, bottom_row, x, top_row)
        self.assertIn('1 L0', self.s.screen())

    def test_the_bar_does_not_sit_on_the_text(self):
        self.s.key(CTRL('p'))
        self.s.type('wide')
        self.s.key(ENTER)
        self.s.pump(0.5)
        from tide import theme
        theme.apply('dark', 'modern')
        x = self.bar_column()
        self.assertIn(self.s.cell(x, self.s.BODY_ROW)[2],
                      (theme.SCROLL_TRACK, theme.SCROLL_THUMB,
                       theme.SCROLL_THUMB_HL),
                      'the bar column should be the bar')
        self.assertEqual(self.s.cell(x - 1, self.s.BODY_ROW)[0], 'W',
                         'text should run up to the bar')

    def test_no_scrollbar_in_a_full_size_terminal(self):
        self.s.key(F2)
        self.s.type('for i in $(seq 1 200); do echo T_$i; done' + ENTER)
        self.assertTrue(self.s.wait_for('T_200'))
        self.assertNotIn('#', self.bar())
        self.assertNotIn('|', self.bar())


class TestLargeFiles(IDETest):
    def make_files(self):
        with open(os.path.join(self.tmp, 'huge.txt'), 'w') as f:
            for i in range(30000):
                f.write('line %d\n' % i)
        with open(os.path.join(self.tmp, 'blob.bin'), 'wb') as f:
            f.write(bytes(range(256)) * 400)

    def test_a_huge_file_asks_first(self):
        pos = self.s.find('huge.txt')
        self.s.click(pos[0] + 1, pos[1])
        self.assertIn('has 30001 lines', self.s.screen())
        self.s.send_raw('n')
        self.s.pump(0.4)
        self.assertNotIn('huge.txt', self.s.line(self.s.TAB_ROW))

    def test_you_can_still_open_it(self):
        pos = self.s.find('huge.txt')
        self.s.click(pos[0] + 1, pos[1])
        self.s.send_raw('y')
        self.assertTrue(self.s.wait_for('huge.txt  x'))
        self.assertIn('1 line 0', self.s.screen())

    def test_a_binary_file_asks_and_opens_read_only(self):
        pos = self.s.find('blob.bin')
        self.s.click(pos[0] + 1, pos[1])
        self.assertIn('looks like a binary file', self.s.screen())
        self.s.send_raw('y')
        self.s.pump(0.8)
        self.assertIn('READ-ONLY', self.s.screen())

    def test_a_normal_file_opens_without_a_question(self):
        pos = self.s.find('notes.md')
        self.s.click(pos[0] + 1, pos[1])
        self.assertTrue(self.s.wait_for('Some *markdown* text.'))
        self.assertNotIn('Open anyway', self.s.screen())


class TestNavigation(IDETest):
    def test_quick_open(self):
        self.s.key(CTRL('p'))
        self.s.type('notes')
        self.s.key(ENTER)
        self.assertTrue(self.s.wait_for('Some *markdown* text.'))
        self.assertIn('Markdown', self.s.screen())

    def test_tree_click_opens_file(self):
        pos = self.s.find('notes.md')
        self.s.click(pos[0] + 1, pos[1])
        self.assertTrue(self.s.wait_for('Some *markdown* text.'))

    def test_find_highlights_and_jumps(self):
        self.s.key(CTRL('f'))
        self.s.type('msg')
        self.assertIn('matches', self.s.screen())
        self.s.key(ENTER)
        self.s.key(ESCAPE)
        self.assertIn('Ln ', self.s.screen())

    def test_goto_line(self):
        self.s.key(CTRL('g'))
        self.s.type('8' + ENTER)
        self.assertIn('Ln 8, Col 1', self.s.screen())

    def test_new_tab_and_close(self):
        self.s.key(CTRL('n'))
        self.assertIn('untitled', self.s.screen())
        self.s.key(CTRL('w'))
        self.assertNotIn('untitled', self.s.screen())

    def test_quit_without_changes(self):
        self.s.key(CTRL('q'), settle=0.5)
        time.sleep(0.4)
        self.assertFalse(self.s.alive())

    def test_quit_with_changes_asks(self):
        self.s.key(CTRL('n'))                 # an untitled buffer auto-save cannot write
        self.s.type('x')
        self.s.key(CTRL('q'))
        self.assertIn('before quitting?', self.s.screen())
        self.s.key('n', settle=0.5)
        time.sleep(0.4)
        self.assertFalse(self.s.alive())


if __name__ == '__main__':
    unittest.main(verbosity=2)
