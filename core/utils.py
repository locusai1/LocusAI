# core/utils.py — Shared utility functions for AxisAI
# Re-exports from validators for backward compatibility

from core.validators import slugify, safe_int, validate_email, validate_phone

# Re-export for backward compatibility
__all__ = ['slugify', 'safe_int', 'validate_email', 'validate_phone']
