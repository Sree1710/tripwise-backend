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


def estimate_internal_travel_time(loc1, loc2):
    """Estimate travel time between two locations based on distance."""
    try:
        lat1, lon1 = float(loc1['lat']), float(loc1['lng'])
        lat2, lon2 = float(loc2['lat']), float(loc2['lng'])
        
        # Haversine formula for more accurate distance calculation
        R = 6371  # Earth's radius in km
        
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat/2) * math.sin(dlat/2) + 
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * 
             math.sin(dlon/2) * math.sin(dlon/2))
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        distance_km = R * c
        
        # Estimate travel time: 40 km/h average speed in cities, 60 km/h outside
        avg_speed = 40 if distance_km < 50 else 60
        travel_hours = distance_km / avg_speed
        
        return round(max(0.25, travel_hours), 2)  # Minimum 15 minutes
        
    except (KeyError, ValueError, TypeError) as e:
        logger.warning(f"Error calculating travel time: {e}")
        return 0.5  # Default 30 minutes


def format_time_from_float(hour_float):
    """Convert float hours to formatted time string."""
    try:
        # Handle cases where hour_float might exceed 24 hours
        hour_float = hour_float % 24
        hours = int(hour_float)
        minutes = int((hour_float * 60) % 60)
        time_obj = time(hour=hours, minute=minutes)
        return time_obj.strftime("%I:%M %p")
    except (ValueError, TypeError) as e:
        logger.warning(f"Error formatting time {hour_float}: {e}")
        return "12:00 PM"


def get_priority_score(spot, interests):
    """Enhanced priority score that favors hidden places."""
    try:
        base_score = 1 if spot.get("type") in interests else 0
        
        # 🔥 BIG BONUS for hidden places
        if spot.get('is_hidden', False):
            base_score += 2.0  # Major boost for hidden spots
        
        # Additional bonus for spots with "hidden" tags
        spot_tags = spot.get("tags", [])
        if any(tag in ["hidden", "secret", "offbeat", "local"] for tag in spot_tags):
            base_score += 1.5  # Boost for hidden-tagged spots
        
        # Bonus points for higher ratings
        rating = spot.get("rating", 0)
        if rating > 4.0:
            base_score += 0.5
        elif rating > 3.5:
            base_score += 0.2
        
        # Reduced penalty for expensive spots (hidden gems can be valuable)
        cost = spot.get("estimated_cost", 0)
        if cost > 5000:
            base_score -= 0.2  # Reduced from 0.3
        
        return max(0, base_score)
        
    except (KeyError, TypeError) as e:
        logger.warning(f"Error calculating priority score: {e}")
        return 0


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
    except (ValueError, TypeError):
        return False, "Invalid budget format"
    
    try:
        start_date = datetime.strptime(data["start_date"], '%Y-%m-%d').date()
        end_date = datetime.strptime(data["end_date"], '%Y-%m-%d').date()
        
        if start_date > end_date:
            return False, "Start date must be before end date"
            
        # Check if dates are too far in the past
        if start_date < datetime.now().date():
            return False, "Start date cannot be in the past"
            
        # Check if trip is too long (max 30 days)
        if (end_date - start_date).days > 30:
            return False, "Trip duration cannot exceed 30 days"
            
    except ValueError:
        return False, "Invalid date format. Use YYYY-MM-DD"
    
    return True, ""


def optimize_itinerary_schedule(spots, duration, daily_hours=8):
    """Optimize the scheduling of spots across days."""
    if not spots:
        return {}
    
    # Sort spots by priority and estimated time
    sorted_spots = sorted(spots, key=lambda x: (
        -get_priority_score(x, []),  # Higher priority first
        x.get("avg_time", 2)  # Shorter activities first for same priority
    ))
    
    day_schedules = {f"Day {i+1}": [] for i in range(duration)}
    current_day = 0
    current_day_time = 0
    
    for spot in sorted_spots:
        spot_time = spot.get("avg_time", 2)
        
        # Check if spot fits in current day
        if current_day_time + spot_time <= daily_hours:
            day_schedules[f"Day {current_day + 1}"].append(spot)
            current_day_time += spot_time
        else:
            # Move to next day
            current_day += 1
            if current_day >= duration:
                break  # No more days available
            
            day_schedules[f"Day {current_day + 1}"].append(spot)
            current_day_time = spot_time
    
    return day_schedules


def add_meal_breaks(day_itinerary, restaurants, current_hour, day_num):
    """Add meal breaks to the day's itinerary."""
    meals_added = []
    
    # Breakfast (8-10 AM)
    if 8 <= current_hour < 10 and restaurants:
        breakfast_spot = min(restaurants, key=lambda x: x.get("estimated_cost", 0))
        meals_added.append({
            "time": format_time_from_float(current_hour),
            "activity": f"Breakfast at {breakfast_spot['name']}",
            "duration_hours": 1,
            "type": "restaurant",
            "cost": breakfast_spot.get("estimated_cost", 0) * 0.3  # 30% of restaurant cost for breakfast
        })
        current_hour += 1
    
    # Lunch (12-3 PM)
    if 12 <= current_hour < 15 and restaurants:
        lunch_spot = restaurants[day_num % len(restaurants)]  # Rotate restaurants
        meals_added.append({
            "time": format_time_from_float(current_hour),
            "activity": f"Lunch at {lunch_spot['name']}",
            "duration_hours": 1,
            "type": "restaurant",
            "cost": lunch_spot.get("estimated_cost", 0)
        })
        current_hour += 1
    
    # Dinner (7-9 PM)
    if 19 <= current_hour < 21 and restaurants:
        dinner_spot = max(restaurants, key=lambda x: x.get("rating", 0))  # Best rated for dinner
        meals_added.append({
            "time": format_time_from_float(current_hour),
            "activity": f"Dinner at {dinner_spot['name']}",
            "duration_hours": 1.5,
            "type": "restaurant",
            "cost": dinner_spot.get("estimated_cost", 0) * 1.2  # 20% more for dinner
        })
        current_hour += 1.5
    
    return meals_added, current_hour


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsUser])
def generate_itinerary(request):
    """Generate a comprehensive travel itinerary with live API integration and hidden places prioritization."""
    
    try:
        # Get user ID from authentication
        user_id = request.auth.get("user_id")
        if not user_id:
            return Response(
                {"error": "Authentication required"}, 
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        data = request.data
        logger.info(f"Generating itinerary for user {user_id}")
        
        # Validate request data
        is_valid, error_message = validate_request_data(data)
        if not is_valid:
            return Response(
                {"error": error_message}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Extract request parameters
        origin = data["starting_location"].strip()
        destination = data["destination"].strip()
        budget = float(data["budget"])
        interests = data.get("interests", [])
        travel_type = data.get("travel_type", "solo")
        
        # Parse dates
        start_date = datetime.strptime(data["start_date"], '%Y-%m-%d').date()
        end_date = datetime.strptime(data["end_date"], '%Y-%m-%d').date()
        duration = (end_date - start_date).days + 1
        
        logger.info(f"Trip details: {origin} -> {destination}, {duration} days, ₹{budget}")
        
        # Get ML budget prediction
        try:
            predicted_budget = predict_budget({
                "destination": destination,
                "duration": duration,
                "travel_type": travel_type,
                "interest": interests[0] if interests else "general"
            })
        except Exception as e:
            logger.warning(f"Budget prediction failed: {e}")
            predicted_budget = budget * 1.1  # 10% buffer as fallback
        
        # Fetch route information with caching
        route_cache_key = f"route_{hash(origin)}_{hash(destination)}"
        route = get_cached_or_fetch(route_cache_key, get_route_info, origin, destination)
        
        if not route:
            logger.warning("Route API failed, using fallback")
            route = {
                "origin": origin,
                "destination": destination,
                "distance_km": 200,
                "duration_hours": 6.0
            }
        
        initial_travel_time = route.get('duration_hours', 6.0)
        
        # Fetch places and hidden spots with caching
        places_cache_key = f"places_{hash(destination)}_{'_'.join(sorted(interests))}"
        pois = get_cached_or_fetch(places_cache_key, get_places, destination, interests)
        
        hidden_cache_key = f"hidden_{hash(destination)}_{'_'.join(sorted(interests))}"
        hidden = get_cached_or_fetch(hidden_cache_key, get_hidden_spots, destination, interests)
        
        # Handle API failures gracefully
        if not pois:
            pois = []
            logger.warning("Places API failed, using empty list")
        
        if not hidden:
            hidden = []
            logger.warning("Hidden spots API failed, using empty list")
        
        # Mark hidden spots explicitly
        for spot in hidden:
            spot['is_hidden'] = True
            if 'tags' not in spot:
                spot['tags'] = ['hidden']
        
        # Combine and deduplicate spots
        all_spots_dict = {}
        for spot in pois + hidden:
            spot_name = spot.get('name', 'Unknown')
            if spot_name not in all_spots_dict:
                # Add priority score to each spot
                spot['priority_score'] = get_priority_score(spot, interests)
                all_spots_dict[spot_name] = spot
        
        all_spots = list(all_spots_dict.values())
        
        # Log hidden spots found
        hidden_count = sum(1 for spot in all_spots if spot.get('is_hidden', False))
        logger.info(f"Found {hidden_count} hidden spots out of {len(all_spots)} total spots")
        
        # Categorize spots
        hotels = sorted(
            [s for s in all_spots if s.get("type") == "hotel"], 
            key=lambda x: x.get('estimated_cost', 0)
        )
        restaurants = sorted(
            [s for s in all_spots if s.get("type") == "restaurant"], 
            key=lambda x: x.get('estimated_cost', 0)
        )
        attractions = [s for s in all_spots if s.get("type") not in ("hotel", "restaurant")]
        
        # Budget allocation
        cost_accumulated = 0
        hotel_cost_total = 0
        chosen_hotel = None
        alternative_hotels = []
        
        # Select hotel within 50% of budget
        hotel_budget_limit = budget * 0.5
        
        if hotels:
            num_nights = max(1, duration - 1)
            for hotel in hotels:
                potential_cost = hotel.get("estimated_cost", 1000) * num_nights
                if chosen_hotel is None and potential_cost <= hotel_budget_limit:
                    chosen_hotel = hotel
                    hotel_cost_total = potential_cost
                    cost_accumulated += hotel_cost_total
                    break
            
            # Store alternatives
            alternative_hotels = [h for h in hotels if h != chosen_hotel][:5]
        
        # Select attractions within remaining budget
        attraction_budget = budget - cost_accumulated
        meal_budget = budget * 0.3  # 30% for meals
        activity_budget = attraction_budget - meal_budget
        
        # Filter and sort attractions by priority and cost
        affordable_attractions = [
            a for a in attractions 
            if a.get("estimated_cost", 0) <= activity_budget * 0.4  # Max 40% of activity budget per attraction
        ]
        
        # Sort by priority score (hidden places will have highest scores)
        sorted_attractions = sorted(
            affordable_attractions, 
            key=lambda x: (-x.get("priority_score", 0), x.get("estimated_cost", 0))
        )
        
        # Log priority distribution
        high_priority = [s for s in sorted_attractions if s.get("priority_score", 0) >= 2.0]
        logger.info(f"High priority spots (likely hidden): {len(high_priority)}")
        
        # Select final attractions
        final_itinerary_spots = []
        alternative_attractions = []
        temp_budget = activity_budget
        temp_time = duration * 8 - initial_travel_time  # 8 hours per day minus initial travel
        
        for spot in sorted_attractions:
            spot_cost = spot.get("estimated_cost", 0)
            spot_time = spot.get("avg_time", 2)
            
            if temp_time >= spot_time and temp_budget >= spot_cost:
                final_itinerary_spots.append(spot)
                temp_time -= spot_time
                temp_budget -= spot_cost
                cost_accumulated += spot_cost
            else:
                alternative_attractions.append(spot)
        
        # Build day-wise itinerary
        day_wise_itinerary = {f"Day {i+1}": [] for i in range(duration)}
        current_hour_float = 8.0  # Start at 8 AM
        current_day = 1
        
        # Starting location (hotel or first attraction)
        current_location = (
            chosen_hotel.get('location', {"lat": 10.0, "lng": 77.0}) 
            if chosen_hotel 
            else (final_itinerary_spots[0].get('location', {"lat": 10.0, "lng": 77.0}) 
                  if final_itinerary_spots else {"lat": 10.0, "lng": 77.0})
        )
        
        # Day 1: Initial travel
        day_wise_itinerary[f"Day {current_day}"].append({
            "time": format_time_from_float(current_hour_float),
            "activity": f"Travel from {origin} to {destination}",
            "duration_hours": initial_travel_time,
            "type": "travel",
            "description": f"Distance: {route.get('distance_km', 'N/A')} km"
        })
        current_hour_float += initial_travel_time
        time_used_today = initial_travel_time
        
        # Add check-in if hotel is available
        if chosen_hotel and current_hour_float >= 14.0:  # Check-in after 2 PM
            day_wise_itinerary[f"Day {current_day}"].append({
                "time": format_time_from_float(current_hour_float),
                "activity": f"Check-in at {chosen_hotel['name']}",
                "duration_hours": 0.5,
                "type": "hotel",
                "cost": 0  # Cost already accounted for
            })
            current_hour_float += 0.5
            time_used_today += 0.5
        
        # Distribute attractions across days
        daily_activity_hours = 8
        meals_added_today = False
        
        for spot in final_itinerary_spots:
            spot_time = spot.get("avg_time", 2)
            travel_to_spot = estimate_internal_travel_time(current_location, spot.get('location', current_location))
            total_time_needed = travel_to_spot + spot_time
            
            # Check if we need to move to next day
            if (time_used_today + total_time_needed > daily_activity_hours and 
                current_day < duration):
                
                # Add dinner if we haven't added meals today and it's evening
                if not meals_added_today and current_hour_float >= 19.0 and restaurants:
                    dinner_spot = restaurants[0]
                    day_wise_itinerary[f"Day {current_day}"].append({
                        "time": format_time_from_float(current_hour_float),
                        "activity": f"Dinner at {dinner_spot['name']}",
                        "duration_hours": 1.5,
                        "type": "restaurant",
                        "cost": dinner_spot.get("estimated_cost", 0)
                    })
                    cost_accumulated += dinner_spot.get("estimated_cost", 0)
                
                # Move to next day
                current_day += 1
                current_hour_float = 8.0
                time_used_today = 0
                meals_added_today = False
                
                if chosen_hotel:
                    current_location = chosen_hotel.get('location', current_location)
                
                travel_to_spot = estimate_internal_travel_time(current_location, spot.get('location', current_location))
            
            # Skip if we've run out of days
            if current_day > duration:
                alternative_attractions.append(spot)
                continue
            
            # Add meal breaks if appropriate time
            if not meals_added_today and 12 <= current_hour_float < 14 and restaurants:
                lunch_spot = restaurants[current_day % len(restaurants)]
                day_wise_itinerary[f"Day {current_day}"].append({
                    "time": format_time_from_float(current_hour_float),
                    "activity": f"Lunch at {lunch_spot['name']}",
                    "duration_hours": 1,
                    "type": "restaurant",
                    "cost": lunch_spot.get("estimated_cost", 0)
                })
                current_hour_float += 1
                time_used_today += 1
                cost_accumulated += lunch_spot.get("estimated_cost", 0)
                meals_added_today = True
            
            # Add travel to spot
            if travel_to_spot > 0.1:  # Only if significant travel time
                day_wise_itinerary[f"Day {current_day}"].append({
                    "time": format_time_from_float(current_hour_float),
                    "activity": f"Travel to {spot['name']}",
                    "duration_hours": travel_to_spot,
                    "type": "travel"
                })
                current_hour_float += travel_to_spot
                time_used_today += travel_to_spot
            
            # Add the main activity with weather info
            activity_date = start_date + timedelta(days=current_day - 1)
            weather_cache_key = f"weather_{spot.get('location', {}).get('lat', 0)}_{spot.get('location', {}).get('lng', 0)}_{activity_date}"
            weather_info = get_cached_or_fetch(
                weather_cache_key, 
                get_weather, 
                spot.get('location', current_location), 
                activity_date
            )
            
            activity_entry = {
                "time": format_time_from_float(current_hour_float),
                "activity": spot['name'],
                "duration_hours": spot_time,
                "type": spot.get('type', 'attraction'),
                "cost": spot.get("estimated_cost", 0),
                "description": spot.get("description", ""),
                "rating": spot.get("rating", 0)
            }
            
            # Add hidden gem indicator
            if spot.get('is_hidden', False):
                activity_entry["is_hidden_gem"] = True
                activity_entry["description"] = (activity_entry["description"] + 
                    " [Hidden Gem]").strip()
            
            if weather_info:
                activity_entry["weather"] = weather_info
            
            day_wise_itinerary[f"Day {current_day}"].append(activity_entry)
            
            current_hour_float += spot_time
            time_used_today += spot_time
            current_location = spot.get('location', current_location)
        
        # Add hotel stays for each night (except last day)
        if chosen_hotel:
            for day_num in range(1, duration):
                day_wise_itinerary[f"Day {day_num}"].append({
                    "time": "09:00 PM",
                    "activity": f"Stay at {chosen_hotel['name']}",
                    "type": "hotel",
                    "description": f"Night {day_num} accommodation"
                })
        
        # Final day: Return travel
        if duration > 1:
            day_wise_itinerary[f"Day {duration}"].append({
                "time": "06:00 PM",
                "activity": f"Return travel to {origin}",
                "duration_hours": initial_travel_time,
                "type": "travel"
            })
        
        # Calculate final costs
        meal_costs = sum(
            activity.get("cost", 0) 
            for day_activities in day_wise_itinerary.values()
            for activity in day_activities
            if activity.get("type") == "restaurant"
        )
        
        activity_costs = sum(
            activity.get("cost", 0)
            for day_activities in day_wise_itinerary.values()
            for activity in day_activities
            if activity.get("type") not in ("restaurant", "hotel", "travel")
        )
        
        total_cost = hotel_cost_total + meal_costs + activity_costs
        
        # Count hidden gems in final itinerary
        hidden_gems_count = sum(
            1 for day_activities in day_wise_itinerary.values()
            for activity in day_activities
            if activity.get("is_hidden_gem", False)
        )
        
        # Prepare response
        response_data = {
            "user_id": user_id,
            "day_wise_itinerary": day_wise_itinerary,
            "hotel_details": {
                "name": chosen_hotel["name"],
                "cost_per_night": chosen_hotel["estimated_cost"],
                "total_nights": max(1, duration - 1),
                "total_cost": hotel_cost_total,
                "rating": chosen_hotel.get("rating", 0),
                "location": chosen_hotel.get("location", {})
            } if chosen_hotel else None,
            "alternatives": {
                "hotels": alternative_hotels[:5],
                "attractions": alternative_attractions[:10]
            },
            "cost_breakdown": {
                "accommodation": hotel_cost_total,
                "activities": activity_costs,
                "meals": meal_costs,
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
                "total_attractions": len(final_itinerary_spots),
                "hidden_gems_count": hidden_gems_count,  # New field
                "budget_utilization": round((total_cost / budget) * 100, 1)
            },
            "route_info": route,
            "status": "success",
            "generated_at": datetime.now().isoformat()
        }
        
        # Save to MongoDB
        try:
            user_itinerary = UserItinerary(
                user_id=user_id, 
                itinerary_data=response_data
            )
            user_itinerary.save()
            logger.info(f"Itinerary saved successfully for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to save itinerary: {e}")
            # Continue without failing the request
        
        logger.info(f"Itinerary generated successfully: {len(final_itinerary_spots)} spots, ₹{total_cost}, {hidden_gems_count} hidden gems")
        return Response(response_data, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Unexpected error in generate_itinerary: {str(e)}", exc_info=True)
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
