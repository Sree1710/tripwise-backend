import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tripwise.settings')
django.setup()

from api.utils.google import get_route_info, get_places
from api.utils.weather import get_weather
from datetime import date

def test_all_apis():
    print("🧪 Testing APIs...")
    
    # Test Google Routes
    print("\n1. Testing Google Routes API:")
    route = get_route_info("Trivandrum", "Kochi")
    print(f"   Distance: {route.get('distance_km')} km")
    print(f"   Duration: {route.get('duration_hours')} hours")
    
    # Test Google Places
    print("\n2. Testing Google Places API:")
    places = get_places("Kochi", ["heritage", "nature"])
    print(f"   Found: {len(places)} places")
    if places:
        print(f"   Sample: {places[0]['name']}")
    
    # Test Weather
    print("\n3. Testing Weather API:")
    location = {'lat': 9.9312, 'lng': 76.2673}
    weather = get_weather(location, date.today())
    print(f"   Condition: {weather.get('condition')}")
    print(f"   Temperature: {weather.get('temp_c')}°C")
    
    print("\n✅ All tests completed!")

if __name__ == "__main__":
    test_all_apis()
