"""Investigation store."""
import uuid
import json
import redis.asyncio as redis

from app.domain import Investigation, CaseFile


class InvestigationStore:
    """Redis registry of all running investigations, keyed by id.

    State lives in this process only: it is lost on restart and not shared
    between replicas. Fine for one pod; with several, use an external
    store such as Redis.
    """

    def __init__(self, r: redis.Redis, case_file: CaseFile):
        """Creates an empty store."""
        self._r = r
        self._case_file = case_file

    async def add(self, investigation: Investigation) -> str:
        """Stores an investigation under a new random id.

        Args:
            investigation: The investigation to store.

        Returns:
            The new id, 12 hex characters.
        """
        investigation_id = uuid.uuid4().hex[:12]
        await self._r.set(self._key(investigation_id), json.dumps(investigation.to_dict()))
        return investigation_id

    async def get(self, investigation_id: str) -> Investigation | None:
        """Looks up an investigation by id.

        Args:
            investigation_id: The id returned by ``add``.

        Returns:
            The investigation, or None if the id is unknown.
        """
        raw = await self._r.get(self._key(investigation_id))
        return Investigation.from_dict(json.loads(raw), self._case_file) if raw else None

    async def save(self, investigation_id: str, investigation: Investigation) -> None:
        """Store an investigation into the Redis store.

        Args:
            investigation_id: Unique identifier of the investigation to store.
            investigation: Investigation data.
        """
        await self._r.set(self._key(investigation_id), json.dumps(investigation.to_dict()))

    async def delete(self, investigation_id: str) -> bool:
        """Removes an investigation.

        Args:
            investigation_id: The id returned by ``add``.

        Returns:
            True if it existed and was removed, False if the id was unknown.
        """
        deleted_keys = await self._r.delete(self._key(investigation_id))
        return bool(deleted_keys)

    @staticmethod
    def _key(inv_id: str):
        return f"investigation:{inv_id}"
