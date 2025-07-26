from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from .utils.google import get_route_info, get_places
from .utils.weather import get_weather
from .ml.predict import predict_budget
from .utils.db import get_hidden_spots
from datetime import datetime, timedelta, time
import math

# --- Helper Functions (no changes here) ---

def estimate_internal_travel_time(loc1, loc2):
    lat1, lon1 = loc1['lat'], loc1['lng']
    lat2, lon2 = loc2['lat'], loc2['lng']
    distance = math.sqrt((lat1 - lat2)**2 + (lon1 - lon2)**2)
    travel_hours = distance * 1.5
    return round(travel_hours, 2)

def format_time_from_float(hour_float):
    hours = int(hour_float)
    minutes = int((hour_float * 60) % 60)
    time_obj = time(hour=hours % 24, minute=minutes)
    return time_obj.strftime("%I:%M %p")

def get_priority_score(spot, interests):
    return 1 if spot["type"] in interests else 0


@api_view(['POST'])
def generate_itinerary(request):
    data = request.data
    origin = data["starting_location"]
    destination = data["destination"]
    
    # --- MODIFICATION: Use start and end dates ---
    try:
        start_date_str = data["start_date"]
        end_date_str = data["end_date"]
        # Convert string dates (YYYY-MM-DD) to date objects
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        
        if start_date > end_date:
            return Response({"error": "Start date must be before end date."}, status=status.HTTP_400_BAD_REQUEST)
            
        # Calculate duration (inclusive of the end date)
        duration = (end_date - start_date).days + 1
        
    except (KeyError, ValueError):
        return Response({"error": "Please provide valid 'start_date' and 'end_date' in YYYY-MM-DD format."}, status=status.HTTP_400_BAD_REQUEST)
    # --- END OF MODIFICATION ---
    
    budget = int(data["budget"])
    interests = data.get("interests", [])
    travel_type = data.get("travel_type", "solo")

    # 1. Predict Budget & Get Route
    predicted_budget = predict_budget({
        "destination": destination, "duration": duration,
        "travel_type": travel_type, "interest": interests[0] if interests else "general"
    })
    route = get_route_info(origin, destination)
    initial_travel_time = route['duration_hours']

    # 2. Get, De-duplicate, and Categorize Spots
    pois = get_places(destination, interests)
    hidden = get_hidden_spots(destination, interests)
    
    all_spots_dict = {spot['name']: spot for spot in pois + hidden}
    all_spots = list(all_spots_dict.values())
    
    hotels = sorted([s for s in all_spots if s["type"] == "hotel"], key=lambda x: x['estimated_cost'])
    restaurants = sorted([s for s in all_spots if s["type"] == "restaurant"], key=lambda x: x['estimated_cost'])
    attractions = [s for s in all_spots if s["type"] not in ("hotel", "restaurant")]

    # 3. Reserve Budget for Hotel & Set up Alternatives
    cost_accumulated = 0
    hotel_cost_total = 0
    chosen_hotel = None
    alternative_hotels = []
    
    if hotels:
        for hotel in hotels:
            # Hotel cost is for n-1 nights
            num_nights = duration - 1 if duration > 1 else 1
            potential_cost = hotel["estimated_cost"] * num_nights
            if chosen_hotel is None and potential_cost <= budget * 0.6:
                chosen_hotel = hotel
                hotel_cost_total = potential_cost
                cost_accumulated += hotel_cost_total
            else:
                alternative_hotels.append(hotel)
    
    attraction_budget = budget - cost_accumulated
    
    # 4. Select Attractions & Set up Alternatives
    for spot in attractions:
        spot["priority_score"] = get_priority_score(spot, interests)
    sorted_attractions = sorted(attractions, key=lambda x: (x["priority_score"], -x["estimated_cost"]), reverse=True)
    
    daily_activity_hours = 8 
    final_itinerary_spots = []
    alternative_attractions = []
    
    temp_time = (duration * daily_activity_hours) - initial_travel_time
    temp_budget = attraction_budget
    for spot in sorted_attractions:
        if temp_time >= spot["avg_time"] and temp_budget >= spot["estimated_cost"]:
            final_itinerary_spots.append(spot)
            temp_time -= spot["avg_time"]
            temp_budget -= spot["estimated_cost"]
            cost_accumulated += spot["estimated_cost"]
        else:
            alternative_attractions.append(spot)

    # 5. Build Day-wise Itinerary
    day_wise_itinerary = {f"Day {i+1}": [] for i in range(duration)}
    current_hour_float = 8.0
    current_day = 1
    
    current_location = chosen_hotel['location'] if chosen_hotel else (final_itinerary_spots[0]['location'] if final_itinerary_spots else {"lat": 0, "lng": 0})

    day_wise_itinerary[f"Day {current_day}"].append({
        "time": format_time_from_float(current_hour_float),
        "activity": "Travel to destination",
        "duration_hours": initial_travel_time
    })
    current_hour_float += initial_travel_time
    time_used_today = initial_travel_time
    lunch_added_today = False

    for spot in final_itinerary_spots:
        travel_to_next_spot = estimate_internal_travel_time(current_location, spot['location'])
        
        if not lunch_added_today and current_hour_float >= 12.5 and restaurants:
            # ... (lunch logic remains the same) ...
            pass # Placeholder for brevity

        if time_used_today + travel_to_next_spot + spot["avg_time"] > daily_activity_hours and current_day < duration:
            current_day += 1
            current_hour_float = 8.0
            time_used_today = 0
            lunch_added_today = False
            current_location = chosen_hotel['location'] if chosen_hotel else current_location
            travel_to_next_spot = estimate_internal_travel_time(current_location, spot['location'])

        if current_day <= duration and time_used_today + travel_to_next_spot + spot["avg_time"] <= daily_activity_hours:
            # --- MODIFICATION: Get date for the current day ---
            activity_date = start_date + timedelta(days=current_day - 1)
            # --- END OF MODIFICATION ---
            
            day_wise_itinerary[f"Day {current_day}"].append({"time": format_time_from_float(current_hour_float), "activity": f"Travel to {spot['name']}", "duration_hours": travel_to_next_spot})
            current_hour_float += travel_to_next_spot
            time_used_today += travel_to_next_spot
            
            day_wise_itinerary[f"Day {current_day}"].append({
                "time": format_time_from_float(current_hour_float), 
                "activity": spot["name"], 
                "duration_hours": spot["avg_time"], 
                # --- MODIFICATION: Pass date to weather function ---
                "weather": get_weather(spot['location'], activity_date)
            })
            current_hour_float += spot["avg_time"]
            time_used_today += spot["avg_time"]
            current_location = spot['location']

    # Add Nightly Hotel Stays
    if chosen_hotel:
        for day_num in range(1, duration):
            day_wise_itinerary[f"Day {day_num}"].append({
                "time": "09:00 PM",
                "activity": f"Check-in / Stay at {chosen_hotel['name']}",
                "type": "hotel"
            })

    # Day N: Return Travel
    if duration > 0:
        day_wise_itinerary[f"Day {duration}"].append({
            "time": "06:00 PM",
            "activity": "Return travel",
            "duration_hours": initial_travel_time
        })

    return Response({
        "day_wise_itinerary": day_wise_itinerary,
        "hotel_details": { "name": chosen_hotel["name"], "cost_per_night": chosen_hotel["estimated_cost"] } if chosen_hotel else None,
        "alternatives": { "hotels": alternative_hotels, "attractions": alternative_attractions },
        "summary": {
            "total_days": duration,
            "start_date": start_date_str,
            "end_date": end_date_str,
            "proposed_budget": budget,
            "predicted_budget": predicted_budget,
            "actual_cost": round(cost_accumulated),
        },
        "status": "success"
    })