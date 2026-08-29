"""Named sessions: the store, the two menu items, and the CLI commands."""

import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class SessionTest(unittest.TestCase):
    def setUp(self):
        self.cfg = tempfile.mkdtemp()
        os.environ['TIDE_CONFIG_HOME'] = self.cfg
        self.tmp = tempfile.mkdtemp()
        for name in ('a.py', 'b.py'):
            with open(os.path.join(self.tmp, name), 'w') as f:
                f.write('x = 1\n')

    def tearDown(self):
        os.environ.pop('TIDE_CONFIG_HOME', None)
        shutil.rmtree(self.cfg, ignore_errors=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def app(self):
        from tide.app import App
        from tide.term import Screen
        app = App(root=self.tmp, paths=[], out=io.StringIO())
        app.screen = Screen(100, 26)
        for name in ('a.py', 'b.py'):
            app.open_file(os.path.join(self.tmp, name))
        app.render()
        return app

    @staticmethod
    def answer(app, text):
        from tide.keys import Key
        for ch in text:
            app.handle_key(Key('char', char=ch))
        app.handle_key(Key('enter'))


class TestTheStore(SessionTest):
    def test_a_name_has_to_be_one(self):
        from tide import sessions
        self.assertTrue(sessions.why_not(''))
        self.assertTrue(sessions.why_not('two words'))
        self.assertTrue(sessions.why_not('../escape'))
        self.assertEqual(sessions.why_not('work-1.2'), '')

    def test_what_is_open_is_what_comes_back(self):
        from tide import sessions
        app = self.app()
        app.split = True
        app.show_term = False
        app.name_session()
        self.answer(app, 'work')
        stored = sessions.load('work')
        self.assertEqual([os.path.basename(f) for f in stored['files']],
                         ['a.py', 'b.py'])
        self.assertEqual(stored['root'], self.tmp)
        self.assertTrue(stored['split'])
        self.assertFalse(stored['show_term'])

    def test_a_session_is_only_open_in_one_place(self):
        from tide import sessions
        sessions.save('work', {'root': self.tmp, 'files': []})
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        try:
            with open(os.path.join(sessions.folder(), 'work.lock'), 'w') as f:
                import socket
                f.write('%d %s' % (child.pid, socket.gethostname()))
            self.assertIn('another tide', sessions.busy('work'))
        finally:
            child.kill()
            child.wait()
        self.assertEqual(sessions.busy('work'), '',
                         'the lock outlived the tide that held it')


class TestTheMenuItems(SessionTest):
    def items(self, app):
        return dict((item[0].strip(), item[2]) for item in app.menu_items('Tide')
                    if item)

    def test_save_is_offered_and_rename_is_not(self):
        items = self.items(self.app())
        self.assertIsNotNone(items['Save to named session...'])
        self.assertIsNone(items['Rename session...'], 'rename was not greyed out')

    def test_once_named_it_is_the_other_way_round(self):
        app = self.app()
        app.name_session()
        self.answer(app, 'work')
        items = self.items(app)
        self.assertIsNone(items['Save to named session...'])
        self.assertIsNotNone(items['Rename session...'])

    def test_a_name_already_taken_is_refused(self):
        from tide import sessions
        sessions.save('taken', {'root': self.tmp, 'files': []})
        app = self.app()
        app.name_session()
        self.answer(app, 'taken')
        self.assertIsNotNone(app.overlay, 'the box closed on a bad name')
        self.assertIn('already', app.overlay.info)
        self.assertIsNone(app.session)

    def test_renaming_moves_the_session(self):
        from tide import sessions
        app = self.app()
        app.name_session()
        self.answer(app, 'work')
        app.rename_session()
        app.overlay.text = ''            # as select-all-and-type would
        self.answer(app, 'later')
        self.assertEqual(app.session, 'later')
        self.assertEqual(sessions.names(), ['later'])


class TestFromTheTerminal(SessionTest):
    def run_tide(self, args, stdin=''):
        env = dict(os.environ, TIDE_CONFIG_HOME=self.cfg, PYTHONPATH=ROOT)
        done = subprocess.run([sys.executable, '-m', 'tide'] + args, env=env,
                              input=stdin, capture_output=True, text=True)
        return done.returncode, done.stdout + done.stderr

    def test_listing_and_forgetting(self):
        from tide import sessions
        sessions.save('work', {'root': self.tmp, 'files': []})
        code, out = self.run_tide(['--list-sessions'])
        self.assertEqual(code, 0)
        self.assertIn('work', out)
        self.assertIn(self.tmp, out)
        code, out = self.run_tide(['--remove-session', 'work'], stdin='n\n')
        self.assertEqual(sessions.names(), ['work'], 'it went without a yes')
        self.run_tide(['--remove-session', 'work'], stdin='y\n')
        self.assertEqual(sessions.names(), [])

    def test_it_says_so_when_there_is_no_such_session(self):
        code, out = self.run_tide(['--resume', 'ghost'])
        self.assertEqual(code, 1)
        self.assertIn('no session called ghost', out)

    def test_a_new_session_will_not_take_a_name_that_is_taken(self):
        from tide import sessions
        sessions.save('work', {'root': self.tmp, 'files': []})
        code, out = self.run_tide(['--new-session', 'work'])
        self.assertEqual(code, 1)
        self.assertIn('already', out)


if __name__ == '__main__':
    unittest.main()
