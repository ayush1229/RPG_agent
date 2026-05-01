import pytest
from sqlmodel import Session, SQLModel, create_engine
from app.db.models import Location, SideCharacter, TarotEntity, NPCIntent, NPCWorldEvent
from app.db.npc_simulation_service import spawn_generic_npc, evaluate_intent, generate_world_events

@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s

@pytest.fixture
def location(session):
    loc = Location(name="Test City", description="A test city.", x=0.0, y=0.0, location_type="city")
    session.add(loc)
    session.commit()
    session.refresh(loc)
    return loc

def test_spawn_generic_npc(session, location):
    entity, npc = spawn_generic_npc(session, "merchant", location.id)
    assert npc is not None
    assert entity is not None
    assert npc.position == "Merchant"
    assert npc.location_id == location.id

def test_evaluate_intent(session, location):
    entity, npc = spawn_generic_npc(session, "bandit", location.id)
    intent = evaluate_intent(session, entity.id, "bandit", location.id)
    # The intent is saved to DB, so we need to query it
    saved_intent = session.exec(
        __import__("sqlmodel").select(NPCIntent).where(NPCIntent.entity_id == entity.id)
    ).first()
    assert saved_intent is not None
    assert saved_intent.intent_type in ["hunt", "travel"]

def test_generate_world_events(session, location):
    e1, npc1 = spawn_generic_npc(session, "bandit", location.id)
    e2, npc2 = spawn_generic_npc(session, "merchant", location.id)
    
    # Generate events for this location
    generate_world_events(session, location.id)
    
    events = session.exec(
        __import__("sqlmodel").select(NPCWorldEvent).where(NPCWorldEvent.location_id == location.id)
    ).all()
    
    assert isinstance(events, list)
