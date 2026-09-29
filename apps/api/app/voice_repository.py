from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import delete, select

from .db.database import Database
from .db.models import VoiceRecording


@dataclass(frozen=True, slots=True)
class VoiceRecordingRecord:
    id: UUID
    session_id: UUID
    message_id: UUID
    owner_user_id: UUID | None
    mime_type: str
    audio_data: bytes
    duration_ms: int
    transcript: str
    pause_count: int
    longest_pause_ms: int
    speaking_rate_wpm: int
    interruption_count: int
    retention_policy: str
    consent_version: str
    consented_at: datetime
    expires_at: datetime
    created_at: datetime


class VoiceRecordingRepository(Protocol):
    def create(self, record: VoiceRecordingRecord) -> VoiceRecordingRecord: ...
    def list_for_session(self, session_id: UUID) -> tuple[VoiceRecordingRecord, ...]: ...
    def get(self, recording_id: UUID) -> VoiceRecordingRecord | None: ...
    def delete(self, recording_id: UUID) -> bool: ...
    def purge_expired(self, now: datetime | None = None) -> int: ...


class InMemoryVoiceRecordingRepository:
    def __init__(self) -> None:
        self._records: dict[UUID, VoiceRecordingRecord] = {}

    def create(self, record: VoiceRecordingRecord) -> VoiceRecordingRecord:
        if any(item.message_id == record.message_id for item in self._records.values()):
            raise ValueError("voice_recording_already_exists")
        self._records[record.id] = record
        return record

    def list_for_session(self, session_id: UUID) -> tuple[VoiceRecordingRecord, ...]:
        self.purge_expired()
        return tuple(item for item in self._records.values() if item.session_id == session_id)

    def get(self, recording_id: UUID) -> VoiceRecordingRecord | None:
        self.purge_expired()
        return self._records.get(recording_id)

    def delete(self, recording_id: UUID) -> bool:
        return self._records.pop(recording_id, None) is not None

    def purge_expired(self, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        expired = [key for key, value in self._records.items() if value.expires_at <= now]
        for key in expired:
            self._records.pop(key, None)
        return len(expired)


class SqlAlchemyVoiceRecordingRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def create(self, record: VoiceRecordingRecord) -> VoiceRecordingRecord:
        with self._database.session_factory.begin() as db:
            if db.scalar(select(VoiceRecording.id).where(VoiceRecording.message_id == str(record.message_id))) is not None:
                raise ValueError("voice_recording_already_exists")
            db.add(VoiceRecording(
                id=str(record.id), session_id=str(record.session_id), message_id=str(record.message_id),
                owner_user_id=str(record.owner_user_id) if record.owner_user_id else None,
                mime_type=record.mime_type, audio_data=record.audio_data, byte_size=len(record.audio_data),
                duration_ms=record.duration_ms, transcript=record.transcript,
                pause_count=record.pause_count, longest_pause_ms=record.longest_pause_ms,
                speaking_rate_wpm=record.speaking_rate_wpm, interruption_count=record.interruption_count,
                retention_policy=record.retention_policy, consent_version=record.consent_version,
                consented_at=record.consented_at, expires_at=record.expires_at, created_at=record.created_at,
            ))
        return record

    def list_for_session(self, session_id: UUID) -> tuple[VoiceRecordingRecord, ...]:
        self.purge_expired()
        with self._database.session_factory() as db:
            rows = db.scalars(select(VoiceRecording).where(
                VoiceRecording.session_id == str(session_id)
            ).order_by(VoiceRecording.created_at)).all()
            return tuple(self._to_record(row) for row in rows)

    def get(self, recording_id: UUID) -> VoiceRecordingRecord | None:
        self.purge_expired()
        with self._database.session_factory() as db:
            row = db.get(VoiceRecording, str(recording_id))
            return self._to_record(row) if row is not None else None

    def delete(self, recording_id: UUID) -> bool:
        with self._database.session_factory.begin() as db:
            result = db.execute(delete(VoiceRecording).where(VoiceRecording.id == str(recording_id)))
            return bool(result.rowcount)

    def purge_expired(self, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        with self._database.session_factory.begin() as db:
            result = db.execute(delete(VoiceRecording).where(VoiceRecording.expires_at <= now))
            return int(result.rowcount or 0)

    @staticmethod
    def _to_record(row: VoiceRecording) -> VoiceRecordingRecord:
        return VoiceRecordingRecord(
            id=UUID(row.id), session_id=UUID(row.session_id), message_id=UUID(row.message_id),
            owner_user_id=UUID(row.owner_user_id) if row.owner_user_id else None,
            mime_type=row.mime_type, audio_data=row.audio_data, duration_ms=row.duration_ms,
            transcript=row.transcript, pause_count=row.pause_count,
            longest_pause_ms=row.longest_pause_ms, speaking_rate_wpm=row.speaking_rate_wpm,
            interruption_count=row.interruption_count, retention_policy=row.retention_policy,
            consent_version=row.consent_version, consented_at=row.consented_at,
            expires_at=row.expires_at, created_at=row.created_at,
        )


def new_voice_recording(**values: object) -> VoiceRecordingRecord:
    now = datetime.now(timezone.utc)
    return VoiceRecordingRecord(id=uuid4(), created_at=now, consented_at=now, **values)  # type: ignore[arg-type]
