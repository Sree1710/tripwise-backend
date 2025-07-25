from django.conf import settings

def get_route_info(origin, destination):
    if settings.MOCK_API:
        return {
            "route": [
                {"step": "Head north"},
                {"step": "Turn right onto Main Street"},
                {"step": "Continue for 2 km"},
                {"step": "Arrive at your destination"}
            ],
            "duration_hours": 3.5
        }

    # Real API logic would go here (currently skipped)
    return {
        "route": [],
        "duration_hours": 0
    }

def get_places(route_steps, interests):
    if settings.MOCK_API:
        return [
            {"name": "Rose Garden", "location": {"lat": 10.1, "lng": 77.2}, "avg_time": 1.5, "estimated_cost": 300, "type": "nature"},
            {"name": "Hill Viewpoint", "location": {"lat": 10.11, "lng": 77.1}, "avg_time": 1, "estimated_cost": 100, "type": "nature"},
            {"name": "Secret Forest Trail", "location": {"lat": 10.13, "lng": 77.3}, "avg_time": 2, "estimated_cost": 0, "type": "nature"},
            {"name": "Munnar Spice Restaurant", "location": {"lat": 10.12, "lng": 77.11}, "avg_time": 1, "estimated_cost": 250, "type": "restaurant"},
            {"name": "Green Valley Hotel", "location": {"lat": 10.13, "lng": 77.12}, "avg_time": 8, "estimated_cost": 1500, "type": "hotel"},
            {"name": "Blue Pine Resort", "location": {"lat": 10.14, "lng": 77.13}, "avg_time": 8, "estimated_cost": 1300, "type": "hotel"}
        ]

    # Real API logic would go here (currently skipped)
    return []
