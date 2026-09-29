from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.database import create_database
from app.db.settings import DatabaseSettings
from app.db.models import (
    MessageRecord,
    NegotiationSession,
    PeerReview,
    PeerReviewItem,
    Role,
    Scenario,
    ScenarioVersion,
    User,
    UserRole,
)


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    Base.metadata.drop_all(engine)


def test_schema_creates_and_persists_minimal_relationships(session: Session) -> None:
    user = User(email="participant@example.test", display_name="Participant")
    role = Role(id="participant", name="Participant")
    scenario = Scenario(slug="supply-equipment", title="Supply", summary="Equipment supply")
    session.add_all([user, role, scenario])
    session.flush()
    session.add(UserRole(user=user, role=role))
    version = ScenarioVersion(scenario=scenario, version_number=1, definition={"title": "Supply"})
    session.add(version)
    session.flush()
    negotiation = NegotiationSession(scenario_version=version, participant_user_id=user.id)
    session.add(negotiation)
    session.flush()
    message = MessageRecord(session=negotiation, sequence_number=1, author_type="participant", content="Let us discuss the terms.")
    review = PeerReview(session_id=negotiation.id, reviewer_user_id=user.id)
    session.add_all([message, review])
    session.flush()
    session.add(PeerReviewItem(peer_review=review, criterion_code="interests", score=4, message_id=message.id))
    session.commit()

    stored = session.get(NegotiationSession, negotiation.id)
    assert stored is not None
    assert stored.scenario_version.scenario.slug == "supply-equipment"
    assert stored.messages[0].content.startswith("Let us")
    assert isinstance(stored.id, str) and len(stored.id) == 36
    assert isinstance(stored.series_id, str) and len(stored.series_id) == 36
    assert stored.attempt_number == 1


def test_unique_message_sequence_is_enforced(session: Session) -> None:
    scenario = Scenario(slug="resources", title="Resources", summary="Project resources")
    version = ScenarioVersion(scenario=scenario, version_number=1, definition={})
    negotiation = NegotiationSession(scenario_version=version)
    session.add_all([scenario, version, negotiation])
    session.flush()
    session.add_all([
        MessageRecord(session=negotiation, sequence_number=1, author_type="participant", content="One"),
        MessageRecord(session=negotiation, sequence_number=1, author_type="opponent", content="Two"),
    ])
    with pytest.raises(IntegrityError):
        session.commit()


def test_database_factory_accepts_sqlite_url() -> None:
    database = create_database(DatabaseSettings("sqlite+pysqlite:///:memory:"))
    Base.metadata.create_all(database.engine)
    with database.session_factory() as session:
        session.add(Role(id="observer", name="Observer"))
        session.commit()
    database.engine.dispose()
