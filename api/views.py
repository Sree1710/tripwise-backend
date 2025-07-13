from rest_framework.decorators import api_view
from rest_framework.response import Response
from .utils.google import get_route_info, get_places
from .utils.weather import get_weather
from .ml.predict import predict_budget
from .utils.db import get_hidden_spots
from django.conf import settings

def get_priority_score(spot, interests):
    return 1 if spot["type"] in interests else 0

@api_view(['POST'])
def generate_itinerary(request):
    data = request.data
    origin = data["starting_location"]
    destination = data["destination"]
    duration = int(data["duration"])
    budget = int(data["budget"])
    interests = data.get("interests", [])
    travel_type = data.get("travel_type", "solo")

    predicted_budget = predict_budget({
        "destination": destination,
        "duration": duration,
        "travel_type": travel_type,
        "interest": interests[0] if interests else "general"
    })

    if predicted_budget > budget:
        return Response({"error": f"Budget too low. Predicted cost is ₹{predicted_budget}"}, status=400)

    route = get_route_info(origin, destination)
    travel_time = route['duration_hours']

    pois = get_places(route["route"], interests)
    hidden = get_hidden_spots(destination, interests)
    all_spots = pois + hidden

    hotels = [s for s in all_spots if s["type"] == "hotel"]
    restaurants = [s for s in all_spots if s["type"] == "restaurant"]
    attractions = [s for s in all_spots if s["type"] not in ("hotel", "restaurant")]

    for spot in attractions:
        spot["priority_score"] = get_priority_score(spot, interests)
    sorted_attractions = sorted(attractions, key=lambda x: (x["priority_score"], -x["estimated_cost"]), reverse=True)

    itinerary = []
    time_remaining = duration * 8 - travel_time * 2
    cost_accumulated = 0

    for spot in sorted_attractions:
        if time_remaining < spot["avg_time"] or cost_accumulated + spot["estimated_cost"] > budget:
            continue
        spot["weather"] = get_weather(spot["location"])
        itinerary.append(spot)
        time_remaining -= spot["avg_time"]
        cost_accumulated += spot["estimated_cost"]

    for rest in restaurants:
        if cost_accumulated + rest["estimated_cost"] <= budget:
            rest["weather"] = get_weather(rest["location"])
            itinerary.append(rest)
            cost_accumulated += rest["estimated_cost"]
            break

    for hotel in hotels:
        if cost_accumulated + hotel["estimated_cost"] <= budget:
            hotel["weather"] = get_weather(hotel["location"])
            itinerary.append(hotel)
            cost_accumulated += hotel["estimated_cost"]
            break

    return Response({
        "itinerary": itinerary,
        "travel_time": travel_time,
        "actual_cost": cost_accumulated,
        "actual_time_used": duration * 8 - time_remaining,
        "predicted_budget": predicted_budget,
        "status": "success"
    })
