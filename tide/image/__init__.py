"""Images, kept in their own corner.

Importing this costs a set literal: the decoder and the view are pulled in
only when an image is actually opened. Nothing here needs anything outside
the standard library, so an image opens the same way on every machine tide
runs on - including one at the far end of an ssh connection, where installing
a viewer is not an option.
"""

import os

EXTENSIONS = {'.png'}


def is_image(path):
    return os.path.splitext(path or '')[1].lower() in EXTENSIONS


def open_view(app, path):
    """An image tab for this file.

    Named so it cannot collide with the `view` submodule it imports.
    """
    from .view import ImageView
    return ImageView(app, path)
