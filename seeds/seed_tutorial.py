import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from sqlmodel import Session, select
from app.db.database import engine
from app.db.models import Location, CitySubLocation

subs = [
    {'name': 'Broken Lantern Inn', 'desc': 'A cozy, dimly lit tavern smelling of woodsmoke and old ale.', 'type': 'inn'},
    {'name': 'Old Well Square', 'desc': 'The bustling center of Ardent Hollow, built around a dried-up stone well.', 'type': 'square'},
    {'name': 'Whispering Forest Edge', 'desc': 'The boundary where the safety of the village ends and the dense, shadowed trees begin.', 'type': 'district'},
    {'name': 'Ruins of Velkar', 'desc': 'Ancient, crumbling stone structures that predate the town.', 'type': 'dungeon'},
    {'name': 'Abandoned Shrine', 'desc': 'A forgotten altar overgrown with vines, radiating faint magic.', 'type': 'hidden'}
]

with Session(engine) as session:
    ardent = session.exec(select(Location).where(Location.name == 'Ardent Hollow')).first()
    if not ardent:
        print('Ardent Hollow not found!')
    else:
        for s in subs:
            if not session.exec(select(CitySubLocation).where(CitySubLocation.name == s['name'])).first():
                obj = CitySubLocation(
                    name=s['name'],
                    description=s['desc'],
                    city_id=ardent.id,
                    sub_type=s['type'],
                    is_safe_zone=True if s['type'] in ['inn', 'square', 'district'] else False
                )
                session.add(obj)
                print(f"Added {s['name']}")
            else:
                print(f"Already exists: {s['name']}")
        session.commit()
        print('Done seeding tutorial locations.')
