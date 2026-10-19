"""Logging utilities."""
import logging


def setup_logging(level: str = "INFO") -> None:
    """Configures the root logger once for the whole application.

    Args:
        level: The logging level. Defaults to "INFO".
    """
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
