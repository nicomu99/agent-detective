"""Investigation store."""
import uuid

from app.domain import Investigation


class InvestigationStore:
    """In-memory registry of all running investigations, keyed by id.

    State lives in this process only: it is lost on restart and not shared
    between replicas. Fine for one pod; with several, use an external
    store such as Redis.
    """

    def __init__(self):
        """Creates an empty store."""
        self._items: dict[str, Investigation] = {}

    def add(self, investigation: Investigation) -> str:
        """Stores an investigation under a new random id.

        Args:
            investigation: The investigation to store.

        Returns:
            The new id, 12 hex characters.
        """
        investigation_id = uuid.uuid4().hex[:12]
        self._items[investigation_id] = investigation
        return investigation_id

    def get(self, investigation_id: str) -> Investigation | None:
        """Looks up an investigation by id.

        Args:
            investigation_id: The id returned by ``add``.

        Returns:
            The investigation, or None if the id is unknown.
        """
        return self._items.get(investigation_id)

    def delete(self, investigation_id: str) -> bool:
        """Removes an investigation.

        Args:
            investigation_id: The id returned by ``add``.

        Returns:
            True if it existed and was removed, False if the id was unknown.
        """
        return self._items.pop(investigation_id, None) is not None
