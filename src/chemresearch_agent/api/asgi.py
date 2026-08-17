"""Explicit ASGI entrypoint.

Keeping application construction here prevents imports of ``api.app`` from
creating runtime data directories as a side effect.
"""

from .app import create_app

app = create_app()
