"""Investigation store."""
import uuid
import redis.asyncio as redis

from app.domain import Investigation, CaseFile


class InvestigationStore:
    """In-memory registry of all running investigations, keyed by id.

    State lives in this process only: it is lost on restart and not shared
    between replicas. Fine for one pod; with several, use an external
    store such as Redis.
    """

    def __init__(self, r: redis.Redis, case_file: CaseFile):
        """Creates an empty store."""
        self._r = r
        self._case_file = case_file
        # self._items: dict[str, Investigation] = {}

    async def add(self, investigation: Investigation) -> str:
        """Stores an investigation under a new random id.

        Args:
            investigation: The investigation to store.

        Returns:
            The new id, 12 hex characters.
        """
        investigation_id = uuid.uuid4().hex[:12]
        await self._r.set(f"investigation:{investigation_id}", investigation.to_dict())
        return investigation_id

    async def get(self, investigation_id: str) -> Investigation | None:
        """Looks up an investigation by id.

        Args:
            investigation_id: The id returned by ``add``.

        Returns:
            The investigation, or None if the id is unknown.
        """
        raw = await self._r.get(f"investigation:{investigation_id}")
        return Investigation.from_dict(raw, self._case_file) if raw else None

    async def delete(self, investigation_id: str) -> bool:
        """Removes an investigation.

        Args:
            investigation_id: The id returned by ``add``.

        Returns:
            True if it existed and was removed, False if the id was unknown.
        """
        deleted_keys = await self._r.delete(f"investigation:{investigation_id}")
        return bool(deleted_keys)
