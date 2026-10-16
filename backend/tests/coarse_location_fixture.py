from datetime import timedelta
from life_prototype.coarse_locations import advance


def depart(test, destination, ident='departure'):
    origin=test.p.snapshot()['place']
    test.item.update(id=ident,kind='commute',state_type='commuting',activity='moving',
        place=origin,destination=destination,coarse_place=origin,coarse_destination=destination,
        start_at=test.clock.now().isoformat(),end_at=(test.clock.now()+timedelta(minutes=20)).isoformat())
    advance(test.cog)
