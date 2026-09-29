"""Opt-in practice motivation derived from server-owned learning evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as CalendarDate, datetime, timedelta, timezone
import hashlib
import re
import secrets
from statistics import mean
from typing import Literal, Protocol
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from .db.database import Database
from .db.models import MotivationChallengeEntry, MotivationPreference, MotivationTeam
from .learning import SKILLS, _attempt_scores
from .models import NegotiationSession, ReportResponse, SessionStatus
from .peer_repository import PeerReviewRepository
from .repository import SessionRepository
from .scenario_catalog import ScenarioCatalog
from .services import create_session, default_session_configuration


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


class MotivationPreferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool
    team_opt_in: bool = False
    timezone: str = Field(default="UTC", min_length=1, max_length=64)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("unknown_timezone") from None
        return value


class CreateMotivationTeamRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=80)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 2:
            raise ValueError("team_name_required")
        return value


class JoinMotivationTeamRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invite_code: str = Field(min_length=16, max_length=20)


class StreakView(BaseModel):
    current: int
    longest: int
    last_practiced_on: CalendarDate | None


class SkillTreeNode(BaseModel):
    id: str
    title: str
    level: int
    unlocked: bool
    unlock_reason: str
    next_requirement: str


class AchievementView(BaseModel):
    id: str
    title: str
    description: str
    earned_at: datetime


class ChallengeView(BaseModel):
    date: CalendarDate | None = None
    week_start: CalendarDate | None = None
    scenario_id: str
    scenario_title: str
    seed: int
    skill_id: str
    completed: bool
    session_id: UUID | None = None


class MotivationTeamView(BaseModel):
    id: UUID
    name: str
    invite_code: str
    members: int


class LeaderboardItem(BaseModel):
    rank: int
    team_id: UUID
    team_name: str
    members: int
    points: int
    completed_sessions: int


class MotivationDashboard(BaseModel):
    enabled: bool
    team_opt_in: bool
    timezone: str
    streak: StreakView
    skill_tree: list[SkillTreeNode]
    achievements: list[AchievementView]
    daily_challenge: ChallengeView
    weekly_challenge: ChallengeView
    team: MotivationTeamView | None
    leaderboard: list[LeaderboardItem]


@dataclass(frozen=True)
class PreferenceRecord:
    user_id: UUID
    enabled: bool = False
    team_opt_in: bool = False
    timezone: str = "UTC"
    team_id: UUID | None = None


@dataclass(frozen=True)
class TeamRecord:
    id: UUID
    name: str
    invite_code: str


@dataclass(frozen=True)
class ChallengeEntryRecord:
    session_id: UUID
    user_id: UUID
    kind: str
    period_key: str
    scenario_id: str
    seed: int
    team_id: UUID | None
    created_at: datetime


class MotivationRepository(Protocol):
    def get_preference(self, user_id: UUID) -> PreferenceRecord: ...
    def save_preference(self, item: PreferenceRecord) -> PreferenceRecord: ...
    def create_team(self, name: str) -> TeamRecord: ...
    def get_team(self, team_id: UUID) -> TeamRecord | None: ...
    def find_team(self, invite_code: str) -> TeamRecord | None: ...
    def list_team_members(self, team_id: UUID) -> tuple[PreferenceRecord, ...]: ...
    def list_opted_in_teams(self) -> tuple[TeamRecord, ...]: ...
    def get_entry(self, user_id: UUID, kind: str, period_key: str) -> ChallengeEntryRecord | None: ...
    def add_entry(self, item: ChallengeEntryRecord) -> ChallengeEntryRecord: ...
    def list_entries(self, kind: str, period_key: str) -> tuple[ChallengeEntryRecord, ...]: ...
    def recent_daily_entry(self, user_id: UUID, after: datetime) -> bool: ...
    def remove_empty_team(self, team_id: UUID) -> None: ...
    def delete_for_user(self, user_id: UUID) -> None: ...


class InMemoryMotivationRepository:
    def __init__(self) -> None:
        self.preferences: dict[UUID, PreferenceRecord] = {}
        self.teams: dict[UUID, TeamRecord] = {}
        self.entries: dict[tuple[UUID, str, str], ChallengeEntryRecord] = {}

    def get_preference(self, user_id: UUID) -> PreferenceRecord:
        return self.preferences.get(user_id, PreferenceRecord(user_id))

    def save_preference(self, item: PreferenceRecord) -> PreferenceRecord:
        self.preferences[item.user_id] = item
        return item

    def create_team(self, name: str) -> TeamRecord:
        team = TeamRecord(uuid4(), name, secrets.token_hex(8).upper())
        self.teams[team.id] = team
        return team

    def get_team(self, team_id: UUID) -> TeamRecord | None:
        return self.teams.get(team_id)

    def find_team(self, invite_code: str) -> TeamRecord | None:
        return next((team for team in self.teams.values() if team.invite_code == invite_code.upper()), None)

    def list_team_members(self, team_id: UUID) -> tuple[PreferenceRecord, ...]:
        return tuple(item for item in self.preferences.values() if item.team_id == team_id and item.enabled and item.team_opt_in)

    def list_opted_in_teams(self) -> tuple[TeamRecord, ...]:
        ids = {item.team_id for item in self.preferences.values() if item.team_id and item.enabled and item.team_opt_in}
        return tuple(team for team in self.teams.values() if team.id in ids)

    def get_entry(self, user_id: UUID, kind: str, period_key: str) -> ChallengeEntryRecord | None:
        return self.entries.get((user_id, kind, period_key))

    def add_entry(self, item: ChallengeEntryRecord) -> ChallengeEntryRecord:
        key = (item.user_id, item.kind, item.period_key)
        if key in self.entries:
            return self.entries[key]
        self.entries[key] = item
        return item

    def list_entries(self, kind: str, period_key: str) -> tuple[ChallengeEntryRecord, ...]:
        return tuple(item for item in self.entries.values() if item.kind == kind and item.period_key == period_key)

    def recent_daily_entry(self, user_id: UUID, after: datetime) -> bool:
        return any(item.user_id == user_id and item.kind == "daily" and item.created_at >= after for item in self.entries.values())

    def remove_empty_team(self, team_id: UUID) -> None:
        if not any(item.team_id == team_id for item in self.preferences.values()):
            self.teams.pop(team_id, None)

    def delete_for_user(self, user_id: UUID) -> None:
        self.preferences.pop(user_id, None)
        self.entries = {key: value for key, value in self.entries.items() if value.user_id != user_id}


class SqlAlchemyMotivationRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _preference(row: MotivationPreference | None, user_id: UUID) -> PreferenceRecord:
        return PreferenceRecord(user_id, row.enabled, row.team_opt_in, row.timezone, UUID(row.team_id) if row.team_id else None) if row else PreferenceRecord(user_id)

    @staticmethod
    def _team(row: MotivationTeam) -> TeamRecord:
        return TeamRecord(UUID(row.id), row.name, row.invite_code)

    @staticmethod
    def _entry(row: MotivationChallengeEntry) -> ChallengeEntryRecord:
        return ChallengeEntryRecord(UUID(row.session_id), UUID(row.user_id), row.kind, row.period_key, row.scenario_id, row.seed, UUID(row.team_id) if row.team_id else None, as_utc(row.created_at))

    def get_preference(self, user_id: UUID) -> PreferenceRecord:
        with self.database.session_factory() as db:
            return self._preference(db.get(MotivationPreference, str(user_id)), user_id)

    def save_preference(self, item: PreferenceRecord) -> PreferenceRecord:
        now = utc_now()
        with self.database.session_factory.begin() as db:
            row = db.get(MotivationPreference, str(item.user_id))
            if row is None:
                row = MotivationPreference(user_id=str(item.user_id), created_at=now)
                db.add(row)
            row.enabled = item.enabled
            row.team_opt_in = item.team_opt_in
            row.timezone = item.timezone
            row.team_id = str(item.team_id) if item.team_id else None
            row.updated_at = now
        return item

    def create_team(self, name: str) -> TeamRecord:
        team = TeamRecord(uuid4(), name, secrets.token_hex(8).upper())
        with self.database.session_factory.begin() as db:
            db.add(MotivationTeam(id=str(team.id), name=name, invite_code=team.invite_code, created_at=utc_now()))
        return team

    def get_team(self, team_id: UUID) -> TeamRecord | None:
        with self.database.session_factory() as db:
            row = db.get(MotivationTeam, str(team_id))
            return self._team(row) if row else None

    def find_team(self, invite_code: str) -> TeamRecord | None:
        with self.database.session_factory() as db:
            row = db.scalar(select(MotivationTeam).where(MotivationTeam.invite_code == invite_code.upper()))
            return self._team(row) if row else None

    def list_team_members(self, team_id: UUID) -> tuple[PreferenceRecord, ...]:
        with self.database.session_factory() as db:
            rows = db.scalars(select(MotivationPreference).where(MotivationPreference.team_id == str(team_id), MotivationPreference.enabled.is_(True), MotivationPreference.team_opt_in.is_(True))).all()
            return tuple(self._preference(row, UUID(row.user_id)) for row in rows)

    def list_opted_in_teams(self) -> tuple[TeamRecord, ...]:
        with self.database.session_factory() as db:
            rows = db.scalars(select(MotivationTeam).join(MotivationPreference, MotivationPreference.team_id == MotivationTeam.id).where(MotivationPreference.enabled.is_(True), MotivationPreference.team_opt_in.is_(True)).distinct()).all()
            return tuple(self._team(row) for row in rows)

    def get_entry(self, user_id: UUID, kind: str, period_key: str) -> ChallengeEntryRecord | None:
        with self.database.session_factory() as db:
            row = db.scalar(select(MotivationChallengeEntry).where(MotivationChallengeEntry.user_id == str(user_id), MotivationChallengeEntry.kind == kind, MotivationChallengeEntry.period_key == period_key))
            return self._entry(row) if row else None

    def add_entry(self, item: ChallengeEntryRecord) -> ChallengeEntryRecord:
        try:
            with self.database.session_factory.begin() as db:
                db.add(MotivationChallengeEntry(session_id=str(item.session_id), user_id=str(item.user_id), kind=item.kind, period_key=item.period_key, scenario_id=item.scenario_id, seed=item.seed, team_id=str(item.team_id) if item.team_id else None, created_at=item.created_at))
            return item
        except IntegrityError:
            existing = self.get_entry(item.user_id, item.kind, item.period_key)
            if existing is None:
                raise
            return existing

    def list_entries(self, kind: str, period_key: str) -> tuple[ChallengeEntryRecord, ...]:
        with self.database.session_factory() as db:
            rows = db.scalars(select(MotivationChallengeEntry).where(MotivationChallengeEntry.kind == kind, MotivationChallengeEntry.period_key == period_key)).all()
            return tuple(self._entry(row) for row in rows)

    def recent_daily_entry(self, user_id: UUID, after: datetime) -> bool:
        with self.database.session_factory() as db:
            return db.scalar(select(func.count()).select_from(MotivationChallengeEntry).where(MotivationChallengeEntry.user_id == str(user_id), MotivationChallengeEntry.kind == "daily", MotivationChallengeEntry.created_at >= after)) > 0

    def remove_empty_team(self, team_id: UUID) -> None:
        with self.database.session_factory.begin() as db:
            row = db.get(MotivationTeam, str(team_id), with_for_update=True)
            if row and not db.scalar(select(func.count()).select_from(MotivationPreference).where(MotivationPreference.team_id == str(team_id))):
                db.delete(row)

    def delete_for_user(self, user_id: UUID) -> None:
        with self.database.session_factory.begin() as db:
            db.execute(delete(MotivationChallengeEntry).where(MotivationChallengeEntry.user_id == str(user_id)))
            db.execute(delete(MotivationPreference).where(MotivationPreference.user_id == str(user_id)))


def _seed(kind: str, period_key: str) -> int:
    return int.from_bytes(hashlib.sha256(f"arena-v1:{kind}:{period_key}".encode()).digest()[:4], "big") & 0x7FFFFFFF


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[\w]+", text.casefold(), flags=re.UNICODE))


def _ngrams(tokens: tuple[str, ...], size: int = 5) -> set[tuple[str, ...]]:
    return {tokens[index:index + size] for index in range(len(tokens) - size + 1)}


def _substantive(session: NegotiationSession, other_sessions: list[NegotiationSession]) -> bool:
    """Count varied practice once; a repeated script never earns another reward."""
    texts = [message.content for message in session.messages if message.role == "participant"]
    tokens = [_tokens(text) for text in texts]
    if len(tokens) < 3 or sum(len(item) for item in tokens) < 35:
        return False
    normalized = {" ".join(item) for item in tokens if len(item) >= 5}
    if len(normalized) < 3:
        return False
    for index, left in enumerate(tokens):
        for right in tokens[index + 1:]:
            if left and right and len(set(left) & set(right)) / min(len(set(left)), len(set(right))) >= 0.85:
                return False
    words = tuple(word for item in tokens for word in item)
    current = _ngrams(words, 4)
    if not current:
        return False
    for previous in other_sessions:
        if previous.id == session.id or previous.completed_at is None:
            continue
        past_words = tuple(word for message in previous.messages if message.role == "participant" for word in _tokens(message.content))
        past = _ngrams(past_words, 4)
        if past and (len(current & past) / min(len(current), len(past)) >= 0.65 or len(set(words) & set(past_words)) / max(1, len(set(words) | set(past_words))) >= 0.85):
            return False
    return True


def _streak(dates: list[CalendarDate], today: CalendarDate) -> StreakView:
    unique = sorted(set(dates))
    if not unique:
        return StreakView(current=0, longest=0, last_practiced_on=None)
    longest = length = 1
    for previous, current in zip(unique, unique[1:]):
        length = length + 1 if current - previous == timedelta(days=1) else 1
        longest = max(longest, length)
    current = 0
    if unique[-1] in {today, today - timedelta(days=1)}:
        current = 1
        for older, newer in zip(reversed(unique[:-1]), reversed(unique[1:])):
            if newer - older != timedelta(days=1):
                break
            current += 1
    return StreakView(current=current, longest=longest, last_practiced_on=unique[-1])


class MotivationService:
    def __init__(self, sessions: SessionRepository, catalog: ScenarioCatalog, reviews: PeerReviewRepository, records: MotivationRepository, clock=utc_now) -> None:
        self.sessions = sessions
        self.catalog = catalog
        self.reviews = reviews
        self.records = records
        self.clock = clock

    def _now(self) -> datetime:
        return as_utc(self.clock())

    def set_preferences(self, user_id: UUID, payload: MotivationPreferenceRequest) -> MotivationDashboard:
        previous = self.records.get_preference(user_id)
        if previous.timezone != payload.timezone and self.records.recent_daily_entry(user_id, self._now() - timedelta(hours=24)):
            raise ValueError("timezone_locked_after_daily_start")
        self.records.save_preference(PreferenceRecord(user_id, payload.enabled, payload.enabled and payload.team_opt_in, payload.timezone, previous.team_id))
        return self.dashboard(user_id)

    def create_team(self, user_id: UUID, name: str) -> MotivationDashboard:
        preference = self.records.get_preference(user_id)
        if not preference.enabled:
            raise ValueError("motivation_disabled")
        if preference.team_id is not None:
            raise ValueError("already_in_team")
        team = self.records.create_team(name)
        self.records.save_preference(PreferenceRecord(user_id, True, True, preference.timezone, team.id))
        return self.dashboard(user_id)

    def join_team(self, user_id: UUID, invite_code: str) -> MotivationDashboard:
        preference = self.records.get_preference(user_id)
        if not preference.enabled:
            raise ValueError("motivation_disabled")
        if preference.team_id is not None:
            raise ValueError("already_in_team")
        team = self.records.find_team(invite_code)
        if team is None:
            raise LookupError("team_not_found")
        self.records.save_preference(PreferenceRecord(user_id, True, True, preference.timezone, team.id))
        return self.dashboard(user_id)

    def leave_team(self, user_id: UUID) -> MotivationDashboard:
        preference = self.records.get_preference(user_id)
        self.records.save_preference(PreferenceRecord(user_id, preference.enabled, False, preference.timezone, None))
        if preference.team_id:
            self.records.remove_empty_team(preference.team_id)
        return self.dashboard(user_id)

    def delete_for_user(self, user_id: UUID) -> None:
        team_id = self.records.get_preference(user_id).team_id
        self.records.delete_for_user(user_id)
        if team_id:
            self.records.remove_empty_team(team_id)

    def _period(self, kind: Literal["daily", "weekly"], preference: PreferenceRecord) -> tuple[str, CalendarDate]:
        now = self._now()
        if kind == "daily":
            value = now.astimezone(ZoneInfo(preference.timezone)).date()
            return value.isoformat(), value
        value = now.date() - timedelta(days=now.weekday())
        return value.isoformat(), value

    def _challenge(self, user_id: UUID, kind: Literal["daily", "weekly"], preference: PreferenceRecord) -> ChallengeView:
        period_key, day = self._period(kind, preference)
        candidates = sorted((item for item in self.catalog.list() if item.source == "curated"), key=lambda item: item.id)
        if not candidates:
            raise RuntimeError("curated_scenario_pool_empty")
        seed = _seed(kind, period_key)
        skill = SKILLS[seed % len(SKILLS)]
        method = {"questions": "spin", "active_listening": "active_listening", "meso": "meso", "exchanges": "contingent_agreement"}.get(skill.id, "seven_elements")
        relevant = [item for item in candidates if method in item.methods] or candidates
        scenario = relevant[(seed // len(SKILLS)) % len(relevant)]
        skill_id = skill.id
        entry = self.records.get_entry(user_id, kind, period_key)
        if entry:
            # A catalog update must not silently change an already-started case.
            seed = entry.seed
            scenario = self.catalog.get(entry.scenario_id) or scenario
        session = self.sessions.get(entry.session_id) if entry else None
        completed = bool(session and any(item.id == session.id for item, _ in self._qualified(user_id)))
        return ChallengeView(date=day if kind == "daily" else None, week_start=day if kind == "weekly" else None, scenario_id=entry.scenario_id if entry else scenario.id, scenario_title=session.configuration.topic if session else scenario.title, seed=seed, skill_id=skill_id, completed=completed, session_id=entry.session_id if entry else None)

    def start_challenge(self, user_id: UUID, kind: Literal["daily", "weekly"]) -> NegotiationSession:
        preference = self.records.get_preference(user_id)
        if not preference.enabled:
            raise ValueError("motivation_disabled")
        if kind == "weekly" and not (preference.team_opt_in and preference.team_id):
            raise ValueError("team_challenge_requires_opt_in")
        period_key, _ = self._period(kind, preference)
        existing = self.records.get_entry(user_id, kind, period_key)
        if existing:
            session = self.sessions.get(existing.session_id)
            if session:
                return session
        challenge = self._challenge(user_id, kind, preference)
        scenario = self.catalog.get(challenge.scenario_id)
        definition = self.catalog.get_definition(challenge.scenario_id)
        if scenario is None or definition is None:
            raise RuntimeError("challenge_scenario_unavailable")
        config = default_session_configuration(scenario, definition)
        config = config.model_copy(update={"simulation": config.simulation.model_copy(update={"enabled": True, "seed": challenge.seed})})
        fixed_id = uuid5(NAMESPACE_URL, f"arena-challenge-v1:{user_id}:{kind}:{period_key}")
        try:
            session = create_session(self.sessions, self.catalog, challenge.scenario_id, config, user_id, fixed_id)
        except (ValueError, IntegrityError):
            session = self.sessions.get(fixed_id)
            if session is None or session.participant_user_id != user_id:
                raise
        registered = self.records.add_entry(ChallengeEntryRecord(session.id, user_id, kind, period_key, challenge.scenario_id, challenge.seed, preference.team_id if kind == "weekly" else None, self._now()))
        return self.sessions.get(registered.session_id) or session

    def _qualified(self, user_id: UUID) -> list[tuple[NegotiationSession, ReportResponse]]:
        sessions = sorted(self.sessions.list_for_user(user_id), key=lambda item: as_utc(item.completed_at or item.created_at))
        qualified: list[tuple[NegotiationSession, ReportResponse]] = []
        for session in sessions:
            if session.status is not SessionStatus.COMPLETED or session.completed_at is None:
                continue
            report = self.sessions.get_report(session.id)
            if report is None or not _substantive(session, [item[0] for item in qualified]):
                continue
            qualified.append((session, report))
        return qualified

    def _review_rewards(self, user_id: UUID) -> list[tuple[datetime, str]]:
        result: list[tuple[datetime, str]] = []
        for item in self.reviews.list_for_user(user_id):
            record = self.reviews.get(item.assignment_id)
            if not record or not record.submitted or not record.result or record.assignment_kind != "peer":
                continue
            reputation = record.result.reputation
            if reputation.points >= 70 and reputation.accuracy >= 60 and reputation.evidence_quality >= 70 and reputation.helpfulness >= 70 and record.appeal_status != "pending":
                result.append((as_utc(record.submitted_at or item.submitted_at or self._now()), str(item.assignment_id)))
        return result

    def _baseline(self, user_id: UUID, before: datetime, rubric_version: str, evaluator_version: str, excluded_session_id: UUID) -> float | None:
        previous = [(session, report) for session, report in self._qualified(user_id) if session.id != excluded_session_id and as_utc(session.completed_at or session.created_at) < before and report.rubric_version == rubric_version and report.evaluator_version == evaluator_version]
        return mean(report.score for _, report in previous[-3:]) if previous else None

    def _entry_points(self, entry: ChallengeEntryRecord) -> int:
        preference = self.records.get_preference(entry.user_id)
        if not (preference.enabled and preference.team_opt_in and preference.team_id == entry.team_id):
            return 0
        session = self.sessions.get(entry.session_id)
        if not session or session.participant_user_id != entry.user_id or session.scenario_id != entry.scenario_id or session.configuration.simulation.seed != entry.seed or session.status is not SessionStatus.COMPLETED or session.completed_at is None:
            return 0
        report = self.sessions.get_report(session.id)
        if report is None or not any(item.id == session.id for item, _ in self._qualified(entry.user_id)):
            return 0
        baseline = self._baseline(entry.user_id, as_utc(session.completed_at), report.rubric_version, report.evaluator_version, session.id)
        improvement = max(0, report.score - baseline) if baseline is not None else 0
        action_types = len({str(event.action_tag) for event in session.reason_events if event.action_tag})
        return min(60, round(improvement * 2)) + min(20, action_types * 4) + (10 if report.score >= 50 else 0)

    def _leaderboard(self, week_key: str) -> list[LeaderboardItem]:
        entries = self.records.list_entries("weekly", week_key)
        totals: list[tuple[TeamRecord, int, int, int]] = []
        for team in self.records.list_opted_in_teams():
            members = self.records.list_team_members(team.id)
            if not members:
                continue
            team_entries = [item for item in entries if item.team_id == team.id]
            points = sum(self._entry_points(item) for item in team_entries)
            completed = sum(self._entry_points(item) > 0 for item in team_entries)
            totals.append((team, len(members), points, completed))
        totals.sort(key=lambda item: (-item[2], -item[3], item[0].id.hex))
        return [LeaderboardItem(rank=index, team_id=team.id, team_name=team.name, members=members, points=points, completed_sessions=completed) for index, (team, members, points, completed) in enumerate(totals, start=1)]

    def dashboard(self, user_id: UUID) -> MotivationDashboard:
        preference = self.records.get_preference(user_id)
        daily = self._challenge(user_id, "daily", preference)
        weekly = self._challenge(user_id, "weekly", preference)
        empty = MotivationDashboard(enabled=preference.enabled, team_opt_in=preference.team_opt_in, timezone=preference.timezone, streak=StreakView(current=0, longest=0, last_practiced_on=None), skill_tree=[], achievements=[], daily_challenge=daily, weekly_challenge=weekly, team=None, leaderboard=[])
        if not preference.enabled:
            return empty
        qualified = self._qualified(user_id)
        timezone_name = ZoneInfo(preference.timezone)
        today = self._now().astimezone(timezone_name).date()
        streak = _streak([as_utc(session.completed_at).astimezone(timezone_name).date() for session, _ in qualified if session.completed_at], today)
        current_rubric = qualified[-1][1].rubric_version if qualified else None
        current_evaluator = qualified[-1][1].evaluator_version if qualified else None
        scores = [(session, report, _attempt_scores(session, report)) for session, report in qualified if report.rubric_version == current_rubric and report.evaluator_version == current_evaluator]
        requirements = {"interests": None, "questions": None, "active_listening": None, "criteria": "questions", "meso": "criteria", "exchanges": "interests", "batna": "exchanges", "commitments": "batna"}
        levels = {}
        for spec in SKILLS:
            values = [item[2][spec.id] for item in scores]
            levels[spec.id] = 3 if sum(value >= 75 for value in values) >= 3 else 2 if sum(value >= 50 for value in values) >= 2 else 1 if any(value >= 50 for value in values) else 0
        tree = []
        for spec in SKILLS:
            dependency = requirements[spec.id]
            unlocked = dependency is None or levels[dependency] >= 1
            tree.append(SkillTreeNode(id=spec.id, title=spec.title, level=levels[spec.id], unlocked=unlocked, unlock_reason="Доступен с начала" if dependency is None else f"Нужен уровень 1 навыка «{next(item.title for item in SKILLS if item.id == dependency)}»", next_requirement="Уровень 3 достигнут" if levels[spec.id] == 3 else "Покажите этот навык в разных содержательных сессиях: 1 / 2 / 3 подтверждения"))
        achievements: list[AchievementView] = []
        def award(identifier: str, title: str, description: str, at: datetime | None) -> None:
            if at:
                achievements.append(AchievementView(id=identifier, title=title, description=description, earned_at=as_utc(at)))
        if qualified:
            award("first_practice", "Первый шаг", "Завершена содержательная тренировка", qualified[0][0].completed_at)
        if streak.longest >= 3:
            award("practice_streak", "Ритм практики", "Три дня содержательной практики подряд", qualified[-1][0].completed_at)
        for spec, tag in (("questions", "open_questions"), ("active_listening", "active_listening"), ("meso", "meso"), ("exchanges", "conditional_agreement")):
            match = next((session for session, _, item in scores if item[spec] >= 80), None)
            award(tag, next(item.title for item in SKILLS if item.id == spec), f"Навык «{spec}» подтверждён в конкретных действиях", match.completed_at if match else None)
        for session, report in qualified:
            baseline = self._baseline(user_id, as_utc(session.completed_at), report.rubric_version, report.evaluator_version, session.id)
            if baseline is not None and report.score >= baseline + 5:
                award("self_improvement", "Лучше себя", "Результат выше собственного сопоставимого уровня", session.completed_at)
                break
        reviews = self._review_rewards(user_id)
        if reviews:
            award("quality_reviewer", "Полезная рецензия", "Обоснованный peer-review с качественной обратной связью", reviews[0][0])
        for kind, challenge in (("daily", daily), ("weekly", weekly)):
            if challenge.completed and challenge.session_id and any(session.id == challenge.session_id for session, _ in qualified):
                session = self.sessions.get(challenge.session_id)
                award(f"{kind}_challenge", "Вызов дня" if kind == "daily" else "Командная неделя", "Зачтён вызов с общим сценарием и seed", session.completed_at if session else None)
        team = self.records.get_team(preference.team_id) if preference.team_id and preference.team_opt_in else None
        team_view = MotivationTeamView(id=team.id, name=team.name, invite_code=team.invite_code, members=len(self.records.list_team_members(team.id))) if team else None
        leaderboard = self._leaderboard(weekly.week_start.isoformat()) if preference.team_opt_in and team_view else []
        return MotivationDashboard(enabled=True, team_opt_in=preference.team_opt_in, timezone=preference.timezone, streak=streak, skill_tree=tree, achievements=sorted(achievements, key=lambda item: item.earned_at), daily_challenge=daily, weekly_challenge=weekly, team=team_view, leaderboard=leaderboard)
