#!/usr/bin/env python3
"""Run the IDE: python3 main.py [files or directory]"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tide.cli import main  # noqa: E402

if __name__ == '__main__':
    sys.exit(main())
