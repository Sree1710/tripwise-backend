from django.conf import settings

def get_route_info(origin, destination):
    """
    Mock or real route info from origin to destination.
    Returns travel time in hours.
    """
    if getattr(settings, "MOCK_API", False):
        return {
            "origin": origin,
            "destination": destination,
            "distance_km": 150,
            "duration_hours": 5.0
        }

    raise NotImplementedError("Google Maps API integration not implemented. Enable MOCK_API for testing.")


def get_places(destination, interests):
    """
    Returns list of POIs for the given destination and interests.
    """
    if getattr(settings, "MOCK_API", False):
        sample_places = [
            {
                "name": "Eravikulam National Park",
                "location": {"lat": 10.2, "lng": 77.0},
                "avg_time": 3,
                "estimated_cost": 420,
                "type": "nature",
                "destination": "Munnar"
            },
            {
                "name": "Tea Museum",
                "location": {"lat": 10.1, "lng": 77.1},
                "avg_time": 2,
                "estimated_cost": 150,
                "type": "museum",
                "destination": "Munnar"
            },
            {
                "name": "Hotel Munnar Inn",
                "location": {"lat": 10.05, "lng": 77.02},
                "avg_time": 0,
                "estimated_cost": 1000,
                "type": "hotel",
                "destination": "Munnar"
            },
            {
                "name": "Green Leaf Restaurant",
                "location": {"lat": 10.06, "lng": 77.03},
                "avg_time": 0,
                "estimated_cost": 300,
                "type": "restaurant",
                "destination": "Munnar"
            },
            {
                "name": "Fort Kochi",
                "location": {"lat": 9.96, "lng": 76.26},
                "avg_time": 3.5,
                "estimated_cost": 0,
                "type": "heritage",
                "destination": "Kochi"
            },
            {
                "name": "Alleppey Backwaters Houseboat",
                "location": {"lat": 9.5, "lng": 76.3},
                "avg_time": 6,
                "estimated_cost": 8000,
                "type": "boating",
                "destination": "Alleppey"
            },
            {
                "name": "Varkala Cliff",
                "location": {"lat": 8.74, "lng": 76.71},
                "avg_time": 2,
                "estimated_cost": 0,
                "type": "beach",
                "destination": "Varkala"
            }
        ]
        return [p for p in sample_places if p["type"] in interests or p["type"] in ("hotel", "restaurant")]

    raise NotImplementedError("Google Places API integration not implemented. Enable MOCK_API for testing.")
