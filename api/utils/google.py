from django.conf import settings

def get_route_info(origin, destination):
    if settings.MOCK_API:
        return {
            "route": [{"step": "Mock step data"}],
            "duration_hours": 3.5
        }
    # TODO: Real Google Directions API logic
    ...

def get_places(route_steps, interests):
    if settings.MOCK_API:
        return [
            {"name": "Rose Garden", "location": {"lat": 10.1, "lng": 77.2}, "avg_time": 1.5, "estimated_cost": 300, "type": "nature"},
            {"name": "Hill Viewpoint", "location": {"lat": 10.11, "lng": 77.1}, "avg_time": 1, "estimated_cost": 100, "type": "nature"},
            {"name": "Munnar Spice Restaurant", "location": {"lat": 10.12, "lng": 77.11}, "avg_time": 1, "estimated_cost": 250, "type": "restaurant"},
            {"name": "Green Valley Hotel", "location": {"lat": 10.13, "lng": 77.12}, "avg_time": 8, "estimated_cost": 1500, "type": "hotel"}
        ]
    # TODO: Real Google Places API logic
    ...
