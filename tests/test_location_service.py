import pytest
from sqlmodel import Session, SQLModel, create_engine
from app.db.models import Location, CitySubLocation
from app.db.location_service import create_city_sublocation, get_city_sublocations, discover_sublocation

@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s

@pytest.fixture
def city(session):
    loc = Location(name="TestCity", description="A test city.", x=0.0, y=0.0, location_type="city")
    session.add(loc)
    session.commit()
    session.refresh(loc)
    return loc

def test_create_city_sublocation(session, city):
    result = create_city_sublocation(session, city.id, "The Prancing Pony", "A cozy inn", "inn")
    assert result["success"] is True
    assert result["sub_location"].name == "The Prancing Pony"
    assert result["sub_location"].city_id == city.id
    assert result["sub_location"].sub_type == "inn"
    assert result["sub_location"].is_discovered is False

def test_create_duplicate_sublocation(session, city):
    create_city_sublocation(session, city.id, "Duplicate Shop", "Desc", "shop")
    result = create_city_sublocation(session, city.id, "Duplicate Shop", "Desc 2", "shop")
    assert result["success"] is False
    assert "already exists" in result["reason"]

def test_invalid_sub_type(session, city):
    result = create_city_sublocation(session, city.id, "Weird Place", "Desc", "spaceship")
    assert result["success"] is False
    assert "Invalid sub_type" in result["reason"]

def test_max_limit_sublocations(session, city):
    for i in range(50):
        create_city_sublocation(session, city.id, f"Loc {i}", "Desc", "shop")
    
    result = create_city_sublocation(session, city.id, "Loc 51", "Desc", "shop")
    assert result["success"] is False
    assert "Maximum number" in result["reason"]

def test_discover_sublocation(session, city):
    res = create_city_sublocation(session, city.id, "Hidden Cave", "Desc", "hidden")
    sub_id = res["sub_location"].id
    
    # Should not be in get_city_sublocations yet
    assert len(get_city_sublocations(session, city.id)) == 0
    
    # Discover it
    success = discover_sublocation(session, sub_id)
    assert success is True
    
    # Should be available now
    discovered = get_city_sublocations(session, city.id)
    assert len(discovered) == 1
    assert discovered[0].name == "Hidden Cave"
