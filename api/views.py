from rest_framework.decorators import api_view
from rest_framework.response import Response
from .utils.google import get_route_info, get_places
from .utils.weather import get_weather
from .ml.predict import predict_budget
from .utils.db import get_hidden_spots
import datetime

def format_time(hour):
    return datetime.time(hour=hour).strftime("%I:%M %p")

def get_priority_score(spot, interests):
    return 1 if spot["type"] in interests else 0

@api_view(['POST'])
def generate_itinerary(request):
    data = request.data
    origin = data["starting_location"]
    destination = data["destination"]
    duration = int(data["duration"])  # in days
    budget = int(data["budget"])
    interests = data.get("interests", [])
    travel_type = data.get("travel_type", "solo")

    # Predict Budget
    predicted_budget = predict_budget({
        "destination": destination,
        "duration": duration,
        "travel_type": travel_type,
        "interest": interests[0] if interests else "general"
    })

    # Route Info
    route = get_route_info(origin, destination)
    travel_time = route['duration_hours']

    # Get Spots
    pois = get_places(route["route"], interests)
    hidden = get_hidden_spots(destination, interests)
    all_spots = pois + hidden

    # Categorize
    hotels = [s for s in all_spots if s["type"] == "hotel"]
    restaurants = [s for s in all_spots if s["type"] == "restaurant"]
    attractions = [s for s in all_spots if s["type"] not in ("hotel", "restaurant")]

    # Prioritize Attractions
    for spot in attractions:
        spot["priority_score"] = get_priority_score(spot, interests)
    sorted_attractions = sorted(attractions, key=lambda x: (x["priority_score"], -x["estimated_cost"]), reverse=True)

    # Itinerary Plan
    total_time_available = duration * 8
    time_remaining = total_time_available - travel_time
    cost_accumulated = 0
    itinerary = []

    # Add Attractions (within budget & time)
    for spot in sorted_attractions:
        if time_remaining < spot["avg_time"] or cost_accumulated + spot["estimated_cost"] > budget:
            continue
        spot_copy = spot.copy()
        spot_copy["weather"] = get_weather(spot["location"])
        itinerary.append(spot_copy)
        time_remaining -= spot["avg_time"]
        cost_accumulated += spot["estimated_cost"]

    # Choose one hotel
    hotel_spot = None
    hotel_cost_total = 0
    if hotels:
        hotel_spot = hotels[0]
        hotel_spot["weather"] = get_weather(hotel_spot["location"])
        hotel_cost_total = hotel_spot["estimated_cost"] * (duration - 1)
        if cost_accumulated + hotel_cost_total <= budget:
            cost_accumulated += hotel_cost_total
        else:
            hotel_spot = None

    # Day-wise Itinerary Generation
    day_wise_itinerary = {}
    day = 1
    current_hour = 8  # Start at 08:00 AM
    max_activity_days = duration - 1

    # Day 1 Travel
    day_wise_itinerary[f"Day {day}"] = [{
        "time": format_time(current_hour),
        "activity": "Travel to destination",
        "duration_hours": travel_time
    }]
    current_hour += int(travel_time)
    time_used_today = travel_time

    for spot in itinerary:
        if day > max_activity_days:
            break
        # Move to next day if time exceeded
        if time_used_today + spot["avg_time"] > 8:
            # Add restaurant if time left
            for rest in restaurants:
                if time_used_today + rest["avg_time"] <= 8:
                    rest_entry = {
                        "name": rest["name"],
                        "type": "restaurant",
                        "duration_hours": rest["avg_time"],
                        "weather": get_weather(rest["location"]),
                        "time": format_time(current_hour)
                    }
                    day_wise_itinerary[f"Day {day}"].append(rest_entry)
                    time_used_today += rest["avg_time"]
                    current_hour += int(rest["avg_time"])
                    break

            # Add hotel if possible
            if hotel_spot and time_used_today + hotel_spot["avg_time"] <= 8:
                hotel_entry = {
                    "name": hotel_spot["name"],
                    "type": "hotel",
                    "duration_hours": hotel_spot["avg_time"],
                    "weather": hotel_spot["weather"],
                    "time": format_time(current_hour)
                }
                day_wise_itinerary[f"Day {day}"].append(hotel_entry)
                time_used_today += hotel_spot["avg_time"]
                current_hour += int(hotel_spot["avg_time"])

            # Next day
            day += 1
            if day > max_activity_days:
                break
            day_wise_itinerary[f"Day {day}"] = []
            time_used_today = 0
            current_hour = 8

        # Add current attraction
        entry = {
            "name": spot["name"],
            "type": spot["type"],
            "duration_hours": spot["avg_time"],
            "weather": spot["weather"],
            "time": format_time(current_hour)
        }
        day_wise_itinerary[f"Day {day}"].append(entry)
        time_used_today += spot["avg_time"]
        current_hour += int(spot["avg_time"])

    # Add final hotel stay
    if day <= max_activity_days and hotel_spot and time_used_today + hotel_spot["avg_time"] <= 8:
        hotel_entry = {
            "name": hotel_spot["name"],
            "type": "hotel",
            "duration_hours": hotel_spot["avg_time"],
            "weather": hotel_spot["weather"],
            "time": format_time(current_hour)
        }
        day_wise_itinerary[f"Day {day}"].append(hotel_entry)

    # Day N – Return
    day_wise_itinerary[f"Day {duration}"] = [{
        "time": "06:00 PM",
        "activity": "Return travel",
        "duration_hours": travel_time
    }]

    return Response({
        "day_wise_itinerary": day_wise_itinerary,
        "total_days": duration,
        "proposed_budget": budget,
        "predicted_budget": predicted_budget,
        "actual_cost": cost_accumulated,
        "hotel_cost": hotel_cost_total,
        "actual_time_used": total_time_available - time_remaining,
        "travel_time": travel_time,
        "status": "success"
    })
