"""Minimal account service with password hashing and opaque server sessions."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
import secrets
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from .db.database import Database
from .db.models import AccountSession, Role, User, UserRole
from .models import AccountProfile


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    work_factor, block_size, parallelism = 2**14, 8, 1
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=work_factor,
        r=block_size,
        p=parallelism,
        dklen=32,
    )
    return f"scrypt${work_factor}${block_size}${parallelism}${_b64(salt)}${_b64(derived)}"


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    try:
        algorithm, work, block, parallel, salt, expected = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_unb64(salt),
            n=int(work),
            r=int(block),
            p=int(parallel),
            dklen=32,
        )
        return hmac.compare_digest(actual, _unb64(expected))
    except (ValueError, TypeError):
        return False


def new_recovery_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    raw = "".join(secrets.choice(alphabet) for _ in range(16))
    return "-".join(raw[index:index + 4] for index in range(0, 16, 4))


def recovery_digest(value: str) -> str:
    return _digest(value.replace("-", "").replace(" ", "").upper())


@dataclass(frozen=True, slots=True)
class AccountRecord:
    id: UUID
    email: str
    display_name: str
    password_hash: str
    recovery_code_hash: str
    roles: tuple[str, ...]
    created_at: datetime

    def public(self) -> AccountProfile:
        return AccountProfile(
            id=self.id,
            email=self.email,
            display_name=self.display_name,
            roles=list(self.roles),
            created_at=self.created_at,
        )


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    account: AccountRecord
    csrf_token_hash: str
    expires_at: datetime


class AccountRepository(Protocol):
    def create_user(self, email: str, display_name: str, password_hash: str, recovery_code_hash: str) -> AccountRecord: ...
    def get_by_email(self, email: str) -> AccountRecord | None: ...
    def get_by_id(self, user_id: UUID) -> AccountRecord | None: ...
    def create_session(self, user_id: UUID, token_hash: str, csrf_token_hash: str, expires_at: datetime) -> None: ...
    def authenticate(self, token_hash: str) -> AuthenticatedSession | None: ...
    def revoke_session(self, token_hash: str) -> None: ...
    def replace_password(self, user_id: UUID, password_hash: str, recovery_code_hash: str) -> None: ...
    def delete_user(self, user_id: UUID) -> None: ...
    def ping(self) -> bool: ...


class InMemoryAccountRepository:
    def __init__(self) -> None:
        self._users: dict[UUID, AccountRecord] = {}
        self._emails: dict[str, UUID] = {}
        self._sessions: dict[str, tuple[UUID, str, datetime]] = {}

    def create_user(self, email: str, display_name: str, password_hash: str, recovery_code_hash: str) -> AccountRecord:
        if email in self._emails:
            raise ValueError("email_already_registered")
        record = AccountRecord(uuid4(), email, display_name, password_hash, recovery_code_hash, ("participant", "reviewer"), _utc_now())
        self._users[record.id] = record
        self._emails[email] = record.id
        return record

    def get_by_email(self, email: str) -> AccountRecord | None:
        user_id = self._emails.get(email)
        return self._users.get(user_id) if user_id else None

    def get_by_id(self, user_id: UUID) -> AccountRecord | None:
        return self._users.get(user_id)

    def create_session(self, user_id: UUID, token_hash: str, csrf_token_hash: str, expires_at: datetime) -> None:
        self._sessions[token_hash] = (user_id, csrf_token_hash, expires_at)

    def authenticate(self, token_hash: str) -> AuthenticatedSession | None:
        item = self._sessions.get(token_hash)
        if item is None:
            return None
        user_id, csrf_hash, expires_at = item
        if _as_utc(expires_at) <= _utc_now():
            self._sessions.pop(token_hash, None)
            return None
        account = self._users.get(user_id)
        return AuthenticatedSession(account, csrf_hash, expires_at) if account else None

    def revoke_session(self, token_hash: str) -> None:
        self._sessions.pop(token_hash, None)

    def replace_password(self, user_id: UUID, password_hash: str, recovery_code_hash: str) -> None:
        current = self._users[user_id]
        self._users[user_id] = AccountRecord(current.id, current.email, current.display_name, password_hash, recovery_code_hash, current.roles, current.created_at)
        self._sessions = {key: value for key, value in self._sessions.items() if value[0] != user_id}

    def delete_user(self, user_id: UUID) -> None:
        current = self._users.pop(user_id, None)
        if current:
            self._emails.pop(current.email, None)
        self._sessions = {key: value for key, value in self._sessions.items() if value[0] != user_id}

    def ping(self) -> bool:
        return True


class SqlAlchemyAccountRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    @staticmethod
    def _record(row: User) -> AccountRecord:
        return AccountRecord(
            id=UUID(row.id),
            email=row.email or "",
            display_name=row.display_name,
            password_hash=row.password_hash or "",
            recovery_code_hash=row.recovery_code_hash or "",
            roles=tuple(sorted(link.role_id for link in row.roles)),
            created_at=_as_utc(row.created_at),
        )

    def create_user(self, email: str, display_name: str, password_hash: str, recovery_code_hash: str) -> AccountRecord:
        user_id = uuid4()
        try:
            with self._database.session_factory.begin() as db:
                for role_id, name in (("participant", "Участник"), ("reviewer", "Рецензент")):
                    if db.get(Role, role_id) is None:
                        db.add(Role(id=role_id, name=name))
                row = User(id=str(user_id), email=email, display_name=display_name, password_hash=password_hash, recovery_code_hash=recovery_code_hash)
                db.add(row)
                db.flush()
                db.add_all([UserRole(user_id=str(user_id), role_id="participant"), UserRole(user_id=str(user_id), role_id="reviewer")])
        except IntegrityError as error:
            raise ValueError("email_already_registered") from error
        record = self.get_by_id(user_id)
        if record is None:
            raise RuntimeError("account_creation_failed")
        return record

    def _find(self, criterion) -> AccountRecord | None:
        with self._database.session_factory() as db:
            row = db.scalar(select(User).where(criterion).options(selectinload(User.roles)))
            return self._record(row) if row is not None and row.password_hash else None

    def get_by_email(self, email: str) -> AccountRecord | None:
        return self._find(User.email == email)

    def get_by_id(self, user_id: UUID) -> AccountRecord | None:
        return self._find(User.id == str(user_id))

    def create_session(self, user_id: UUID, token_hash: str, csrf_token_hash: str, expires_at: datetime) -> None:
        with self._database.session_factory.begin() as db:
            db.add(AccountSession(user_id=str(user_id), token_hash=token_hash, csrf_token_hash=csrf_token_hash, expires_at=expires_at, last_seen_at=_utc_now()))

    def authenticate(self, token_hash: str) -> AuthenticatedSession | None:
        with self._database.session_factory.begin() as db:
            row = db.scalar(
                select(AccountSession)
                .where(AccountSession.token_hash == token_hash)
                .options(selectinload(AccountSession.user).selectinload(User.roles))
            )
            if row is None:
                return None
            if _as_utc(row.expires_at) <= _utc_now():
                db.delete(row)
                return None
            row.last_seen_at = _utc_now()
            account = self._record(row.user)
            return AuthenticatedSession(account, row.csrf_token_hash, _as_utc(row.expires_at))

    def revoke_session(self, token_hash: str) -> None:
        with self._database.session_factory.begin() as db:
            db.execute(delete(AccountSession).where(AccountSession.token_hash == token_hash))

    def replace_password(self, user_id: UUID, password_hash: str, recovery_code_hash: str) -> None:
        with self._database.session_factory.begin() as db:
            row = db.get(User, str(user_id))
            if row is None:
                raise KeyError("account_not_found")
            row.password_hash = password_hash
            row.recovery_code_hash = recovery_code_hash
            db.execute(delete(AccountSession).where(AccountSession.user_id == str(user_id)))

    def delete_user(self, user_id: UUID) -> None:
        with self._database.session_factory.begin() as db:
            row = db.get(User, str(user_id))
            if row is not None:
                db.delete(row)

    def ping(self) -> bool:
        return True


class AccountService:
    def __init__(self, repository: AccountRepository, session_days: int | None = None) -> None:
        self.repository = repository
        self.session_days = session_days or max(1, min(90, int(os.getenv("AUTH_SESSION_DAYS", "30"))))

    def register(self, email: str, display_name: str, password: str) -> tuple[AccountRecord, str, str, str]:
        recovery = new_recovery_code()
        account = self.repository.create_user(email, display_name, hash_password(password), recovery_digest(recovery))
        token, csrf = self._new_session(account.id)
        return account, token, csrf, recovery

    def login(self, email: str, password: str) -> tuple[AccountRecord, str, str]:
        account = self.repository.get_by_email(email)
        if account is None or not verify_password(password, account.password_hash):
            raise ValueError("invalid_credentials")
        token, csrf = self._new_session(account.id)
        return account, token, csrf

    def authenticate(self, token: str | None) -> AuthenticatedSession | None:
        return self.repository.authenticate(_digest(token)) if token else None

    def logout(self, token: str | None) -> None:
        if token:
            self.repository.revoke_session(_digest(token))

    def recover(self, email: str, code: str, new_password: str) -> str:
        account = self.repository.get_by_email(email)
        supplied = recovery_digest(code)
        if account is None or not hmac.compare_digest(supplied, account.recovery_code_hash):
            raise ValueError("invalid_recovery_code")
        replacement = new_recovery_code()
        self.repository.replace_password(account.id, hash_password(new_password), recovery_digest(replacement))
        return replacement

    def _new_session(self, user_id: UUID) -> tuple[str, str]:
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(24)
        self.repository.create_session(user_id, _digest(token), _digest(csrf), _utc_now() + timedelta(days=self.session_days))
        return token, csrf


def verify_csrf(header: str | None, cookie: str | None, expected_hash: str) -> bool:
    return bool(header and cookie and hmac.compare_digest(header, cookie) and hmac.compare_digest(_digest(header), expected_hash))
