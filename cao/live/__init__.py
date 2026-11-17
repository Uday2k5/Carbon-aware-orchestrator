"""Live demo pipeline: real grid data -> forecast -> hourly scheduling twin -> dashboard JSON."""
from .pipeline import tick

__all__ = ["tick"]
