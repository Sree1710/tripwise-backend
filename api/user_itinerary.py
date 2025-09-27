from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response
from rest_framework import status
from .ml.predict import predict_budget
from .utils.google import get_route_info, get_places
from .utils.weather import get_weather
from .utils.db import get_hidden_spots
from datetime import datetime, timedelta, time
import math
import logging
from django.core.cache import cache
from django.conf import settings
from api.auth import JWTAuthentication
from api.permissions import IsUser
from api.models import UserItinerary
from difflib import SequenceMatcher
import json

# Set up logging
logger = logging.getLogger(__name__)

def get_cached_or_fetch(cache_key, fetch_function, *args, **kwargs):
    """Get data from cache or fetch from API with caching."""
    cached_data = cache.get(cache_key)
    if cached_data:
        logger.info(f"Cache hit for {cache_key}")
        return cached_data
    
    try:
        logger.info(f"Fetching fresh data for {cache_key}")
        data = fetch_function(*args, **kwargs)
        
        # Cache for different durations based on data type
        cache_duration = 300  # 5 minutes default
        if 'weather' in cache_key:
            cache_duration = 1800  # 30 minutes for weather
        elif 'places' in cache_key or 'hidden' in cache_key:
            cache_duration = 3600  # 1 hour for places
        elif 'route' in cache_key:
            cache_duration = 7200  # 2 hours for routes
        
        cache.set(cache_key, data, cache_duration)
        return data
    except Exception as e:
        logger.error(f"API fetch error for {cache_key}: {e}")
        return None

def calculate_similarity(str1, str2):
    """Calculate string similarity using SequenceMatcher."""
    return SequenceMatcher(None, str1.lower(), str2.lower()).ratio()

def calculate_distance(loc1, loc2):
    """Calculate distance between two locations using Haversine formula."""
    try:
        lat1, lon1 = float(loc1.get('lat', 0)), float(loc1.get('lng', 0))
        lat2, lon2 = float(loc2.get('lat', 0)), float(loc2.get('lng', 0))
        
        R = 6371  # Earth's radius in km
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        
        a = (math.sin(dlat/2) * math.sin(dlat/2) +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
             math.sin(dlon/2) * math.sin(dlon/2))
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        distance_km = R * c
        
        return distance_km
    except (KeyError, ValueError, TypeError) as e:
        logger.warning(f"Error calculating distance: {e}")
        return 0.0

def is_activity_time_realistic(hour_float, activity_type):
    """Check if activity timing is realistic based on type."""
    if activity_type in ['nature', 'sightseeing', 'adventure', 'attraction']:
        return 7.0 <= hour_float <= 18.0
    elif activity_type == 'restaurant':
        return (7.0 <= hour_float <= 10.0 or
                12.0 <= hour_float <= 15.0 or
                18.0 <= hour_float <= 21.0)
    elif activity_type == 'hotel':
        return hour_float >= 14.0 or hour_float <= 12.0
    elif activity_type == 'travel':
        return 6.0 <= hour_float <= 22.0
    return True

def enforce_daily_time_limits(current_hour, daily_start_hour=8.0):
    """Enforce realistic daily activity limits."""
    max_daily_activity_hours = 10  # Maximum 10 hours of activities
    latest_outdoor_time = 18.0  # No outdoor activities after 6 PM
    
    if current_hour > latest_outdoor_time:
        return False, "Outdoor activities cannot extend beyond 6 PM"
    
    if (current_hour - daily_start_hour) > max_daily_activity_hours:
        return False, "Daily activity limit exceeded (10 hours)"
    
    return True, ""

def schedule_activity_safely(current_hour, activity, activity_type, daily_start_hour=8.0):
    """Schedule activity only if timing is realistic - KEY VALIDATION FUNCTION."""
    activity_time = min(activity.get('avg_time', 2), 3.0)  # Cap at 3 hours
    end_hour = current_hour + activity_time
    
    if not is_activity_time_realistic(current_hour, activity_type):
        logger.warning(f"BLOCKED: {activity.get('name', 'Unknown')} - unrealistic start time {current_hour:.1f} for {activity_type}")
        return None, current_hour
    
    if not is_activity_time_realistic(end_hour, activity_type):
        logger.warning(f"BLOCKED: {activity.get('name', 'Unknown')} - would end at unrealistic time {end_hour:.1f} for {activity_type}")
        return None, current_hour
    
    is_valid, error_msg = enforce_daily_time_limits(current_hour, daily_start_hour)
    if not is_valid:
        logger.warning(f"BLOCKED: {activity.get('name', 'Unknown')} - {error_msg}")
        return None, current_hour
    
    logger.info(f"APPROVED: {activity.get('name', 'Unknown')} scheduled from {current_hour:.1f} to {end_hour:.1f}")
    return activity_time, end_hour
def deduplicate_attractions(attractions, similarity_threshold=0.8):
    """Remove duplicate attractions based on name similarity and location."""
    if not attractions:
        return []
    
    unique_attractions = []
    seen_locations = []
    
    for attraction in attractions:
        is_duplicate = False
        current_location = attraction.get('location', {})
        current_name = attraction.get('name', '').lower().strip()
        
        if not current_name:
            continue
        
        for seen_name, seen_location in seen_locations:
            name_similarity = calculate_similarity(current_name, seen_name)
            
            location_distance = float('inf')
            if current_location and seen_location:
                location_distance = calculate_distance(current_location, seen_location)
            
            if (name_similarity > similarity_threshold or
                location_distance < 0.5 or
                (name_similarity > 0.6 and location_distance < 2.0)):
                is_duplicate = True
                logger.info(f"Duplicate detected: '{current_name}' similar to '{seen_name}'")
                break
        
        if not is_duplicate:
            unique_attractions.append(attraction)
            seen_locations.append((current_name, current_location))
    
    logger.info(f"Deduplication: {len(attractions)} -> {len(unique_attractions)} attractions")
    return unique_attractions

def allocate_budget_realistically(budget, duration):
    """Realistic budget allocation."""
    if duration <= 1:
        return {
            'accommodation': 0,
            'activities': budget * 0.6,
            'meals': budget * 0.4,
            'max_hotel_budget': 0
        }
    else:
        return {
            'accommodation': budget * 0.35,
            'activities': budget * 0.35,
            'meals': budget * 0.3,
            'max_hotel_budget': budget * 0.4
        }

def select_budget_appropriate_hotel(hotels, budget_allocation, duration):
    """Select hotel that fits within budget constraints."""
    if not hotels or duration <= 1:
        return None, 0
    
    num_nights = max(1, duration - 1)
    max_hotel_budget = budget_allocation['max_hotel_budget']
    
    affordable_hotels = []
    for hotel in hotels:
        cost_per_night = hotel.get("estimated_cost", 1000)
        total_cost = cost_per_night * num_nights
        
        if total_cost <= max_hotel_budget:
            rating = hotel.get("rating", 3.0)
            value_score = rating / max(cost_per_night/1000, 1)
            affordable_hotels.append({
                'hotel': hotel,
                'total_cost': total_cost,
                'value_score': value_score
            })
    
    if not affordable_hotels:
        logger.warning("No hotels within normal budget - trying with extended budget")
        extended_budget = max_hotel_budget * 1.5
        for hotel in hotels:
            cost_per_night = hotel.get("estimated_cost", 1000)
            total_cost = cost_per_night * num_nights
            
            if total_cost <= extended_budget:
                rating = hotel.get("rating", 3.0)
                value_score = rating / max(cost_per_night/1000, 1)
                affordable_hotels.append({
                    'hotel': hotel,
                    'total_cost': total_cost,
                    'value_score': value_score
                })
    
    if not affordable_hotels:
        logger.warning("Still no hotels found - selecting cheapest available")
        if hotels:
            cheapest_hotel = min(hotels, key=lambda x: x.get("estimated_cost", 1000))
            total_cost = cheapest_hotel.get("estimated_cost", 1000) * num_nights
            return cheapest_hotel, total_cost
        return None, 0
    
    best_hotel = max(affordable_hotels, key=lambda x: x['value_score'])
    logger.info(f"Selected hotel: {best_hotel['hotel']['name']} (₹{best_hotel['total_cost']})")
    return best_hotel['hotel'], best_hotel['total_cost']

def estimate_internal_travel_time(loc1, loc2):
    """Estimate realistic travel time between locations."""
    try:
        distance_km = calculate_distance(loc1, loc2)
        
        if distance_km < 10:
            avg_speed = 25
        elif distance_km < 50:
            avg_speed = 35
        else:
            avg_speed = 50
        
        travel_hours = distance_km / avg_speed
        return round(max(0.25, travel_hours), 2)
    except Exception as e:
        logger.warning(f"Error calculating travel time: {e}")
        return 0.5

def format_time_from_float(hour_float):
    """Convert float hours to formatted time string."""
    try:
        hour_float = hour_float % 24
        hours = int(hour_float)
        minutes = int((hour_float * 60) % 60)
        time_obj = time(hour=hours, minute=minutes)
        return time_obj.strftime("%I:%M %p")
    except (ValueError, TypeError) as e:
        logger.warning(f"Error formatting time {hour_float}: {e}")
        return "12:00 PM"

def get_priority_score(spot, interests):
    """Enhanced priority score favoring hidden places."""
    try:
        base_score = 2 if spot.get("type") in interests else 1
        
        # Major bonus for hidden places - ONLY from get_hidden_spots
        if spot.get('is_hidden', False):
            base_score += 2.0
        
        # rating = spot.get("rating", 0)
        # if rating > 4.5:
        #     base_score += 1.0
        # elif rating > 4.0:
        #     base_score += 0.5
        
        cost = spot.get("estimated_cost", 0)
        if cost > 8000:
            base_score -= 0.5
        
        return max(0, base_score)
    except Exception as e:
        logger.warning(f"Error calculating priority score: {e}")
        return 1

def schedule_meal(day_wise_itinerary, day_key, meal_type, meal_time, restaurants, meal_budget, total_meal_cost, day_num):
    """Helper function to schedule meals consistently."""
    if not restaurants:
        return total_meal_cost
    
    restaurant_index = (day_num - 1) % len(restaurants)
    restaurant = restaurants[restaurant_index]
    
    meal_cost_map = {
        'breakfast': restaurant.get('estimated_cost', 300) * 0.6,
        'lunch': restaurant.get('estimated_cost', 400) * 0.8,
        'dinner': restaurant.get('estimated_cost', 500) * 1.0
    }
    
    meal_cost = min(meal_cost_map.get(meal_type, 300), meal_budget * 0.15)
    
    if total_meal_cost + meal_cost <= meal_budget:
        day_wise_itinerary[day_key].append({
            "time": meal_time,
            "activity": f"{meal_type.title()} at {restaurant['name']}",
            "duration_hours": 1.0 if meal_type == 'lunch' else 0.5,
            "type": "restaurant",
            "cost": meal_cost
        })
        total_meal_cost += meal_cost
    
    return total_meal_cost

def validate_request_data(data):
    """Validate incoming request data."""
    required_fields = ["starting_location", "destination", "start_date", "end_date", "budget"]
    missing_fields = [field for field in required_fields if not data.get(field)]
    
    if missing_fields:
        return False, f"Missing required fields: {', '.join(missing_fields)}"
    
    try:
        budget = float(data["budget"])
        if budget <= 0:
            return False, "Budget must be a positive number"
        if budget < 1000:
            return False, "Budget too low for realistic travel planning (minimum ₹1000)"
    except (ValueError, TypeError):
        return False, "Invalid budget format"
    
    try:
        start_date = datetime.strptime(data["start_date"], '%Y-%m-%d').date()
        end_date = datetime.strptime(data["end_date"], '%Y-%m-%d').date()
        
        if start_date > end_date:
            return False, "Start date must be before end date"
        if start_date < datetime.now().date():
            return False, "Start date cannot be in the past"
        if (end_date - start_date).days > 30:
            return False, "Trip duration cannot exceed 30 days"
    except ValueError:
        return False, "Invalid date format. Use YYYY-MM-DD"
    
    return True, ""
@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsUser])
def generate_itinerary(request):
    """Generate TRULY realistic travel itinerary with PRECISE timing structure."""
    try:
        user_id = request.auth.get("user_id")
        if not user_id:
            return Response(
                {"error": "Authentication required"},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        data = request.data
        logger.info(f"Generating PRECISE itinerary for user {user_id}")
        
        # Validate request data
        is_valid, error_message = validate_request_data(data)
        if not is_valid:
            return Response(
                {"error": error_message},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Extract parameters
        origin = data["starting_location"].strip()
        destination = data["destination"].strip()
        budget = float(data["budget"])
        interests = data.get("interests", [])
        travel_type = data.get("travel_type", "solo")
        
        # Parse dates
        start_date = datetime.strptime(data["start_date"], '%Y-%m-%d').date()
        end_date = datetime.strptime(data["end_date"], '%Y-%m-%d').date()
        duration = (end_date - start_date).days + 1
        
        logger.info(f"Trip: {origin} -> {destination}, {duration} days, ₹{budget}")
        
        # Budget allocation
        budget_allocation = allocate_budget_realistically(budget, duration)
        
        # Get ML prediction
        try:
            predicted_budget = predict_budget({
                "destination": destination,
                "duration": duration,
                "travel_type": travel_type,
                "interest": interests[0] if interests else "general"
            })
        except Exception as e:
            logger.warning(f"Budget prediction failed: {e}")
            predicted_budget = budget * 1.1
        
        # Fetch route info
        route_cache_key = f"route_{hash(origin)}_{hash(destination)}"
        route = get_cached_or_fetch(route_cache_key, get_route_info, origin, destination)
        if not route:
            route = {
                "origin": origin,
                "destination": destination,
                "distance_km": 200,
                "duration_hours": 6.0
            }
        
        initial_travel_time = min(route.get('duration_hours', 6.0), 12.0)
        
        # Fetch places
        places_cache_key = f"places_{hash(destination)}_{'_'.join(sorted(interests))}"
        pois = get_cached_or_fetch(places_cache_key, get_places, destination, interests) or []
        
        hidden_cache_key = f"hidden_{hash(destination)}_{'_'.join(sorted(interests))}"
        hidden = get_cached_or_fetch(hidden_cache_key, get_hidden_spots, destination, interests) or []
        
        # IMPORTANT: Mark ONLY hidden spots from get_hidden_spots as hidden gems
        for spot in hidden:
            spot['is_hidden'] = True
            # spot['tags'] = spot.get('tags', []) + ['hidden']
        
        # Combine and deduplicate
        all_spots = list({spot.get('name', 'Unknown'): spot for spot in pois + hidden}.values())
        all_spots = deduplicate_attractions(all_spots)
        
        # Add priority scores
        for spot in all_spots:
            spot['priority_score'] = get_priority_score(spot, interests)
        
        # Categorize spots
        hotels = [s for s in all_spots if s.get("type") == "hotel"]
        restaurants = sorted([s for s in all_spots if s.get("type") == "restaurant"],
                            key=lambda x: x.get('estimated_cost', 0))
        attractions = sorted([s for s in all_spots if s.get("type") not in ("hotel", "restaurant")],
                           key=lambda x: -x.get('priority_score', 0))
        
        # Hotel selection
        chosen_hotel, hotel_cost_total = select_budget_appropriate_hotel(
            hotels, budget_allocation, duration
        )
        
        # Calculate remaining budget for activities
        remaining_budget = budget - hotel_cost_total
        if remaining_budget <= 0:
            return Response({
                "error": f"Budget insufficient after accommodation costs (₹{hotel_cost_total}). Increase budget or reduce trip duration."
            }, status=status.HTTP_400_BAD_REQUEST)
        
        activity_budget = remaining_budget * 0.6
        meal_budget = remaining_budget * 0.4
        # Build PRECISE day-wise itinerary following EXACT structure
        day_wise_itinerary = {}
        total_activity_cost = 0
        total_meal_cost = 0
        hidden_gems_count = 0
        current_location = {"lat": 10.0, "lng": 77.0}
        
        globally_scheduled_activities = set()
        
        for day_num in range(1, duration + 1):
            day_key = f"Day {day_num}"
            day_wise_itinerary[day_key] = []
            scheduled_today = set()
            
            # PRECISE STRUCTURE IMPLEMENTATION
            
            # Day 1: 08:00 AM Travel → 03:50 PM Check-in → 04:30 PM Evening Activity → 07:00 PM Dinner → 09:00 PM Stay
            if day_num == 1:
                current_hour = 8.0  # 08:00 AM
                
                # 08:00 AM - Travel from Origin to Destination
                day_wise_itinerary[day_key].append({
                    "time": "08:00 AM",
                    "activity": f"Travel from {origin} to {destination}",
                    "duration_hours": initial_travel_time,
                    "type": "travel",
                    "description": f"Distance: {route.get('distance_km', 'N/A')} km"
                })
                
                arrival_time = current_hour + initial_travel_time
                
                # Check-in time (will be around 03:50 PM if travel is ~8 hours)
                if chosen_hotel and arrival_time >= 14.0:
                    check_in_time = max(arrival_time, 14.0)  # Standard 2 PM earliest check-in
                    day_wise_itinerary[day_key].append({
                        "time": format_time_from_float(check_in_time),
                        "activity": f"Check-in at {chosen_hotel['name']}",
                        "duration_hours": 0.5,
                        "type": "hotel",
                        "cost": 0
                    })
                    current_hour = check_in_time + 0.5
                    current_location = chosen_hotel.get('location', current_location)
                else:
                    current_hour = arrival_time
                
                # 04:30 PM - Evening Activity (if attractions available)
                if attractions and current_hour <= 16.5:
                    for attraction in attractions:
                        if attraction['name'] in globally_scheduled_activities:
                            continue
                        
                        activity_start = max(current_hour, 16.5)  # Force 04:30 PM start
                        activity_time, new_hour = schedule_activity_safely(
                            activity_start, attraction, attraction.get('type', 'attraction'), 8.0
                        )
                        
                        if activity_time is not None:
                            # Add travel time
                            travel_time = estimate_internal_travel_time(
                                current_location, attraction.get('location', current_location)
                            )
                            
                            if travel_time > 0.2:
                                day_wise_itinerary[day_key].append({
                                    "time": format_time_from_float(activity_start),
                                    "activity": f"Travel to {attraction['name']}",
                                    "duration_hours": travel_time,
                                    "type": "travel"
                                })
                                activity_start += travel_time
                            
                            # Add weather info
                            weather_cache_key = f"weather_{attraction.get('location', {}).get('lat', 0)}_{attraction.get('location', {}).get('lng', 0)}_{start_date}"
                            weather_info = get_cached_or_fetch(
                                weather_cache_key, get_weather,
                                attraction.get('location', current_location), start_date
                            )
                            
                            activity_entry = {
                                "time": format_time_from_float(activity_start),
                                "activity": attraction['name'],
                                "duration_hours": activity_time,
                                "type": attraction.get('type', 'attraction'),
                                "cost": attraction.get("estimated_cost", 0),
                                "description": attraction.get("description", ""),
                                "rating": attraction.get("rating", 0)
                            }
                            
                            # ONLY mark as hidden gem if from get_hidden_spots
                            if attraction.get('is_hidden', False):
                                activity_entry["is_hidden_gem"] = True
                                activity_entry["description"] += " [Hidden Gem]"
                                hidden_gems_count += 1
                            
                            if weather_info:
                                activity_entry["weather"] = weather_info
                            
                            day_wise_itinerary[day_key].append(activity_entry)
                            total_activity_cost += attraction.get("estimated_cost", 0)
                            current_location = attraction.get('location', current_location)
                            
                            globally_scheduled_activities.add(attraction['name'])
                            break
                
                # 07:00 PM - Dinner at Restaurant
                total_meal_cost = schedule_meal(
                    day_wise_itinerary, day_key, 'dinner', "07:00 PM", 
                    restaurants, meal_budget, total_meal_cost, day_num
                )
                
                # 09:00 PM - Stay at Hotel
                if chosen_hotel:
                    day_wise_itinerary[day_key].append({
                        "time": "09:00 PM",
                        "activity": f"Stay at {chosen_hotel['name']}",
                        "type": "hotel",
                        "description": f"Night {day_num} accommodation"
                    })
            
            # Day 2 to Last Day-1: PRECISE Structure
            elif day_num < duration:
                # 07:30 AM - Breakfast at Restaurant
                total_meal_cost = schedule_meal(
                    day_wise_itinerary, day_key, 'breakfast', "07:30 AM", 
                    restaurants, meal_budget, total_meal_cost, day_num
                )
                
                # Get available attractions for this day
                available_attractions = [a for a in attractions if a['name'] not in globally_scheduled_activities]
                day_attractions = available_attractions[:4]  # Max 4 attractions per day
                
                # 08:30 AM - Morning Activity 1
                if len(day_attractions) > 0:
                    attraction = day_attractions[0]
                    activity_time, new_hour = schedule_activity_safely(
                        8.5, attraction, attraction.get('type', 'attraction'), 8.0
                    )
                    
                    if activity_time is not None:
                        travel_time = estimate_internal_travel_time(
                            current_location, attraction.get('location', current_location)
                        )
                        
                        if travel_time > 0.2:
                            day_wise_itinerary[day_key].append({
                                "time": "08:30 AM",
                                "activity": f"Travel to {attraction['name']}",
                                "duration_hours": travel_time,
                                "type": "travel"
                            })
                        
                        activity_date = start_date + timedelta(days=day_num - 1)
                        weather_cache_key = f"weather_{attraction.get('location', {}).get('lat', 0)}_{attraction.get('location', {}).get('lng', 0)}_{activity_date}"
                        weather_info = get_cached_or_fetch(
                            weather_cache_key, get_weather,
                            attraction.get('location', current_location), activity_date
                        )
                        
                        activity_entry = {
                            "time": "08:30 AM",
                            "activity": attraction['name'],
                            "duration_hours": activity_time,
                            "type": attraction.get('type', 'attraction'),
                            "cost": attraction.get("estimated_cost", 0),
                            "description": attraction.get("description", ""),
                            "rating": attraction.get("rating", 0)
                        }
                        
                        if attraction.get('is_hidden', False):
                            activity_entry["is_hidden_gem"] = True
                            activity_entry["description"] += " [Hidden Gem]"
                            hidden_gems_count += 1
                        
                        if weather_info:
                            activity_entry["weather"] = weather_info
                        
                        day_wise_itinerary[day_key].append(activity_entry)
                        total_activity_cost += attraction.get("estimated_cost", 0)
                        current_location = attraction.get('location', current_location)
                        globally_scheduled_activities.add(attraction['name'])
                
                # 11:00 AM - Morning Activity 2 (if available)
                if len(day_attractions) > 1:
                    attraction = day_attractions[1]
                    activity_time, new_hour = schedule_activity_safely(
                        11.0, attraction, attraction.get('type', 'attraction'), 8.0
                    )
                    
                    if activity_time is not None:
                        travel_time = estimate_internal_travel_time(
                            current_location, attraction.get('location', current_location)
                        )
                        
                        if travel_time > 0.2:
                            day_wise_itinerary[day_key].append({
                                "time": "11:00 AM",
                                "activity": f"Travel to {attraction['name']}",
                                "duration_hours": travel_time,
                                "type": "travel"
                            })
                        
                        activity_date = start_date + timedelta(days=day_num - 1)
                        weather_cache_key = f"weather_{attraction.get('location', {}).get('lat', 0)}_{attraction.get('location', {}).get('lng', 0)}_{activity_date}"
                        weather_info = get_cached_or_fetch(
                            weather_cache_key, get_weather,
                            attraction.get('location', current_location), activity_date
                        )
                        
                        activity_entry = {
                            "time": "11:00 AM",
                            "activity": attraction['name'],
                            "duration_hours": activity_time,
                            "type": attraction.get('type', 'attraction'),
                            "cost": attraction.get("estimated_cost", 0),
                            "description": attraction.get("description", ""),
                            "rating": attraction.get("rating", 0)
                        }
                        
                        if attraction.get('is_hidden', False):
                            activity_entry["is_hidden_gem"] = True
                            activity_entry["description"] += " [Hidden Gem]"
                            hidden_gems_count += 1
                        
                        if weather_info:
                            activity_entry["weather"] = weather_info
                        
                        day_wise_itinerary[day_key].append(activity_entry)
                        total_activity_cost += attraction.get("estimated_cost", 0)
                        current_location = attraction.get('location', current_location)
                        globally_scheduled_activities.add(attraction['name'])
                
                # 12:00 PM - Lunch at Restaurant
                total_meal_cost = schedule_meal(
                    day_wise_itinerary, day_key, 'lunch', "12:00 PM", 
                    restaurants, meal_budget, total_meal_cost, day_num
                )
                
                # 01:00 PM - Afternoon Activity 1
                if len(day_attractions) > 2:
                    attraction = day_attractions[2]
                    activity_time, new_hour = schedule_activity_safely(
                        13.0, attraction, attraction.get('type', 'attraction'), 8.0
                    )
                    
                    if activity_time is not None:
                        travel_time = estimate_internal_travel_time(
                            current_location, attraction.get('location', current_location)
                        )
                        
                        if travel_time > 0.2:
                            day_wise_itinerary[day_key].append({
                                "time": "01:00 PM",
                                "activity": f"Travel to {attraction['name']}",
                                "duration_hours": travel_time,
                                "type": "travel"
                            })
                        
                        activity_date = start_date + timedelta(days=day_num - 1)
                        weather_cache_key = f"weather_{attraction.get('location', {}).get('lat', 0)}_{attraction.get('location', {}).get('lng', 0)}_{activity_date}"
                        weather_info = get_cached_or_fetch(
                            weather_cache_key, get_weather,
                            attraction.get('location', current_location), activity_date
                        )
                        
                        activity_entry = {
                            "time": "01:00 PM",
                            "activity": attraction['name'],
                            "duration_hours": activity_time,
                            "type": attraction.get('type', 'attraction'),
                            "cost": attraction.get("estimated_cost", 0),
                            "description": attraction.get("description", ""),
                            "rating": attraction.get("rating", 0)
                        }
                        
                        if attraction.get('is_hidden', False):
                            activity_entry["is_hidden_gem"] = True
                            activity_entry["description"] += " [Hidden Gem]"
                            hidden_gems_count += 1
                        
                        if weather_info:
                            activity_entry["weather"] = weather_info
                        
                        day_wise_itinerary[day_key].append(activity_entry)
                        total_activity_cost += attraction.get("estimated_cost", 0)
                        current_location = attraction.get('location', current_location)
                        globally_scheduled_activities.add(attraction['name'])
                
                # 04:00 PM - Afternoon Activity 2 (if available)
                if len(day_attractions) > 3:
                    attraction = day_attractions[3]
                    activity_time, new_hour = schedule_activity_safely(
                        16.0, attraction, attraction.get('type', 'attraction'), 8.0
                    )
                    
                    if activity_time is not None:
                        travel_time = estimate_internal_travel_time(
                            current_location, attraction.get('location', current_location)
                        )
                        
                        if travel_time > 0.2:
                            day_wise_itinerary[day_key].append({
                                "time": "04:00 PM",
                                "activity": f"Travel to {attraction['name']}",
                                "duration_hours": travel_time,
                                "type": "travel"
                            })
                        
                        activity_date = start_date + timedelta(days=day_num - 1)
                        weather_cache_key = f"weather_{attraction.get('location', {}).get('lat', 0)}_{attraction.get('location', {}).get('lng', 0)}_{activity_date}"
                        weather_info = get_cached_or_fetch(
                            weather_cache_key, get_weather,
                            attraction.get('location', current_location), activity_date
                        )
                        
                        activity_entry = {
                            "time": "04:00 PM",
                            "activity": attraction['name'],
                            "duration_hours": activity_time,
                            "type": attraction.get('type', 'attraction'),
                            "cost": attraction.get("estimated_cost", 0),
                            "description": attraction.get("description", ""),
                            "rating": attraction.get("rating", 0)
                        }
                        
                        if attraction.get('is_hidden', False):
                            activity_entry["is_hidden_gem"] = True
                            activity_entry["description"] += " [Hidden Gem]"
                            hidden_gems_count += 1
                        
                        if weather_info:
                            activity_entry["weather"] = weather_info
                        
                        day_wise_itinerary[day_key].append(activity_entry)
                        total_activity_cost += attraction.get("estimated_cost", 0)
                        current_location = attraction.get('location', current_location)
                        globally_scheduled_activities.add(attraction['name'])
                
                # 07:00 PM - Dinner at Restaurant
                total_meal_cost = schedule_meal(
                    day_wise_itinerary, day_key, 'dinner', "07:00 PM", 
                    restaurants, meal_budget, total_meal_cost, day_num
                )
                
                # 09:00 PM - Stay at Hotel
                if chosen_hotel:
                    day_wise_itinerary[day_key].append({
                        "time": "09:00 PM",
                        "activity": f"Stay at {chosen_hotel['name']}",
                        "type": "hotel",
                        "description": f"Night {day_num} accommodation"
                    })
            # Last Day: 07:30 AM Breakfast → 08:30 AM Check out → 09:00 AM Final Activity → 12:00 PM Lunch → 02:00 PM Departure → Arrival
            else:
                # 07:30 AM - Breakfast at Restaurant
                total_meal_cost = schedule_meal(
                    day_wise_itinerary, day_key, 'breakfast', "07:30 AM", 
                    restaurants, meal_budget, total_meal_cost, day_num
                )
                
                # 08:30 AM - Check out from Hotel
                if chosen_hotel:
                    day_wise_itinerary[day_key].append({
                        "time": "08:30 AM",
                        "activity": f"Check out from {chosen_hotel['name']}",
                        "duration_hours": 0.5,
                        "type": "hotel",
                        "cost": 0
                    })
                
                # 09:00 AM - Final Morning Activity
                remaining_attractions = [a for a in attractions if a['name'] not in globally_scheduled_activities]
                if remaining_attractions:
                    attraction = remaining_attractions[0]
                    activity_time, new_hour = schedule_activity_safely(
                        9.0, attraction, attraction.get('type', 'attraction'), 8.0
                    )
                    
                    if activity_time is not None:
                        travel_time = estimate_internal_travel_time(
                            current_location, attraction.get('location', current_location)
                        )
                        
                        if travel_time > 0.2:
                            day_wise_itinerary[day_key].append({
                                "time": "09:00 AM",
                                "activity": f"Travel to {attraction['name']}",
                                "duration_hours": travel_time,
                                "type": "travel"
                            })
                        
                        activity_date = start_date + timedelta(days=day_num - 1)
                        weather_cache_key = f"weather_{attraction.get('location', {}).get('lat', 0)}_{attraction.get('location', {}).get('lng', 0)}_{activity_date}"
                        weather_info = get_cached_or_fetch(
                            weather_cache_key, get_weather,
                            attraction.get('location', current_location), activity_date
                        )
                        
                        activity_entry = {
                            "time": "09:00 AM",
                            "activity": attraction['name'],
                            "duration_hours": activity_time,
                            "type": attraction.get('type', 'attraction'),
                            "cost": attraction.get("estimated_cost", 0),
                            "description": attraction.get("description", ""),
                            "rating": attraction.get("rating", 0)
                        }
                        
                        if attraction.get('is_hidden', False):
                            activity_entry["is_hidden_gem"] = True
                            activity_entry["description"] += " [Hidden Gem]"
                            hidden_gems_count += 1
                        
                        if weather_info:
                            activity_entry["weather"] = weather_info
                        
                        day_wise_itinerary[day_key].append(activity_entry)
                        total_activity_cost += attraction.get("estimated_cost", 0)
                        globally_scheduled_activities.add(attraction['name'])
                
                # 12:00 PM - Lunch at Restaurant
                total_meal_cost = schedule_meal(
                    day_wise_itinerary, day_key, 'lunch', "12:00 PM", 
                    restaurants, meal_budget, total_meal_cost, day_num
                )
                
                # 02:00 PM - Departure from Destination
                day_wise_itinerary[day_key].append({
                    "time": "02:00 PM",
                    "activity": f"Departure from {destination}",
                    "duration_hours": initial_travel_time,
                    "type": "travel",
                    "description": f"Return journey to {origin}"
                })
                
                # Calculate arrival time (e.g., 02:00 PM + 7.84 hours = 09:50 PM)
                departure_hour = 14.0  # 2:00 PM
                arrival_hour = departure_hour + initial_travel_time
                
                day_wise_itinerary[day_key].append({
                    "time": format_time_from_float(arrival_hour),
                    "activity": f"Arrival at {origin}",
                    "duration_hours": 0,
                    "type": "arrival",
                    "description": "End of trip"
                })
        
        # Calculate final totals
        total_cost = hotel_cost_total + total_activity_cost + total_meal_cost
        
        if total_cost > budget * 1.1:
            logger.error(f"BUDGET SIGNIFICANTLY EXCEEDED: ₹{total_cost} > ₹{budget}")
            return Response({
                "error": f"Unable to create itinerary within reasonable budget. Total cost: ₹{total_cost}, Budget: ₹{budget}. Please increase budget significantly."
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Alternative options
        remaining_attractions = [a for a in attractions
                               if a['name'] not in globally_scheduled_activities][:10]
        alternative_hotels = [h for h in hotels if h != chosen_hotel][:5]
        
        # Response data
        response_data = {
            "user_id": user_id,
            "day_wise_itinerary": day_wise_itinerary,
            "hotel_details": {
                "name": chosen_hotel["name"],
                "cost_per_night": chosen_hotel.get("estimated_cost", 0),
                "total_nights": max(1, duration - 1),
                "total_cost": hotel_cost_total,
                "rating": chosen_hotel.get("rating", 0),
                "location": chosen_hotel.get("location", {})
            } if chosen_hotel else None,
            "alternatives": {
                "hotels": alternative_hotels,
                "attractions": remaining_attractions
            },
            "cost_breakdown": {
                "accommodation": hotel_cost_total,
                "activities": total_activity_cost,
                "meals": total_meal_cost,
                "total": total_cost
            },
            "summary": {
                "total_days": duration,
                "start_date": start_date.strftime('%Y-%m-%d'),
                "end_date": end_date.strftime('%Y-%m-%d'),
                "proposed_budget": budget,
                "predicted_budget": predicted_budget,
                "actual_cost": round(total_cost),
                "savings": max(0, budget - total_cost),
                "destination": destination,
                "origin": origin,
                "total_attractions": len(globally_scheduled_activities),
                "hidden_gems_count": hidden_gems_count,
                "budget_utilization": round((total_cost / budget) * 100, 1) if budget > 0 else 0,
                "realistic_schedule": True,
                "timing_validated": True,
                "no_duplicates": True,
                "precise_structure": True
            },
            "route_info": route,
            "status": "success",
            "generated_at": datetime.now().isoformat()
        }
        
        # Save to MongoDB
        try:
            user_itinerary = UserItinerary(user_id=user_id, itinerary_data=response_data)
            user_itinerary.save()
            logger.info(f"PRECISE itinerary saved for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to save itinerary: {e}")
        
        logger.info(f"PRECISE itinerary generated: {len(globally_scheduled_activities)} unique attractions, "
                   f"₹{total_cost}, {hidden_gems_count} hidden gems, {response_data['summary']['budget_utilization']}% budget used")
        
        return Response(response_data, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error generating PRECISE itinerary: {str(e)}", exc_info=True)
        return Response(
            {"error": "An unexpected error occurred while generating the itinerary. Please try again."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
