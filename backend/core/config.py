"""Backend compatibility facade for the canonical Smart Port configuration."""
from smart_port.config import Settings, settings

# Preserve the historic type name for external callers while keeping one source
# of truth for every SMART_PORT_* setting.
BackendSettings = Settings

__all__ = ["BackendSettings", "Settings", "settings"]
