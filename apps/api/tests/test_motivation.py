from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.database import Database
from app.db.models import MotivationTeam, User
from app.main import create_app
from app.motivation import PreferenceRecord, SqlAlchemyMotivationRepository
from app.repository import InMemorySessionRepository


def registered(app, address):
    client = TestClient(app)
    response = client.post("/api/v1/auth/register", json={"email": address, "display_name": "Участник", "password": "Strong-pass-42"})
    assert response.status_code == 201
    return client, response.json()["csrf_token"]


def enabled(client, csrf, *, team=False, zone="UTC"):
    response = client.post("/api/v1/me/motivation/preferences", json={"enabled": True, "team_opt_in": team, "timezone": zone}, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200
    return response.json()


def complete(client, csrf, session_id, texts):
    for text in texts:
        response = client.post(f"/api/v1/sessions/{session_id}/messages", json={"content": text}, headers={"X-CSRF-Token": csrf})
        assert response.status_code == 200
    assert client.post(f"/api/v1/sessions/{session_id}/complete", headers={"X-CSRF-Token": csrf}).status_code == 200
    assert client.get(f"/api/v1/sessions/{session_id}/report").status_code == 200


SCRIPT = [
    "Какие ограничения по срокам для вас самые важные, и почему текущий вариант вызывает опасения?",
    "Правильно понимаю, что ключевой риск связан с загрузкой команды? Какой график был бы для вас приемлемым?",
    "Предлагаю сравнить два пакета: ускорить поставку при предоплате либо сохранить срок и расширить сервис. Что важнее?",
]


def test_opt_in_seeded_start_is_idempotent_and_account_scoped():
    app = create_app(InMemorySessionRepository())
    first, csrf = registered(app, "motivation-one@example.test")
    second, csrf2 = registered(app, "motivation-two@example.test")
    assert first.get("/api/v1/me/motivation").json()["enabled"] is False
    assert first.post("/api/v1/me/motivation/challenges/daily/start", headers={"X-CSRF-Token": csrf}).status_code == 409
    enabled(first, csrf, zone="Asia/Yekaterinburg")
    enabled(second, csrf2, zone="Asia/Yekaterinburg")
    one = first.post("/api/v1/me/motivation/challenges/daily/start", headers={"X-CSRF-Token": csrf})
    repeat = first.post("/api/v1/me/motivation/challenges/daily/start", headers={"X-CSRF-Token": csrf})
    two = second.post("/api/v1/me/motivation/challenges/daily/start", headers={"X-CSRF-Token": csrf2})
    assert one.status_code == repeat.status_code == two.status_code == 201
    assert one.json()["id"] == repeat.json()["id"] != two.json()["id"]
    assert one.json()["scenario_id"] == two.json()["scenario_id"]
    assert one.json()["simulation"]["seed"] == two.json()["simulation"]["seed"]
    assert second.get(f"/api/v1/sessions/{one.json()['id']}").status_code == 404
    assert first.post("/api/v1/me/motivation/preferences", json={"enabled": True, "timezone": "UTC"}, headers={"X-CSRF-Token": csrf}).status_code == 409


def test_team_weekly_requires_consent_and_privacy_after_opt_out():
    app = create_app(InMemorySessionRepository())
    owner, csrf = registered(app, "team-owner@example.test")
    guest, csrf2 = registered(app, "team-joiner@example.test")
    enabled(owner, csrf)
    assert owner.post("/api/v1/me/motivation/challenges/weekly/start", headers={"X-CSRF-Token": csrf}).status_code == 409
    created = owner.post("/api/v1/me/motivation/team/create", json={"name": "Практики"}, headers={"X-CSRF-Token": csrf})
    assert created.status_code == 200
    team = created.json()["team"]
    enabled(guest, csrf2)
    joined = guest.post("/api/v1/me/motivation/team/join", json={"invite_code": team["invite_code"]}, headers={"X-CSRF-Token": csrf2})
    assert joined.status_code == 200
    assert joined.json()["team"]["members"] == 2
    weekly = owner.post("/api/v1/me/motivation/challenges/weekly/start", headers={"X-CSRF-Token": csrf})
    assert weekly.status_code == 201
    copied = owner.post("/api/v1/sessions", json={"scenario_id": weekly.json()["scenario_id"], "configuration": weekly.json()["configuration"]}, headers={"X-CSRF-Token": csrf})
    assert copied.status_code == 201
    complete(owner, csrf, copied.json()["id"], [
        "На совещании важно согласовать бюджет инициативы и ответственность за обработку всех поступающих заявок.",
        "Сначала уточним доступность сотрудников по неделям, а затем составим согласованный график подготовки материалов.",
        "Предлагаю записать ответственных, срок промежуточной проверки и условия пересмотра решений после первого месяца.",
    ])
    assert owner.get("/api/v1/me/motivation").json()["leaderboard"][0]["points"] == 0
    complete(owner, csrf, weekly.json()["id"], SCRIPT)
    assert owner.get("/api/v1/me/motivation").json()["leaderboard"][0]["points"] > 0
    assert owner.get("/api/v1/me/motivation").json()["leaderboard"][0]["team_name"] == "Практики"
    opted_out = owner.post("/api/v1/me/motivation/preferences", json={"enabled": False, "team_opt_in": False, "timezone": "UTC"}, headers={"X-CSRF-Token": csrf})
    assert opted_out.status_code == 200
    assert opted_out.json()["leaderboard"] == []
    assert guest.get("/api/v1/me/motivation").json()["team"]["members"] == 1


def test_substantive_practice_counts_once_and_template_replay_does_not_farm():
    repository = InMemorySessionRepository()
    app = create_app(repository)
    client, csrf = registered(app, "streak@example.test")
    enabled(client, csrf)
    first = client.post("/api/v1/me/motivation/challenges/daily/start", headers={"X-CSRF-Token": csrf}).json()
    complete(client, csrf, first["id"], SCRIPT)
    dashboard = client.get("/api/v1/me/motivation").json()
    assert dashboard["streak"]["current"] == 1
    assert [item["id"] for item in dashboard["achievements"]].count("first_practice") == 1
    replay = client.post("/api/v1/sessions", json={"scenario_id": first["scenario_id"]}, headers={"X-CSRF-Token": csrf}).json()
    complete(client, csrf, replay["id"], SCRIPT)
    after = client.get("/api/v1/me/motivation").json()
    assert after["streak"]["current"] == 1
    assert all(node["level"] <= 1 for node in after["skill_tree"])


def test_local_calendar_streak_across_utc_midnight():
    repository = InMemorySessionRepository()
    app = create_app(repository)
    client, csrf = registered(app, "calendar@example.test")
    enabled(client, csrf, zone="Asia/Yekaterinburg")
    first = client.post("/api/v1/me/motivation/challenges/daily/start", headers={"X-CSRF-Token": csrf}).json()
    complete(client, csrf, first["id"], SCRIPT)
    session = repository.get(UUID(first["id"]))
    assert session is not None
    session.completed_at = datetime(2026, 9, 24, 18, 30, tzinfo=timezone.utc)
    repository.save(session)
    app.state.motivation_service.clock = lambda: datetime(2026, 9, 25, 18, 0, tzinfo=timezone.utc)
    second = client.post("/api/v1/sessions", json={"scenario_id": first["scenario_id"]}, headers={"X-CSRF-Token": csrf}).json()
    complete(client, csrf, second["id"], [
        "Нужно разобраться в распределении бюджета и ответственности между подразделениями до утверждения графика проекта.",
        "Если мы выделим инженера на две недели, сможете подтвердить объем работ и закрепить ответственного за приемку?",
        "Давайте зафиксируем конкретную контрольную дату, метрику готовности и следующий разговор с владельцем процесса.",
    ])
    second_session = repository.get(UUID(second["id"]))
    assert second_session is not None
    second_session.completed_at = datetime(2026, 9, 25, 18, 0, tzinfo=timezone.utc)
    repository.save(second_session)
    result = client.get("/api/v1/me/motivation").json()
    assert result["streak"]["current"] == 2


def test_sql_preferences_and_team_are_removed_with_account_data():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    database = Database(engine, sessionmaker(bind=engine, expire_on_commit=False))
    user_id = uuid4()
    with database.session_factory.begin() as db:
        db.add(User(id=str(user_id), email="sql-motivation@example.test", display_name="Участник"))
    records = SqlAlchemyMotivationRepository(database)
    team = records.create_team("Команда")
    records.save_preference(PreferenceRecord(user_id, True, True, "Asia/Yekaterinburg", team.id))
    assert records.get_preference(user_id).timezone == "Asia/Yekaterinburg"
    assert len(records.list_team_members(team.id)) == 1
    records.delete_for_user(user_id)
    records.remove_empty_team(team.id)
    assert records.get_preference(user_id).enabled is False
    with database.session_factory() as db:
        assert db.scalar(select(MotivationTeam).where(MotivationTeam.id == str(team.id))) is None
    engine.dispose()
