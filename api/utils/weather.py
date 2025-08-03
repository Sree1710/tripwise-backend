from django.conf import settings
from datetime import date as dt_date

def get_weather(location, date):
    """
    Returns a mock weather forecast based on the location and date.

    Args:
        location (dict): A dictionary with 'lat' and 'lng' keys.
        date (datetime.date): The forecast date.

    Returns:
        dict: A mock forecast with condition, temperature, location, and date.
    """
    if getattr(settings, "MOCK_API", False):
        # Dynamic weather based on day of month
        conditions = ["Sunny", "Partly Cloudy", "Clear Skies", "Light Showers"]
        condition = conditions[date.day % len(conditions)]
        temp = 28 + (date.day % 5) - 2  # Generates values between 26-30

        return {
            "condition": condition,
            "temp_c": temp,
            "location": location,
            "date": date.strftime('%Y-%m-%d')
        }

    # TODO: Replace with real API call in production
    return {
        "condition": "N/A",
        "temp_c": 0,
        "location": location,
        "date": date.strftime('%Y-%m-%d')
    }
