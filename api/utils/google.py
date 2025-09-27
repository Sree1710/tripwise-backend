# import json
import requests
import time
from django.conf import settings
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError


class GeocodeError(Exception):
    pass


def get_route_info(origin, destination):
    """
    Get route information using OSRM (Open Source Routing Machine) or mock data.
    """
    if getattr(settings, "MOCK_API", False):
        return {
            "origin": origin,
            "destination": destination,
            "distance_km": 150,
            "duration_hours": 5.0
        }

    try:
        # Get coordinates for both locations using OSM
        origin_coords = get_destination_coordinates(origin)
        dest_coords = get_destination_coordinates(destination)
        
        # OSRM API (free, open source routing)
        osrm_url = "http://router.project-osrm.org/route/v1/driving"
        coords = f"{origin_coords['lng']},{origin_coords['lat']};{dest_coords['lng']},{dest_coords['lat']}"
        
        response = requests.get(f"{osrm_url}/{coords}?overview=false", timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            
            if data['code'] == 'Ok' and data['routes']:
                route = data['routes'][0]
                
                return {
                    "origin": origin,
                    "destination": destination,
                    "distance_km": round(route['distance'] / 1000, 2),
                    "duration_hours": round(route['duration'] / 3600, 2)
                }
        
    except Exception as e:
        print(f"OSRM routing error: {e}")
    
    # Fallback to mock data on error
    return {
        "origin": origin,
        "destination": destination,
        "distance_km": 150,
        "duration_hours": 5.0
    }


def get_places(destination, interests):
    """
    Get places using OpenStreetMap Overpass API or mock data.
    """
    if getattr(settings, "MOCK_API", False):
        return get_mock_places(destination, interests)

    try:
        # Get destination coordinates first
        coords = get_destination_coordinates(destination)
        
        all_places = []
        
        # Define OpenStreetMap tags for different interests
        osm_tags = {
            'nature': ['leisure=park', 'natural=*', 'tourism=zoo'],
            'heritage': ['tourism=museum', 'tourism=attraction', 'amenity=place_of_worship'],
            'adventure': ['tourism=theme_park', 'leisure=water_park'],
            'beach': ['natural=beach', 'leisure=beach_resort'],
            'culture': ['tourism=museum', 'tourism=gallery'],
            'food': ['amenity=restaurant', 'amenity=cafe'],
            'hotel': ['tourism=hotel', 'tourism=guest_house'],
            'restaurant': ['amenity=restaurant', 'amenity=fast_food', 'amenity=cafe']
        }
        
        for interest in interests + ['hotel', 'restaurant']:
            if interest in osm_tags:
                interest_places = search_overpass_api(coords, osm_tags[interest], destination, interest)
                all_places.extend(interest_places)
        
        # Remove duplicates and limit results
        seen_names = set()
        unique_places = []
        for place in all_places:
            if place['name'] not in seen_names:
                seen_names.add(place['name'])
                unique_places.append(place)
        
        return unique_places[:20]  # Limit to 20 places
        
    except Exception as e:
        print(f"OSM Places API error: {e}")
        # Fallback to mock data instead of empty list
        return get_mock_places(destination, interests)


def get_destination_coordinates(destination, api_key=None):
    """Get latitude and longitude for a destination using OpenStreetMap Nominatim."""
    try:
        # Initialize Nominatim with a unique user agent (required by Nominatim)
        geolocator = Nominatim(user_agent="travel_booking_app_kerala_v1")
        
        # Add India bias for better results
        location = geolocator.geocode(f"{destination}, India", timeout=10)
        
        if location:
            print(f"Successfully geocoded {destination}: {location.latitude}, {location.longitude}")
            return {
                "lat": location.latitude, 
                "lng": location.longitude
            }
        else:
            print(f"No results found for {destination} using Nominatim")
            
    except (GeocoderTimedOut, GeocoderServiceError) as e:
        print(f"Nominatim geocoding error: {e}")
    except Exception as e:
        print(f"Unexpected geocoding error: {e}")
    
    # Fallback coordinates for major Indian destinations (unchanged)
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


def search_overpass_api(coords, tags, destination, interest_type):
    """Search OpenStreetMap using Overpass API for places."""
    places = []
    
    try:
        # Overpass API endpoint
        overpass_url = "http://overpass-api.de/api/interpreter"
        
        # Build query for each tag (limit to avoid timeout)
        for tag in tags[:2]:  # Limit to 2 tags per interest
            # Search within 25km radius
            query = f"""
            [out:json][timeout:25];
            (
              node[{tag}](around:25000,{coords['lat']},{coords['lng']});
              way[{tag}](around:25000,{coords['lat']},{coords['lng']});
              relation[{tag}](around:25000,{coords['lat']},{coords['lng']});
            );
            out center meta;
            """
            
            response = requests.post(overpass_url, data=query, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                
                for element in data.get('elements', [])[:5]:  # Limit to 5 per tag
                    if 'tags' in element and 'name' in element['tags']:
                        # Get coordinates
                        if element['type'] == 'node':
                            lat, lng = element['lat'], element['lon']
                        elif 'center' in element:
                            lat, lng = element['center']['lat'], element['center']['lon']
                        else:
                            continue
                        
                        place = {
                            'name': element['tags']['name'],
                            'location': {'lat': lat, 'lng': lng},
                            'avg_time': estimate_visit_time_from_osm_tag(tag),
                            'estimated_cost': estimate_cost_from_osm_tag(tag),
                            'type': interest_type,
                            'destination': destination,
                            'rating': 4.0,  # Default rating for OSM places
                            'place_id': f"osm_{element['type']}_{element['id']}",
                            'price_level': 2,
                            'user_ratings_total': 100  # Default value
                        }
                        
                        # Add additional OSM-specific data if available
                        if 'website' in element['tags']:
                            place['has_website'] = True
                        if 'phone' in element['tags']:
                            place['has_phone'] = True
                            
                        places.append(place)
            
            # Respect Overpass API rate limits
            time.sleep(1)
            
    except Exception as e:
        print(f"Overpass API error for {interest_type}: {e}")
    
    return places


def estimate_visit_time_from_osm_tag(tag):
    """Estimate visit time based on OSM tag."""
    time_mapping = {
        'tourism=museum': 2,
        'leisure=park': 3,
        'tourism=zoo': 4,
        'amenity=restaurant': 1,
        'amenity=cafe': 0.5,
        'tourism=hotel': 0,
        'tourism=guest_house': 0,
        'natural=beach': 3,
        'tourism=attraction': 2.5,
        'amenity=place_of_worship': 1,
        'tourism=theme_park': 5,
        'tourism=gallery': 1.5
    }
    
    # Handle wildcard matches
    if tag.startswith('natural='):
        return 2.5
    
    return time_mapping.get(tag, 2)


def estimate_cost_from_osm_tag(tag):
    """Estimate cost based on OSM tag (2025 rates)."""
    cost_mapping = {
        'tourism=museum': 150,
        'leisure=park': 50,
        'tourism=zoo': 300,
        'amenity=restaurant': 500,
        'amenity=cafe': 300,
        'amenity=fast_food': 250,
        'tourism=hotel': 2500,
        'tourism=guest_house': 1500,
        'natural=beach': 0,
        'tourism=attraction': 200,
        'amenity=place_of_worship': 0,
        'tourism=theme_park': 800,
        'tourism=gallery': 100
    }
    
    # Handle wildcard matches
    if tag.startswith('natural='):
        return 50  # Most natural features are free or low cost
    
    return cost_mapping.get(tag, 100)


def search_places_by_type(destination, coords, place_type, api_key):
    """Legacy function - now redirects to OSM-based search."""
    # Map old Google place types to OSM tags
    google_to_osm = {
        'park': ['leisure=park'],
        'natural_feature': ['natural=*'],
        'zoo': ['tourism=zoo'],
        'museum': ['tourism=museum'],
        'tourist_attraction': ['tourism=attraction'],
        'place_of_worship': ['amenity=place_of_worship'],
        'restaurant': ['amenity=restaurant'],
        'cafe': ['amenity=cafe'],
        'lodging': ['tourism=hotel'],
        'art_gallery': ['tourism=gallery'],
        'amusement_park': ['tourism=theme_park']
    }
    
    tags = google_to_osm.get(place_type, ['tourism=attraction'])
    return search_overpass_api(coords, tags, destination, place_type)


def map_place_type_to_interest(place_type, interest):
    """Map place type back to our interest categories (unchanged)."""
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
    """Enhanced cost estimation (unchanged for compatibility)."""
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
    
    # Use price_level if available (0-4 scale)
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
    """Estimate average visit time based on place type (unchanged)."""
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


def get_place_details(place_id, api_key=None):
    """Get detailed information about a specific place - OSM version."""
    try:
        if place_id.startswith('osm_'):
            # For OSM places, we have limited detail capability
            # Could integrate with additional OSM services if needed
            return {
                'name': 'OSM Place',
                'formatted_address': 'Address from OpenStreetMap',
                'rating': 4.0,
                'source': 'OpenStreetMap'
            }
            
    except Exception as e:
        print(f"Place details error: {e}")
    
    return None


def get_mock_places(destination, interests):
    """Comprehensive mock data for testing and fallback (unchanged)."""
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


def search_text_places(query, api_key=None):
    """Search places using Nominatim text search."""
    try:
        geolocator = Nominatim(user_agent="travel_booking_app_kerala_v1")
        locations = geolocator.geocode(query, exactly_one=False, limit=10, timeout=10)
        
        places = []
        if locations:
            for location in locations[:10]:
                places.append({
                    'name': location.address.split(',')[0],
                    'location': {
                        'lat': location.latitude,
                        'lng': location.longitude
                    },
                    'rating': 4.0,  # Default rating
                    'place_id': f"osm_text_{hash(location.address)}",
                    'formatted_address': location.address,
                    'price_level': 2
                })
        
        return places
        
    except Exception as e:
        print(f"Text search error: {e}")
        return []
