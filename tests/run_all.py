#!/usr/bin/env python3
"""Run every test: unit tests first, then the pty end-to-end suite."""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

if __name__ == '__main__':
    loader = unittest.TestLoader()
    suite = unittest.TestSuite([
        loader.discover(HERE, pattern='test_units.py'),
        loader.discover(HERE, pattern='test_saving.py'),
        loader.discover(HERE, pattern='test_history.py'),
        loader.discover(HERE, pattern='test_parity.py'),
        loader.discover(HERE, pattern='test_sync.py'),
        loader.discover(HERE, pattern='test_workflows.py'),
        loader.discover(HERE, pattern='test_filesystem.py'),
        loader.discover(HERE, pattern='test_git.py'),
        loader.discover(HERE, pattern='test_diff.py'),
        loader.discover(HERE, pattern='test_split.py'),
        loader.discover(HERE, pattern='test_chrome.py'),
        loader.discover(HERE, pattern='test_panes.py'),
        loader.discover(HERE, pattern='test_names.py'),
        loader.discover(HERE, pattern='test_review.py'),
        loader.discover(HERE, pattern='test_appearance.py'),
        loader.discover(HERE, pattern='test_audio.py'),
        loader.discover(HERE, pattern='test_update.py'),
        loader.discover(HERE, pattern='test_sessions.py'),
        loader.discover(HERE, pattern='test_settings.py'),
        loader.discover(HERE, pattern='test_e2e.py'),
        loader.discover(HERE, pattern='test_watch.py'),
        loader.discover(HERE, pattern='test_durability.py'),
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
