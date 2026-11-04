"""Regel-Engine Modul."""
from .base import Rule, RuleRegistry, registry  # noqa: F401

# Import side-effect: registriert alle Regeln
from . import completeness  # noqa: F401
from . import uniqueness    # noqa: F401
from . import validity      # noqa: F401
from . import consistency   # noqa: F401
from . import referential   # noqa: F401
from . import temporal      # noqa: F401
from . import anomaly       # noqa: F401
