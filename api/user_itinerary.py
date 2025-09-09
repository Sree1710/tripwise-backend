from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response
from rest_framework import status
from .ml.predict import predict_budget
from .utils.google import get_route_info, get_places
from .utils.weather import get_weather
from .utils.db import get_hidden_spots
from datetime import datetime, timedelta, time
import math
from api.auth import JWTAuthentication
from api.permissions import IsUser
from api.models import UserItinerary

#Mock Code
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
@authentication_classes([JWTAuthentication])
@permission_classes([IsUser])
def generate_itinerary(request):
    user_id = request.auth.get("user_id")
    data = request.data
    origin = data["starting_location"]
    destination = data["destination"]

    try:
        start_date = datetime.strptime(data["start_date"], '%Y-%m-%d').date()
        end_date = datetime.strptime(data["end_date"], '%Y-%m-%d').date()
        if start_date > end_date:
            return Response({"error": "Start date must be before end date."}, status=status.HTTP_400_BAD_REQUEST)
        duration = (end_date - start_date).days + 1
    except (KeyError, ValueError):
        return Response({"error": "Invalid start or end date."}, status=status.HTTP_400_BAD_REQUEST)

    budget = int(data["budget"])
    interests = data.get("interests", [])
    travel_type = data.get("travel_type", "solo")

    predicted_budget = predict_budget({
        "destination": destination,
        "duration": duration,
        "travel_type": travel_type,
        "interest": interests[0] if interests else "general"
    })
    route = get_route_info(origin, destination)
    initial_travel_time = route['duration_hours']

    pois = get_places(destination, interests)
    hidden = get_hidden_spots(destination, interests)

    all_spots_dict = {spot['name']: spot for spot in pois + hidden}
    all_spots = list(all_spots_dict.values())

    hotels = sorted([s for s in all_spots if s["type"] == "hotel"], key=lambda x: x['estimated_cost'])
    restaurants = sorted([s for s in all_spots if s["type"] == "restaurant"], key=lambda x: x['estimated_cost'])
    attractions = [s for s in all_spots if s["type"] not in ("hotel", "restaurant")]

    cost_accumulated = 0
    hotel_cost_total = 0
    chosen_hotel = None
    alternative_hotels = []

    if hotels:
        for hotel in hotels:
            num_nights = duration - 1 if duration > 1 else 1
            potential_cost = hotel["estimated_cost"] * num_nights
            if chosen_hotel is None and potential_cost <= budget * 0.6:
                chosen_hotel = hotel
                hotel_cost_total = potential_cost
                cost_accumulated += hotel_cost_total
            else:
                alternative_hotels.append(hotel)

    attraction_budget = budget - cost_accumulated

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

        # ✅ Add lunch stop if not already done & it's past 1 PM
        if not lunch_added_today and current_hour_float >= 13.0 and restaurants:
            chosen_restaurant = restaurants[0]  # pick cheapest/best
            day_wise_itinerary[f"Day {current_day}"].append({
                "time": format_time_from_float(current_hour_float),
                "activity": f"Lunch at {chosen_restaurant['name']}",
                "duration_hours": 1,
                "type": "restaurant"
            })
            current_hour_float += 1
            time_used_today += 1
            cost_accumulated += chosen_restaurant["estimated_cost"]
            lunch_added_today = True
            current_location = chosen_restaurant['location']

        if time_used_today + travel_to_next_spot + spot["avg_time"] > daily_activity_hours and current_day < duration:
            current_day += 1
            current_hour_float = 8.0
            time_used_today = 0
            lunch_added_today = False
            current_location = chosen_hotel['location'] if chosen_hotel else current_location
            travel_to_next_spot = estimate_internal_travel_time(current_location, spot['location'])

        if current_day <= duration and time_used_today + travel_to_next_spot + spot["avg_time"] <= daily_activity_hours:
            activity_date = start_date + timedelta(days=current_day - 1)

            day_wise_itinerary[f"Day {current_day}"].append({
                "time": format_time_from_float(current_hour_float),
                "activity": f"Travel to {spot['name']}",
                "duration_hours": travel_to_next_spot
            })
            current_hour_float += travel_to_next_spot
            time_used_today += travel_to_next_spot

            day_wise_itinerary[f"Day {current_day}"].append({
                "time": format_time_from_float(current_hour_float),
                "activity": spot["name"],
                "duration_hours": spot["avg_time"],
                "weather": get_weather(spot['location'], activity_date)
            })
            current_hour_float += spot["avg_time"]
            time_used_today += spot["avg_time"]
            current_location = spot['location']

    if chosen_hotel:
        for day_num in range(1, duration):
            day_wise_itinerary[f"Day {day_num}"].append({
                "time": "09:00 PM",
                "activity": f"Check-in / Stay at {chosen_hotel['name']}",
                "type": "hotel"
            })

    if duration > 0:
        day_wise_itinerary[f"Day {duration}"].append({
            "time": "06:00 PM",
            "activity": "Return travel",
            "duration_hours": initial_travel_time
        })

    response_data = {
        "user_id": user_id,
        "day_wise_itinerary": day_wise_itinerary,
        "hotel_details": {"name": chosen_hotel["name"], "cost_per_night": chosen_hotel["estimated_cost"]} if chosen_hotel else None,
        "alternatives": {"hotels": alternative_hotels, "attractions": alternative_attractions},
        "summary": {
            "total_days": duration,
            "start_date": start_date.strftime('%Y-%m-%d'),
            "end_date": end_date.strftime('%Y-%m-%d'),
            "proposed_budget": budget,
            "predicted_budget": predicted_budget,
            "actual_cost": round(cost_accumulated),
            "destination": destination
        },
        "status": "success"
    }

    # ✅ Save to MongoDB
    UserItinerary(user_id=user_id, itinerary_data=response_data).save()

    return Response(response_data, status=status.HTTP_200_OK)
