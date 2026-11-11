"""Home Assistant lifecycle entry points for Orvibo Local."""

from .runtime.lifecycle import async_migrate_entry as async_migrate_entry
from .runtime.lifecycle import async_setup_entry as async_setup_entry
from .runtime.lifecycle import async_unload_entry as async_unload_entry
