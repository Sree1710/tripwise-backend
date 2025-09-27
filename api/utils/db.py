import os
import requests
from django.conf import settings
from api.models import PointOfInterest
from pymongo import MongoClient

def get_hidden_spots(destination, interests):
    """
    Fetch hidden/unpopular spots for a destination filtered by user interests.
    Uses mock data if MOCK_API=True in settings.py.
    """
    if getattr(settings, "MOCK_API", False):
        # Your existing mock data
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
    
    try:
        # Live MongoDB query with enhanced filtering
        all_spots = PointOfInterest.objects(destination=destination).all()
        hidden_spots = []

        for spot in all_spots:
            # Enhanced criteria for "hidden" spots
            is_hidden = (
                "hidden" in spot.tags or 
                "secret" in spot.tags or 
                "offbeat" in spot.tags
            )
            
            # Check if spot matches user interests
            if any(tag in interests for tag in spot.tags) and is_hidden:
                hidden_spots.append({
                    "name": spot.name,
                    "location": {
                        "lat": float(spot.location.get('lat', 10.0)), 
                        "lng": float(spot.location.get('lng', 77.0))
                    },
                    "avg_time": spot.avg_time,
                    "estimated_cost": spot.estimated_cost,
                    "type": spot.tags[0] if spot.tags else "general",
                    "description": getattr(spot, 'description', ''),
                    "rating": getattr(spot, 'rating', 0)
                })

        return hidden_spots[:10]  # Limit to top 10 hidden spots
        
    except Exception as e:
        print(f"Database error: {e}")
        return []  # Return empty list on database error
