import requests
from django.conf import settings
from urllib.parse import urlencode


class GoogleAPIError(Exception):
    pass


def get_route_info(origin, destination):
    """
    Get route information using Google Directions API or mock data.
    """
    if getattr(settings, "MOCK_API", False):
        return {
            "origin": origin,
            "destination": destination,
            "distance_km": 150,
            "duration_hours": 5.0
        }

    try:
        api_key = getattr(settings, 'GOOGLE_MAPS_API_KEY', None)
        if not api_key:
            raise GoogleAPIError("Google Maps API key not configured")

        # Google Directions API
        base_url = "https://maps.googleapis.com/maps/api/directions/json"
        params = {
            'origin': origin,
            'destination': destination,
            'key': api_key,
            'mode': 'driving',
            'units': 'metric',
            'region': 'in'  # Bias results towards India
        }
        
        response = requests.get(base_url, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        if data['status'] != 'OK' or not data['routes']:
            raise GoogleAPIError(f"No routes found: {data.get('status', 'Unknown error')}")
        
        route = data['routes'][0]['legs'][0]
        
        return {
            "origin": origin,
            "destination": destination,
            "distance_km": round(route['distance']['value'] / 1000, 2),
            "duration_hours": round(route['duration']['value'] / 3600, 2)
        }
        
    except (requests.RequestException, KeyError, GoogleAPIError) as e:
        print(f"Google Directions API error: {e}")
        # Fallback to mock data on error
        return {
            "origin": origin,
            "destination": destination,
            "distance_km": 150,
            "duration_hours": 5.0
        }


def get_places(destination, interests):
    """
    Get places using Google Places API or mock data.
    """
    if getattr(settings, "MOCK_API", False):
        return get_mock_places(destination, interests)

    try:
        api_key = getattr(settings, 'GOOGLE_MAPS_API_KEY', None)
        if not api_key:
            raise GoogleAPIError("Google Maps API key not configured")

        all_places = []
        
        # Search for different types of places
        place_types = {
            'nature': ['park', 'natural_feature', 'zoo'],
            'heritage': ['museum', 'tourist_attraction', 'place_of_worship'],
            'adventure': ['amusement_park', 'tourist_attraction'],
            'beach': ['natural_feature', 'tourist_attraction'],
            'culture': ['museum', 'art_gallery', 'tourist_attraction'],
            'food': ['restaurant', 'cafe', 'meal_takeaway'],
            'hotel': ['lodging'],
            'restaurant': ['restaurant', 'food', 'cafe']
        }
        
        # Get coordinates for the destination first
        destination_coords = get_destination_coordinates(destination, api_key)
        
        for interest in interests + ['hotel', 'restaurant']:
            search_types = place_types.get(interest, ['tourist_attraction'])
            
            for place_type in search_types:
                places = search_places_by_type(destination, destination_coords, place_type, api_key)
                
                for place in places:
                    place['type'] = map_place_type_to_interest(place_type, interest)
                    place['destination'] = destination
                    all_places.append(place)
        
        # Remove duplicates and limit results
        seen_names = set()
        unique_places = []
        for place in all_places:
            if place['name'] not in seen_names:
                seen_names.add(place['name'])
                unique_places.append(place)
        
        return unique_places[:20]  # Limit to 20 places
        
    except Exception as e:
        print(f"Google Places API error: {e}")
        # Fallback to mock data instead of empty list
        return get_mock_places(destination, interests)


def get_destination_coordinates(destination, api_key):
    """Get latitude and longitude for a destination with fallbacks."""
    try:
        base_url = "https://maps.googleapis.com/maps/api/geocoding/json"
        params = {
            'address': destination + ", India",  # Better for Indian locations
            'key': api_key,
            'region': 'in'  # Bias towards India
        }
        
        response = requests.get(base_url, params=params, timeout=10)
        data = response.json()
        
        if data['status'] == 'OK' and data['results']:
            location = data['results'][0]['geometry']['location']
            return {"lat": location['lat'], "lng": location['lng']}
        
    except Exception as e:
        print(f"Geocoding error: {e}")
    
    # Fallback coordinates for major Indian destinations
    default_coords = {
        'mumbai': {"lat": 19.0760, "lng": 72.8777},
        'delhi': {"lat": 28.7041, "lng": 77.1025},
        'bangalore': {"lat": 12.9716, "lng": 77.5946},
        'kochi': {"lat": 9.9312, "lng": 76.2673},
        'trivandrum': {"lat": 8.5241, "lng": 76.9366},
        'chennai': {"lat": 13.0827, "lng": 80.2707},
        'kolkata': {"lat": 22.5726, "lng": 88.3639},
        'goa': {"lat": 15.2993, "lng": 74.1240},
        'munnar': {"lat": 10.0889, "lng": 77.0595},
        'alleppey': {"lat": 9.4981, "lng": 76.3388},
        'thekkady': {"lat": 9.46, "lng": 77.15},
        'kumarakom': {"lat": 9.61, "lng": 76.43},
        'varkala': {"lat": 8.74, "lng": 76.71},
        'wayanad': {"lat": 11.6054, "lng": 76.0870}
    }
    
    destination_lower = destination.lower()
    for city, coords in default_coords.items():
        if city in destination_lower:
            return coords
    
    # Default coordinates (Kochi, Kerala)
    return {"lat": 9.9312, "lng": 76.2673}


def search_places_by_type(destination, coords, place_type, api_key):
    """Search for places of a specific type near destination."""
    try:
        base_url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
        params = {
            'location': f"{coords['lat']},{coords['lng']}",
            'radius': 25000,  # 25km radius
            'type': place_type,
            'key': api_key
        }
        
        response = requests.get(base_url, params=params, timeout=10)
        data = response.json()
        
        places = []
        if data['status'] == 'OK':
            for place in data.get('results', [])[:5]:  # Limit to 5 per type
                # Skip places with very low ratings
                if place.get('rating', 0) < 3.0 and place.get('user_ratings_total', 0) > 10:
                    continue
                    
                # Estimate cost and time based on place type and rating
                estimated_cost = estimate_place_cost(place, place_type)
                avg_time = estimate_visit_time(place_type)
                
                place_data = {
                    'name': place['name'],
                    'location': {
                        'lat': place['geometry']['location']['lat'],
                        'lng': place['geometry']['location']['lng']
                    },
                    'avg_time': avg_time,
                    'estimated_cost': estimated_cost,
                    'rating': place.get('rating', 0),
                    'place_id': place['place_id'],
                    'price_level': place.get('price_level', 2),
                    'user_ratings_total': place.get('user_ratings_total', 0)
                }
                
                # Add additional details if available
                if 'photos' in place:
                    place_data['has_photos'] = True
                
                if 'opening_hours' in place:
                    place_data['is_open'] = place['opening_hours'].get('open_now', True)
                
                places.append(place_data)
        
        return places
        
    except Exception as e:
        print(f"Places search error: {e}")
        return []


def map_place_type_to_interest(place_type, interest):
    """Map Google place type back to our interest categories."""
    type_mapping = {
        'lodging': 'hotel',
        'restaurant': 'restaurant',
        'cafe': 'restaurant',
        'food': 'restaurant',
        'meal_takeaway': 'restaurant',
        'tourist_attraction': interest,
        'museum': 'heritage',
        'place_of_worship': 'heritage',
        'art_gallery': 'heritage',
        'park': 'nature',
        'natural_feature': 'nature',
        'zoo': 'nature',
        'amusement_park': 'adventure'
    }
    return type_mapping.get(place_type, interest)


def estimate_place_cost(place, place_type):
    """Enhanced cost estimation with price_level and rating."""
    # Base costs in INR (updated for 2025 rates)
    base_costs = {
        'lodging': 2500,
        'restaurant': 500,
        'cafe': 300,
        'food': 400,
        'meal_takeaway': 250,
        'tourist_attraction': 200,
        'museum': 150,
        'park': 50,
        'natural_feature': 0,
        'amusement_park': 800,
        'place_of_worship': 0,
        'zoo': 300,
        'art_gallery': 100
    }
    
    base_cost = base_costs.get(place_type, 100)
    
    # Use Google's price_level if available (0-4 scale)
    price_level = place.get('price_level', 2)  # Default to moderate
    price_multipliers = {0: 0.5, 1: 0.7, 2: 1.0, 3: 1.5, 4: 2.0}
    price_multiplier = price_multipliers.get(price_level, 1.0)
    
    # Adjust based on rating
    rating = place.get('rating', 3.5)
    if rating >= 4.5:
        rating_multiplier = 1.2
    elif rating >= 4.0:
        rating_multiplier = 1.1
    else:
        rating_multiplier = 0.9
    
    final_cost = int(base_cost * price_multiplier * rating_multiplier)
    return max(0, final_cost)


def estimate_visit_time(place_type):
    """Estimate average visit time based on place type."""
    time_estimates = {
        'lodging': 0,           # Accommodation, not visit time
        'restaurant': 1,        # 1 hour for meal
        'cafe': 0.5,           # 30 minutes
        'food': 1,             # 1 hour for meal
        'meal_takeaway': 0.3,  # 20 minutes
        'tourist_attraction': 2.5,  # 2.5 hours average
        'museum': 2,           # 2 hours
        'park': 3,             # 3 hours
        'natural_feature': 2.5,    # 2.5 hours
        'amusement_park': 5,   # 5 hours
        'place_of_worship': 1, # 1 hour
        'zoo': 4,              # 4 hours
        'art_gallery': 1.5     # 1.5 hours
    }
    
    return time_estimates.get(place_type, 2)


def get_place_details(place_id, api_key):
    """Get detailed information about a specific place."""
    try:
        base_url = "https://maps.googleapis.com/maps/api/place/details/json"
        params = {
            'place_id': place_id,
            'key': api_key,
            'fields': 'name,formatted_address,formatted_phone_number,website,opening_hours,price_level,rating,reviews,photos'
        }
        
        response = requests.get(base_url, params=params, timeout=10)
        data = response.json()
        
        if data['status'] == 'OK':
            return data['result']
            
    except Exception as e:
        print(f"Place details error: {e}")
    
    return None


def get_mock_places(destination, interests):
    """Comprehensive mock data for testing and fallback."""
    sample_places = [
        # Munnar
        {
            "name": "Eravikulam National Park",
            "location": {"lat": 10.2, "lng": 77.0},
            "avg_time": 3,
            "estimated_cost": 420,
            "type": "nature",
            "destination": "Munnar",
            "rating": 4.5,
            "price_level": 1,
            "user_ratings_total": 2847,
            "place_id": "mock_eravikulam"
        },
        {
            "name": "Tea Museum",
            "location": {"lat": 10.1, "lng": 77.1},
            "avg_time": 2,
            "estimated_cost": 150,
            "type": "heritage",
            "destination": "Munnar",
            "rating": 4.2,
            "price_level": 1,
            "user_ratings_total": 1653,
            "place_id": "mock_tea_museum"
        },
        {
            "name": "Hotel Munnar Inn",
            "location": {"lat": 10.05, "lng": 77.02},
            "avg_time": 0,
            "estimated_cost": 2500,
            "type": "hotel",
            "destination": "Munnar",
            "rating": 4.0,
            "price_level": 2,
            "user_ratings_total": 945,
            "place_id": "mock_munnar_inn"
        },
        {
            "name": "Green Leaf Restaurant",
            "location": {"lat": 10.06, "lng": 77.03},
            "avg_time": 1,
            "estimated_cost": 400,
            "type": "restaurant",
            "destination": "Munnar",
            "rating": 4.1,
            "price_level": 2,
            "user_ratings_total": 728,
            "place_id": "mock_green_leaf"
        },
        # Kochi
        {
            "name": "Fort Kochi",
            "location": {"lat": 9.96, "lng": 76.26},
            "avg_time": 3.5,
            "estimated_cost": 0,
            "type": "heritage",
            "destination": "Kochi",
            "rating": 4.3,
            "price_level": 0,
            "user_ratings_total": 3521,
            "place_id": "mock_fort_kochi"
        },
        {
            "name": "Mattancherry Palace",
            "location": {"lat": 9.958, "lng": 76.259},
            "avg_time": 1.5,
            "estimated_cost": 15,
            "type": "heritage",
            "destination": "Kochi",
            "rating": 4.1,
            "price_level": 0,
            "user_ratings_total": 2134,
            "place_id": "mock_mattancherry"
        },
        # Alleppey
        {
            "name": "Alleppey Backwaters Houseboat",
            "location": {"lat": 9.5, "lng": 76.3},
            "avg_time": 6,
            "estimated_cost": 8000,
            "type": "adventure",
            "destination": "Alleppey",
            "rating": 4.6,
            "price_level": 3,
            "user_ratings_total": 1876,
            "place_id": "mock_backwaters"
        },
        # Varkala
        {
            "name": "Varkala Cliff",
            "location": {"lat": 8.74, "lng": 76.71},
            "avg_time": 2,
            "estimated_cost": 0,
            "type": "beach",
            "destination": "Varkala",
            "rating": 4.4,
            "price_level": 0,
            "user_ratings_total": 2967,
            "place_id": "mock_varkala_cliff"
        },
        # Thekkady
        {
            "name": "Periyar Wildlife Sanctuary",
            "location": {"lat": 9.46, "lng": 77.15},
            "avg_time": 4,
            "estimated_cost": 300,
            "type": "nature",
            "destination": "Thekkady",
            "rating": 4.2,
            "price_level": 1,
            "user_ratings_total": 3245,
            "place_id": "mock_periyar"
        },
        # Kumarakom
        {
            "name": "Kumarakom Bird Sanctuary",
            "location": {"lat": 9.61, "lng": 76.43},
            "avg_time": 2.5,
            "estimated_cost": 100,
            "type": "nature",
            "destination": "Kumarakom",
            "rating": 4.0,
            "price_level": 1,
            "user_ratings_total": 1432,
            "place_id": "mock_bird_sanctuary"
        },
        # Hotels
        {
            "name": "Taj Malabar Resort & Spa",
            "location": {"lat": 9.96, "lng": 76.26},
            "avg_time": 0,
            "estimated_cost": 8000,
            "type": "hotel",
            "destination": "Kochi",
            "rating": 4.7,
            "price_level": 4,
            "user_ratings_total": 2156,
            "place_id": "mock_taj_malabar"
        },
        {
            "name": "Coconut Creek Resort",
            "location": {"lat": 9.61, "lng": 76.43},
            "avg_time": 0,
            "estimated_cost": 4500,
            "type": "hotel",
            "destination": "Kumarakom",
            "rating": 4.5,
            "price_level": 3,
            "user_ratings_total": 1087,
            "place_id": "mock_coconut_creek"
        },
        # Restaurants
        {
            "name": "Dhe Puttu",
            "location": {"lat": 9.96, "lng": 76.26},
            "avg_time": 1,
            "estimated_cost": 600,
            "type": "restaurant",
            "destination": "Kochi",
            "rating": 4.3,
            "price_level": 2,
            "user_ratings_total": 3476,
            "place_id": "mock_dhe_puttu"
        },
        {
            "name": "Thaff Restaurant",
            "location": {"lat": 8.74, "lng": 76.71},
            "avg_time": 1,
            "estimated_cost": 450,
            "type": "restaurant",
            "destination": "Varkala",
            "rating": 4.2,
            "price_level": 2,
            "user_ratings_total": 1298,
            "place_id": "mock_thaff"
        }
    ]
    
    # Filter based on interests and destination
    filtered_places = []
    for place in sample_places:
        if (place["type"] in interests or 
            place["type"] in ("hotel", "restaurant") or
            destination.lower() in place["destination"].lower()):
            filtered_places.append(place)
    
    return filtered_places


def search_text_places(query, api_key):
    """Search places using text query (useful for specific searches)."""
    try:
        base_url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
        params = {
            'query': query,
            'key': api_key,
            'region': 'in'
        }
        
        response = requests.get(base_url, params=params, timeout=10)
        data = response.json()
        
        places = []
        if data['status'] == 'OK':
            for place in data.get('results', [])[:10]:  # Limit results
                places.append({
                    'name': place['name'],
                    'location': {
                        'lat': place['geometry']['location']['lat'],
                        'lng': place['geometry']['location']['lng']
                    },
                    'rating': place.get('rating', 0),
                    'place_id': place['place_id'],
                    'formatted_address': place.get('formatted_address', ''),
                    'price_level': place.get('price_level', 2)
                })
        
        return places
        
    except Exception as e:
        print(f"Text search error: {e}")
        return []
