from django.conf import settings

# --- Mock Databases ---

# A mock database of routes, keyed by (origin, destination) tuples.
MOCK_ROUTES = {
    ('trivandrum', 'munnar'): {
        "route": [
            {"step": "Head north on Main Central Rd toward Kottayam."},
            {"step": "From Kottayam, take NH 183 and then the Munnar-Kumily highway."},
            {"step": "Follow the signs through the hills to Munnar town."},
        ],
        "duration_hours": 6.5
    },
    ('kochi', 'munnar'): {
        "route": [
            {"step": "Take NH 85 east from Kochi via Muvattupuzha and Kothamangalam."},
            {"step": "Continue on the scenic route through Adimali."},
            {"step": "Arrive in Munnar."}
        ],
        "duration_hours": 4
    },
    ('trivandrum', 'kochi'): {
        "route": [{"step": "Take NH 66 North for approximately 200km."}],
        "duration_hours": 5
    },
    ('trivandrum', 'alleppey'): {
        "route": [{"step": "Take NH 66 North for approximately 150km."}],
        "duration_hours": 3.5
    },
}

# A mock database of places, organized by destination.
MOCK_PLACES_DATABASE = {
    "munnar": [
        {"name": "Eravikulam National Park", "location": {"lat": 10.158, "lng": 77.045}, "avg_time": 3, "estimated_cost": 420, "type": "nature"},
        {"name": "Mattupetty Dam", "location": {"lat": 10.106, "lng": 77.128}, "avg_time": 1.5, "estimated_cost": 50, "type": "sightseeing"},
        {"name": "Tea Museum", "location": {"lat": 10.088, "lng": 77.049}, "avg_time": 2, "estimated_cost": 150, "type": "museum"},
        {"name": "Rapsy Restaurant", "location": {"lat": 10.087, "lng": 77.059}, "avg_time": 1, "estimated_cost": 500, "type": "restaurant"},
        {"name": "Saravana Bhavan", "location": {"lat": 10.088, "lng": 77.060}, "avg_time": 1, "estimated_cost": 350, "type": "restaurant"},
        {"name": "Budget Hillside Inn", "location": {"lat": 10.08, "lng": 77.06}, "avg_time": 8, "estimated_cost": 1500, "type": "hotel"}, # Add this line
        {"name": "KTDC Tea County", "location": {"lat": 10.091, "lng": 77.070}, "avg_time": 8, "estimated_cost": 5000, "type": "hotel"},
        {"name": "The Panoramic Getaway", "location": {"lat": 10.057, "lng": 77.017}, "avg_time": 8, "estimated_cost": 9500, "type": "hotel"}
    ],
    "kochi": [
        {"name": "Fort Kochi", "location": {"lat": 9.965, "lng": 76.242}, "avg_time": 3, "estimated_cost": 0, "type": "history"},
        {"name": "Chinese Fishing Nets", "location": {"lat": 9.967, "lng": 76.240}, "avg_time": 0.5, "estimated_cost": 0, "type": "sightseeing"},
        {"name": "Paragon Restaurant", "location": {"lat": 10.01, "lng": 76.30}, "avg_time": 1.2, "estimated_cost": 800, "type": "restaurant"},
        {"name": "Grand Hyatt Kochi Bolgatty", "location": {"lat": 9.98, "lng": 76.27}, "avg_time": 8, "estimated_cost": 12000, "type": "hotel"}
    ],
    "trivandrum": [
        {"name": "Kovalam Beach", "location": {"lat": 8.399, "lng": 76.979}, "avg_time": 3, "estimated_cost": 0, "type": "nature"},
        {"name": "Napier Museum", "location": {"lat": 8.508, "lng": 76.953}, "avg_time": 2, "estimated_cost": 100, "type": "museum"},
        {"name": "Padmanabhaswamy Temple", "location": {"lat": 8.483, "lng": 76.943}, "avg_time": 1.5, "estimated_cost": 0, "type": "history"},
        {"name": "Villa Maya", "location": {"lat": 8.487, "lng": 76.940}, "avg_time": 1.5, "estimated_cost": 2500, "type": "restaurant"},
        {"name": "Hyatt Regency Trivandrum", "location": {"lat": 8.514, "lng": 76.949}, "avg_time": 8, "estimated_cost": 9000, "type": "hotel"}
    ],
    "alleppey": [
        {"name": "Alleppey Backwaters Houseboat", "location": {"lat": 9.498, "lng": 76.333}, "avg_time": 6, "estimated_cost": 8000, "type": "sightseeing"},
        {"name": "Marari Beach", "location": {"lat": 9.600, "lng": 76.300}, "avg_time": 2.5, "estimated_cost": 0, "type": "nature"},
        {"name": "Thaff Restaurant", "location": {"lat": 9.503, "lng": 76.340}, "avg_time": 1, "estimated_cost": 400, "type": "restaurant"},
        {"name": "Ramada by Wyndham Alleppey", "location": {"lat": 9.508, "lng": 76.338}, "avg_time": 8, "estimated_cost": 6500, "type": "hotel"}
    ]
}


# --- Mock API Functions ---

def get_route_info(origin, destination):
    """
    Looks up a route from the MOCK_ROUTES dictionary to simulate a real API.
    """
    if settings.MOCK_API:
        # Match the route using lowercase keys.
        route_key = (origin.lower(), destination.lower())
        return MOCK_ROUTES.get(route_key, {
            "route": [],
            "duration_hours": 0
        })

    # Real API logic would go here
    return {"route": [], "duration_hours": 0}


def get_places(destination, interests):
    """
    Looks up places from the MOCK_PLACES_DATABASE based on destination and interests.
    Note: The original function signature `(route_steps, interests)` has been updated
    to `(destination, interests)` for better utility.
    """
    if settings.MOCK_API:
        # Get all places for the requested destination, matching in lowercase.
        places_for_destination = MOCK_PLACES_DATABASE.get(destination.lower(), [])

        # If no specific interests are provided, return all places for that destination.
        if not interests:
            return places_for_destination

        # Filter places based on interests, but always include hotels and restaurants
        # as the main itinerary logic often depends on them.
        filtered_places = [
            place for place in places_for_destination
            if place['type'] in interests or place['type'] in ['hotel', 'restaurant']
        ]
        return filtered_places

    # Real API logic would go here
    return []