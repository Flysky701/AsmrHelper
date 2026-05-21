"""Core configuration domain.

Provides a thin wrapper over the top-level src.config module,
establishing the canonical core-layer entry point for configuration
access. This allows service-layer code to import from src.core.config
rather than directly from the top-level src.config module.
"""

from __future__ import annotations

from src.config import Config, config

__all__ = [
    "Config",
    "ConfigManager",
    "config",
    "get_config",
]


# Alias for clarity in core-layer usage
ConfigManager = Config


def get_config() -> Config:
    """Get the global Config singleton."""
    return config
