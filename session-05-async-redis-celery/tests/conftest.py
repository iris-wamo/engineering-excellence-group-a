"""Shared pytest setup.

Settings require JWT_SECRET_KEY; give the test run a fixed one before any
``app`` module is imported, unless the environment already provides one.
"""

import os

os.environ.setdefault(
    "JWT_SECRET_KEY", "test-only-jwt-secret-key-not-for-production-use-0123456789"
)
