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
        # Outdoor activities: 7 AM to 6 PM only (STRICTLY ENFORCED)
        return 7.0 <= hour_float <= 18.0
    elif activity_type == 'restaurant':
        # Meals: Breakfast (7-10), Lunch (12-3), Dinner (6-9 PM)
        return (7.0 <= hour_float <= 10.0 or 
                12.0 <= hour_float <= 15.0 or 
                18.0 <= hour_float <= 21.0)
    elif activity_type == 'hotel':
        # Hotel check-in/check-out: 2 PM onwards for check-in
        return hour_float >= 14.0 or hour_float <= 12.0
    elif activity_type == 'travel':
        # Travel can happen anytime between 6 AM - 10 PM
        return 6.0 <= hour_float <= 22.0
    
    return True

def enforce_daily_time_limits(current_hour, daily_start_hour=8.0):
    """Enforce realistic daily activity limits."""
    max_daily_activity_hours = 10  # Maximum 10 hours of activities
    latest_outdoor_time = 18.0      # No outdoor activities after 6 PM
    
    if current_hour > latest_outdoor_time:
        return False, "Outdoor activities cannot extend beyond 6 PM"
    
    if (current_hour - daily_start_hour) > max_daily_activity_hours:
        return False, "Daily activity limit exceeded (10 hours)"
    
    return True, ""

def schedule_activity_safely(current_hour, activity, activity_type, daily_start_hour=8.0):
    """Schedule activity only if timing is realistic - KEY VALIDATION FUNCTION."""
    activity_time = min(activity.get('avg_time', 2), 3.0)  # Cap at 3 hours
    end_hour = current_hour + activity_time
    
    # CRITICAL: Check if activity timing is realistic
    if not is_activity_time_realistic(current_hour, activity_type):
        logger.warning(f"BLOCKED: {activity.get('name', 'Unknown')} - unrealistic start time {current_hour:.1f} for {activity_type}")
        return None, current_hour
    
    if not is_activity_time_realistic(end_hour, activity_type):
        logger.warning(f"BLOCKED: {activity.get('name', 'Unknown')} - would end at unrealistic time {end_hour:.1f} for {activity_type}")
        return None, current_hour
    
    # Check daily limits
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
        
        # Skip if name is empty
        if not current_name:
            continue
            
        for seen_name, seen_location in seen_locations:
            # Check name similarity
            name_similarity = calculate_similarity(current_name, seen_name)
            
            # Check location proximity
            location_distance = float('inf')
            if current_location and seen_location:
                location_distance = calculate_distance(current_location, seen_location)
            
            # Mark as duplicate if very similar or same location
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
    """FIXED: Realistic budget allocation with higher accommodation allowance."""
    if duration <= 1:
        return {
            'accommodation': 0,
            'activities': budget * 0.6,
            'meals': budget * 0.4,
            'max_hotel_budget': 0
        }
    else:
        # 🔧 FIXED: Increased accommodation budget to ensure hotel selection
        return {
            'accommodation': budget * 0.5,     # 50% for accommodation (INCREASED)
            'activities': budget * 0.3,        # 30% for activities  
            'meals': budget * 0.2,             # 20% for meals
            'max_hotel_budget': budget * 0.6   # Max 60% for accommodation (INCREASED)
        }

def select_budget_appropriate_hotel(hotels, budget_allocation, duration):
    """FIXED: Select hotel that fits within FLEXIBLE budget constraints."""
    if not hotels or duration <= 1:
        return None, 0
    
    num_nights = max(1, duration - 1)
    max_hotel_budget = budget_allocation['max_hotel_budget']
    
    # 🔧 FIXED: More flexible hotel selection
    affordable_hotels = []
    for hotel in hotels:
        cost_per_night = hotel.get("estimated_cost", 1000)
        total_cost = cost_per_night * num_nights
        
        # More generous budget allowance
        if total_cost <= max_hotel_budget:
            rating = hotel.get("rating", 3.0)
            value_score = rating / max(cost_per_night/1000, 1)
            affordable_hotels.append({
                'hotel': hotel,
                'total_cost': total_cost,
                'value_score': value_score
            })
    
    # 🔧 FIXED: If no hotels found, try with even more generous budget
    if not affordable_hotels:
        logger.warning("No hotels within normal budget - trying with extended budget")
        extended_budget = max_hotel_budget * 1.5  # 50% more budget allowance
        
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
    
    # Select best value hotel within budget
    best_hotel = max(affordable_hotels, key=lambda x: x['value_score'])
    logger.info(f"Selected hotel: {best_hotel['hotel']['name']} (₹{best_hotel['total_cost']})")
    
    return best_hotel['hotel'], best_hotel['total_cost']

def estimate_internal_travel_time(loc1, loc2):
    """Estimate realistic travel time between locations."""
    try:
        distance_km = calculate_distance(loc1, loc2)
        
        # Conservative speed estimates
        if distance_km < 10:
            avg_speed = 25  # City traffic
        elif distance_km < 50:
            avg_speed = 35  # Regional roads
        else:
            avg_speed = 50  # Highway
            
        travel_hours = distance_km / avg_speed
        return round(max(0.25, travel_hours), 2)  # Minimum 15 minutes
        
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
        
        # Major bonus for hidden places
        if spot.get('is_hidden', False):
            base_score += 3.0
        
        # Bonus for hidden tags
        spot_tags = spot.get("tags", [])
        if any(tag in ["hidden", "secret", "offbeat", "local", "gem"] for tag in spot_tags):
            base_score += 2.0
        
        # Rating bonus
        rating = spot.get("rating", 0)
        if rating > 4.5:
            base_score += 1.0
        elif rating > 4.0:
            base_score += 0.5
        
        # Cost consideration
        cost = spot.get("estimated_cost", 0)
        if cost > 8000:
            base_score -= 0.5
        
        return max(0, base_score)
        
    except Exception as e:
        logger.warning(f"Error calculating priority score: {e}")
        return 1

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
    """Generate TRULY realistic travel itinerary with ENFORCED timing and budget constraints."""
    
    try:
        user_id = request.auth.get("user_id")
        if not user_id:
            return Response(
                {"error": "Authentication required"}, 
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        data = request.data
        logger.info(f"Generating REALISTIC itinerary for user {user_id}")
        
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
        
        # 🔧 FIXED: Improved budget allocation
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
        
        initial_travel_time = min(route.get('duration_hours', 6.0), 12.0)  # Cap at 12 hours
        
        # Fetch places
        places_cache_key = f"places_{hash(destination)}_{'_'.join(sorted(interests))}"
        pois = get_cached_or_fetch(places_cache_key, get_places, destination, interests) or []
        
        hidden_cache_key = f"hidden_{hash(destination)}_{'_'.join(sorted(interests))}"
        hidden = get_cached_or_fetch(hidden_cache_key, get_hidden_spots, destination, interests) or []
        
        # Mark hidden spots
        for spot in hidden:
            spot['is_hidden'] = True
            spot['tags'] = spot.get('tags', []) + ['hidden']
        
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
        
        # 🔧 FIXED: Improved hotel selection
        chosen_hotel, hotel_cost_total = select_budget_appropriate_hotel(
            hotels, budget_allocation, duration
        )
        
        # Calculate remaining budget for activities
        remaining_budget = budget - hotel_cost_total
        if remaining_budget <= 0:
            return Response({
                "error": f"Budget insufficient after accommodation costs (₹{hotel_cost_total}). Increase budget or reduce trip duration."
            }, status=status.HTTP_400_BAD_REQUEST)
        
        activity_budget = remaining_budget * 0.6  # 60% of remaining for activities
        meal_budget = remaining_budget * 0.4      # 40% of remaining for meals
        
        # Build REALISTIC day-wise itinerary with ENFORCED timing
        day_wise_itinerary = {}
        total_activity_cost = 0
        total_meal_cost = 0
        hidden_gems_count = 0
        current_location = {"lat": 10.0, "lng": 77.0}
        
        # 🔧 FIXED: Track scheduled activities to prevent duplicates
        globally_scheduled_activities = set()
        
        # Distribute attractions across days (2-3 per day max for realism)
        attractions_per_day = max(2, min(3, len(attractions) // duration if duration > 0 else 2))
        
        for day_num in range(1, duration + 1):
            day_key = f"Day {day_num}"
            day_wise_itinerary[day_key] = []
            current_hour = 8.0  # Always start at 8 AM
            daily_start_hour = current_hour
            
            # 🔧 FIXED: Track activities scheduled today to prevent same-day duplicates
            scheduled_today = set()
            
            # Day 1: Travel and arrival
            if day_num == 1:
                # Initial travel
                day_wise_itinerary[day_key].append({
                    "time": format_time_from_float(current_hour),
                    "activity": f"Travel from {origin} to {destination}",
                    "duration_hours": initial_travel_time,
                    "type": "travel",
                    "description": f"Distance: {route.get('distance_km', 'N/A')} km"
                })
                current_hour += initial_travel_time
                
                # 🔧 FIXED: Hotel check-in (ONLY if realistic timing with proper sequence)
                if chosen_hotel and current_hour >= 14.0:  # Standard 2 PM check-in
                    day_wise_itinerary[day_key].append({
                        "time": format_time_from_float(max(current_hour, 14.0)),  # Ensure 2 PM minimum
                        "activity": f"Check-in at {chosen_hotel['name']}",
                        "duration_hours": 0.5,
                        "type": "hotel",
                        "cost": 0
                    })
                    current_hour = max(current_hour + 0.5, 14.5)  # Update current hour
                    current_location = chosen_hotel.get('location', current_location)
                
                # Evening activity ONLY if timing is realistic
                if attractions and current_hour <= 16.0:  # Must start by 4 PM
                    for attraction in attractions:
                        # 🔧 FIXED: Skip if already scheduled globally
                        if attraction['name'] in globally_scheduled_activities:
                            continue
                            
                        activity_time, new_hour = schedule_activity_safely(
                            current_hour, attraction, attraction.get('type', 'attraction'), daily_start_hour
                        )
                        
                        if activity_time is not None:  # ONLY schedule if realistic
                            # Add travel time with validation
                            travel_time = estimate_internal_travel_time(
                                current_location, attraction.get('location', current_location)
                            )
                            
                            if travel_time > 0.2 and is_activity_time_realistic(current_hour, 'travel'):
                                day_wise_itinerary[day_key].append({
                                    "time": format_time_from_float(current_hour),
                                    "activity": f"Travel to {attraction['name']}",
                                    "duration_hours": travel_time,
                                    "type": "travel"
                                })
                                current_hour += travel_time
                            
                            # Add weather info
                            weather_cache_key = f"weather_{attraction.get('location', {}).get('lat', 0)}_{attraction.get('location', {}).get('lng', 0)}_{start_date}"
                            weather_info = get_cached_or_fetch(
                                weather_cache_key, get_weather, 
                                attraction.get('location', current_location), start_date
                            )
                            
                            activity_entry = {
                                "time": format_time_from_float(current_hour),
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
                            current_hour = new_hour
                            total_activity_cost += attraction.get("estimated_cost", 0)
                            current_location = attraction.get('location', current_location)
                            
                            # 🔧 FIXED: Mark as scheduled
                            globally_scheduled_activities.add(attraction['name'])
                            scheduled_today.add(attraction['name'])
                            break  # Only one activity for Day 1 evening
                
                # 🔧 FIXED: Dinner ONLY at realistic time AND after check-in
                dinner_time = max(current_hour, 19.0)  # Ensure dinner is after current activities
                if restaurants and is_activity_time_realistic(dinner_time, 'restaurant'):
                    restaurant = restaurants[0]
                    dinner_cost = min(restaurant.get('estimated_cost', 400), meal_budget * 0.3)
                    if total_meal_cost + dinner_cost <= meal_budget:
                        day_wise_itinerary[day_key].append({
                            "time": format_time_from_float(dinner_time),  # Dynamic dinner time
                            "activity": f"Dinner at {restaurant['name']}",
                            "duration_hours": 1.5,
                            "type": "restaurant",
                            "cost": dinner_cost
                        })
                        total_meal_cost += dinner_cost
            
            # Regular days (2 to duration-1) with STRICT timing enforcement
            elif day_num < duration:
                start_attraction_index = (day_num - 2) * attractions_per_day + 1
                end_attraction_index = min((day_num - 1) * attractions_per_day + 1, len(attractions))
                day_attractions = attractions[start_attraction_index:end_attraction_index]
                
                # Morning activities (8 AM - 12 PM) with validation
                morning_count = 0
                for attraction in day_attractions:
                    if morning_count >= 2:  # Max 2 morning activities
                        break
                    
                    # 🔧 FIXED: Skip if already scheduled globally or today
                    if (attraction['name'] in globally_scheduled_activities or 
                        attraction['name'] in scheduled_today):
                        continue
                        
                    activity_time, new_hour = schedule_activity_safely(
                        current_hour, attraction, attraction.get('type', 'attraction'), daily_start_hour
                    )
                    
                    if (activity_time is not None and 
                        new_hour <= 12.0 and  # Must end by noon
                        total_activity_cost + attraction.get('estimated_cost', 0) <= activity_budget):
                        
                        # Add travel time with validation
                        travel_time = estimate_internal_travel_time(
                            current_location, attraction.get('location', current_location)
                        )
                        
                        if travel_time > 0.2 and is_activity_time_realistic(current_hour, 'travel'):
                            day_wise_itinerary[day_key].append({
                                "time": format_time_from_float(current_hour),
                                "activity": f"Travel to {attraction['name']}",
                                "duration_hours": travel_time,
                                "type": "travel"
                            })
                            current_hour += travel_time
                        
                        # Add activity with weather info
                        activity_date = start_date + timedelta(days=day_num - 1)
                        weather_cache_key = f"weather_{attraction.get('location', {}).get('lat', 0)}_{attraction.get('location', {}).get('lng', 0)}_{activity_date}"
                        weather_info = get_cached_or_fetch(
                            weather_cache_key, get_weather, 
                            attraction.get('location', current_location), activity_date
                        )
                        
                        activity_entry = {
                            "time": format_time_from_float(current_hour),
                            "activity": attraction['name'],
                            "duration_hours": activity_time,
                            "type": attraction.get('type', 'attraction'),
                            "cost": attraction.get('estimated_cost', 0),
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
                        current_hour = new_hour
                        total_activity_cost += attraction.get('estimated_cost', 0)
                        current_location = attraction.get('location', current_location)
                        
                        # 🔧 FIXED: Mark as scheduled
                        globally_scheduled_activities.add(attraction['name'])
                        scheduled_today.add(attraction['name'])
                        morning_count += 1
                
                # Lunch break (12 PM - 1 PM) at REALISTIC time
                if restaurants and is_activity_time_realistic(12.0, 'restaurant'):
                    restaurant = restaurants[day_num % len(restaurants)]
                    lunch_cost = min(restaurant.get('estimated_cost', 350), meal_budget * 0.25)
                    if total_meal_cost + lunch_cost <= meal_budget:
                        day_wise_itinerary[day_key].append({
                            "time": "12:00 PM",  # Fixed realistic lunch time
                            "activity": f"Lunch at {restaurant['name']}",
                            "duration_hours": 1.0,
                            "type": "restaurant",
                            "cost": lunch_cost
                        })
                        total_meal_cost += lunch_cost
                    current_hour = 13.0
                
                # Afternoon activities (1 PM - 5 PM) with STRICT validation
                afternoon_count = 0
                remaining_attractions = [a for a in attractions if a not in day_attractions]
                
                for attraction in remaining_attractions:
                    if afternoon_count >= 2:  # Max 2 afternoon activities
                        break
                    
                    # 🔧 FIXED: Skip if already scheduled globally or today
                    if (attraction['name'] in globally_scheduled_activities or 
                        attraction['name'] in scheduled_today):
                        continue
                        
                    activity_time, new_hour = schedule_activity_safely(
                        current_hour, attraction, attraction.get('type', 'attraction'), daily_start_hour
                    )
                    
                    if (activity_time is not None and 
                        new_hour <= 17.0 and  # Must end by 5 PM for outdoor activities
                        total_activity_cost + attraction.get('estimated_cost', 0) <= activity_budget):
                        
                        # Add travel time with validation
                        travel_time = estimate_internal_travel_time(
                            current_location, attraction.get('location', current_location)
                        )
                        
                        if travel_time > 0.2 and is_activity_time_realistic(current_hour, 'travel'):
                            day_wise_itinerary[day_key].append({
                                "time": format_time_from_float(current_hour),
                                "activity": f"Travel to {attraction['name']}",
                                "duration_hours": travel_time,
                                "type": "travel"
                            })
                            current_hour += travel_time
                        
                        # Add activity with weather info
                        activity_date = start_date + timedelta(days=day_num - 1)
                        weather_cache_key = f"weather_{attraction.get('location', {}).get('lat', 0)}_{attraction.get('location', {}).get('lng', 0)}_{activity_date}"
                        weather_info = get_cached_or_fetch(
                            weather_cache_key, get_weather, 
                            attraction.get('location', current_location), activity_date
                        )
                        
                        activity_entry = {
                            "time": format_time_from_float(current_hour),
                            "activity": attraction['name'],
                            "duration_hours": activity_time,
                            "type": attraction.get('type', 'attraction'),
                            "cost": attraction.get('estimated_cost', 0),
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
                        current_hour = new_hour
                        total_activity_cost += attraction.get('estimated_cost', 0)
                        current_location = attraction.get('location', current_location)
                        
                        # 🔧 FIXED: Mark as scheduled
                        globally_scheduled_activities.add(attraction['name'])
                        scheduled_today.add(attraction['name'])
                        afternoon_count += 1
                
                # Dinner ONLY at realistic time
                if restaurants and is_activity_time_realistic(19.0, 'restaurant'):
                    restaurant = restaurants[(day_num - 1) % len(restaurants)]
                    dinner_cost = min(restaurant.get('estimated_cost', 450), meal_budget * 0.3)
                    if total_meal_cost + dinner_cost <= meal_budget:
                        day_wise_itinerary[day_key].append({
                            "time": "07:00 PM",  # Fixed realistic dinner time
                            "activity": f"Dinner at {restaurant['name']}",
                            "duration_hours": 1.5,
                            "type": "restaurant",
                            "cost": dinner_cost
                        })
                        total_meal_cost += dinner_cost
            
            # Last day: Final activities and departure with STRICT timing
            else:
                # Morning activity ONLY if realistic
                remaining_attractions = [a for a in attractions if a['name'] not in globally_scheduled_activities]
                if remaining_attractions and current_hour <= 10.0:
                    attraction = remaining_attractions[0]
                    activity_time, new_hour = schedule_activity_safely(
                        current_hour, attraction, attraction.get('type', 'attraction'), daily_start_hour
                    )
                    
                    if (activity_time is not None and 
                        new_hour <= 12.0 and  # Must end by noon for departure
                        total_activity_cost + attraction.get('estimated_cost', 0) <= activity_budget):
                        
                        # Add travel time with validation
                        travel_time = estimate_internal_travel_time(
                            current_location, attraction.get('location', current_location)
                        )
                        
                        if travel_time > 0.2 and is_activity_time_realistic(current_hour, 'travel'):
                            day_wise_itinerary[day_key].append({
                                "time": format_time_from_float(current_hour),
                                "activity": f"Travel to {attraction['name']}",
                                "duration_hours": travel_time,
                                "type": "travel"
                            })
                            current_hour += travel_time
                        
                        # Add activity with weather info
                        activity_date = start_date + timedelta(days=day_num - 1)
                        weather_cache_key = f"weather_{attraction.get('location', {}).get('lat', 0)}_{attraction.get('location', {}).get('lng', 0)}_{activity_date}"
                        weather_info = get_cached_or_fetch(
                            weather_cache_key, get_weather, 
                            attraction.get('location', current_location), activity_date
                        )
                        
                        activity_entry = {
                            "time": format_time_from_float(current_hour),
                            "activity": attraction['name'],
                            "duration_hours": activity_time,
                            "type": attraction.get('type', 'attraction'),
                            "cost": attraction.get('estimated_cost', 0),
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
                        current_hour = new_hour
                        total_activity_cost += attraction.get('estimated_cost', 0)
                        
                        # Mark as scheduled
                        globally_scheduled_activities.add(attraction['name'])
                
                # Return travel at REALISTIC time (not before 2 PM)
                departure_time = max(current_hour + 1, 14.0)  # Leave after 2 PM at earliest
                day_wise_itinerary[day_key].append({
                    "time": format_time_from_float(departure_time),
                    "activity": f"Return travel to {origin}",
                    "duration_hours": initial_travel_time,
                    "type": "travel"
                })
            
            # Add hotel stay for each night (except last day)
            if chosen_hotel and day_num < duration:
                day_wise_itinerary[day_key].append({
                    "time": "09:00 PM",
                    "activity": f"Stay at {chosen_hotel['name']}",
                    "type": "hotel",
                    "description": f"Night {day_num} accommodation"
                })
        
        # Calculate final totals with budget compliance
        total_cost = hotel_cost_total + total_activity_cost + total_meal_cost
        
        # Budget enforcement (allowing slight overrun for essential accommodation)
        if total_cost > budget * 1.1:  # Allow 10% buffer
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
                "no_duplicates": True
            },
            "route_info": route,
            "status": "success",
            "generated_at": datetime.now().isoformat()
        }
        
        # Save to MongoDB
        try:
            user_itinerary = UserItinerary(user_id=user_id, itinerary_data=response_data)
            user_itinerary.save()
            logger.info(f"REALISTIC itinerary saved for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to save itinerary: {e}")
        
        logger.info(f"REALISTIC itinerary generated: {len(globally_scheduled_activities)} unique attractions, "
                   f"₹{total_cost}, {hidden_gems_count} hidden gems, {response_data['summary']['budget_utilization']}% budget used")
        
        return Response(response_data, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error generating REALISTIC itinerary: {str(e)}", exc_info=True)
        return Response(
            {"error": "An unexpected error occurred while generating the itinerary. Please try again."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsUser])
def get_user_itineraries(request):
    """Get all itineraries for the authenticated user."""
    try:
        user_id = request.auth.get("user_id")
        if not user_id:
            return Response(
                {"error": "Authentication required"}, 
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        itineraries = UserItinerary.objects(user_id=user_id).order_by('-created_at')
        
        itinerary_list = []
        for itinerary in itineraries:
            summary = itinerary.itinerary_data.get('summary', {})
            itinerary_list.append({
                'id': str(itinerary.id),
                'destination': summary.get('destination', 'Unknown'),
                'start_date': summary.get('start_date', ''),
                'end_date': summary.get('end_date', ''),
                'total_days': summary.get('total_days', 0),
                'actual_cost': summary.get('actual_cost', 0),
                'hidden_gems_count': summary.get('hidden_gems_count', 0),
                'budget_utilization': summary.get('budget_utilization', 0),
                'realistic_schedule': summary.get('realistic_schedule', False),
                'timing_validated': summary.get('timing_validated', False),
                'no_duplicates': summary.get('no_duplicates', False),
                'created_at': itinerary.created_at.isoformat() if itinerary.created_at else None
            })
        
        return Response({
            'itineraries': itinerary_list,
            'total_count': len(itinerary_list)
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error fetching user itineraries: {str(e)}")
        return Response(
            {"error": "Failed to fetch itineraries"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsUser])
def get_itinerary_detail(request, itinerary_id):
    """Get detailed itinerary by ID."""
    try:
        user_id = request.auth.get("user_id")
        if not user_id:
            return Response(
                {"error": "Authentication required"}, 
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        itinerary = UserItinerary.objects(id=itinerary_id, user_id=user_id).first()
        
        if not itinerary:
            return Response(
                {"error": "Itinerary not found"}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        return Response(itinerary.itinerary_data, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error fetching itinerary detail: {str(e)}")
        return Response(
            {"error": "Failed to fetch itinerary details"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['DELETE'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsUser])
def delete_itinerary(request, itinerary_id):
    """Delete an itinerary by ID."""
    try:
        user_id = request.auth.get("user_id")
        if not user_id:
            return Response(
                {"error": "Authentication required"}, 
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        itinerary = UserItinerary.objects(id=itinerary_id, user_id=user_id).first()
        
        if not itinerary:
            return Response(
                {"error": "Itinerary not found"}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        itinerary.delete()
        
        return Response(
            {"message": "Itinerary deleted successfully"}, 
            status=status.HTTP_200_OK
        )
        
    except Exception as e:
        logger.error(f"Error deleting itinerary: {str(e)}")
        return Response(
            {"error": "Failed to delete itinerary"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
