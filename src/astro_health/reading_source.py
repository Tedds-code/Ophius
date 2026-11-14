
# Made in cooperation with ChatGPT
# File: src/astro_health/reading_source.py

from abc import ABC, abstractmethod

from astro_health.models import Reading


class ReadingSource(ABC):
    """Common interface for sources of health readings."""

    @abstractmethod
    def read(self) -> Reading:
        """
        Obtain one reading from any source.
        Subclasses must implement this method, and return a Reading object
        """
        pass
