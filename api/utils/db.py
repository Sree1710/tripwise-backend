import os
from django.conf import settings
from api.models import PointOfInterest

def get_hidden_spots(destination, interests):
    """
    Fetch hidden/unpopular spots for a destination filtered by user interests.
    Uses mock data if MOCK_API=True in settings.py.
    """
    if getattr(settings, "MOCK_API", False):
        # Return mock data
        return [
            {
                "name": "Secret Forest Trail",
                "location": {"lat": 10.1, "lng": 77.3},
                "avg_time": 2,
                "estimated_cost": 150,
                "type": "nature"
            },
            {
                "name": "Hidden Waterfall Cave",
                "location": {"lat": 10.12, "lng": 77.35},
                "avg_time": 1.5,
                "estimated_cost": 100,
                "type": "adventure"
            }
        ]
    
    # Fetch from MongoDB (non-mock)
    all_spots = PointOfInterest.objects(destination=destination).all()
    hidden_spots = []

    for spot in all_spots:
        # Consider spots with less popular tags as "hidden"
        if any(tag in interests for tag in spot.tags):
            if "hidden" in spot.tags or "secret" in spot.name.lower() or spot.estimated_cost < 100:
                hidden_spots.append({
                    "name": spot.name,
                    "location": {"lat": 10.0, "lng": 77.0},  # Default or randomize if needed
                    "avg_time": spot.avg_time,
                    "estimated_cost": spot.estimated_cost,
                    "type": spot.tags[0] if spot.tags else "general"
                })

    return hidden_spots
