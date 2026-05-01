from typing import Optional, List
from sqlmodel import Session, select
from app.db.models import CitySubLocation, Location

def create_city_sublocation(
    session: Session, 
    city_id: int, 
    name: str, 
    description: str, 
    sub_type: str,
    tags: Optional[str] = None
) -> dict:
    """
    Creates a new sub-location inside a city.
    Must validate:
    - city exists
    - name uniqueness within city
    """
    # Enforce sub_type validation
    valid_sub_types = ["inn", "shop", "square", "district", "guild", "hidden", "residence"]
    if sub_type not in valid_sub_types:
        return {"success": False, "reason": f"Invalid sub_type. Must be one of {valid_sub_types}"}

    city = session.get(Location, city_id)
    if not city:
        return {"success": False, "reason": "City location not found."}

    # Enforce max limit per city
    current_count = session.exec(
        select(CitySubLocation).where(CitySubLocation.city_id == city_id)
    ).all()
    
    if len(current_count) >= 50:
        return {"success": False, "reason": "Maximum number of sub-locations reached for this city (50)."}

    # Check for duplicates
    duplicate = session.exec(
        select(CitySubLocation).where(
            CitySubLocation.city_id == city_id,
            CitySubLocation.name == name
        )
    ).first()
    
    if duplicate:
        return {"success": False, "reason": f"A sub-location named '{name}' already exists in this city."}

    sub_loc = CitySubLocation(
        name=name,
        description=description,
        city_id=city_id,
        sub_type=sub_type,
        is_safe_zone=True,
        is_discovered=False,
        tags=tags
    )
    
    session.add(sub_loc)
    session.commit()
    session.refresh(sub_loc)
    
    return {"success": True, "sub_location": sub_loc}


def get_city_sublocations(session: Session, city_id: int) -> List[CitySubLocation]:
    """Returns all discovered sub-locations in a city."""
    return list(session.exec(
        select(CitySubLocation).where(
            CitySubLocation.city_id == city_id,
            CitySubLocation.is_discovered == True
        )
    ).all())


def discover_sublocation(session: Session, sublocation_id: int) -> bool:
    """Marks a location as discovered."""
    sub_loc = session.get(CitySubLocation, sublocation_id)
    if sub_loc and not sub_loc.is_discovered:
        sub_loc.is_discovered = True
        session.add(sub_loc)
        session.commit()
        return True
    return False
