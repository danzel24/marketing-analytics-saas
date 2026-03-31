"""Pytest bootstrap: required env for crypto and JWT."""

import os

# Tests must not rely on a dev machine secret; CI/local runs stay deterministic.
os.environ.setdefault("JWT_SECRET", "pytest-jwt-secret-key-minimum-32-chars!!")
