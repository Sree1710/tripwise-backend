import requests
from django.conf import settings
from datetime import date as dt_date

def get_weather(location, date):
    """
    Get weather forecast using OpenWeatherMap API or mock data.
    """
    if getattr(settings, "MOCK_API", False):
        # Your existing mock data
        conditions = ["Sunny", "Partly Cloudy", "Clear Skies", "Light Showers"]
        condition = conditions[date.day % len(conditions)]
        temp = 28 + (date.day % 5) - 2
        
        return {
            "condition": condition,
            "temp_c": temp,
            "location": location,
            "date": date.strftime('%Y-%m-%d')
        }

    try:
        api_key = getattr(settings, 'OPENWEATHER_API_KEY', None)
        if not api_key:
            raise Exception("OpenWeatherMap API key not configured")

        # Current weather (for today) or forecast (for future dates)
        today = dt_date.today()
        
        if date == today:
            # Current weather
            url = "https://api.openweathermap.org/data/2.5/weather"
            params = {
                'lat': location['lat'],
                'lon': location['lng'],
                'appid': api_key,
                'units': 'metric'
            }
        else:
            # 5-day forecast
            url = "https://api.openweathermap.org/data/2.5/forecast"
            params = {
                'lat': location['lat'],
                'lon': location['lng'],
                'appid': api_key,
                'units': 'metric'
            }

        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if date == today:
            # Current weather response
            return {
                "condition": data['weather'][0]['description'].title(),
                "temp_c": round(data['main']['temp']),
                "location": location,
                "date": date.strftime('%Y-%m-%d'),
                "humidity": data['main']['humidity'],
                "wind_speed": data['wind']['speed']
            }
        else:
            # Find forecast for the specific date
            target_date_str = date.strftime('%Y-%m-%d')
            
            for forecast in data['list']:
                forecast_date = forecast['dt_txt'][:10]
                if forecast_date == target_date_str:
                    return {
                        "condition": forecast['weather'][0]['description'].title(),
                        "temp_c": round(forecast['main']['temp']),
                        "location": location,
                        "date": date.strftime('%Y-%m-%d'),
                        "humidity": forecast['main']['humidity'],
                        "wind_speed": forecast['wind']['speed']
                    }
            
            # If no exact match found, return average for that date
            return {
                "condition": "Partly Cloudy",
                "temp_c": 28,
                "location": location,
                "date": date.strftime('%Y-%m-%d')
            }

    except Exception as e:
        print(f"Weather API error: {e}")
        # Fallback to mock data
        conditions = ["Sunny", "Partly Cloudy", "Clear Skies", "Light Showers"]
        condition = conditions[date.day % len(conditions)]
        temp = 28 + (date.day % 5) - 2
        
        return {
            "condition": condition,
            "temp_c": temp,
            "location": location,
            "date": date.strftime('%Y-%m-%d')
        }
