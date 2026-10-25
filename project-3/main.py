"""Vercel entrypoint for the Nexus API service (see vercel.json)."""

from nexus.api.app import app

__all__ = ["app"]
