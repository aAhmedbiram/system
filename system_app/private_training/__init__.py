"""Private Training domain package."""

from .permissions import (
    PRIVATE_TRAINING_MANAGE,
    PRIVATE_TRAINING_TRAINER,
    PRIVATE_TRAINING_VIEW,
)
from .queries import ensure_private_training_tables
