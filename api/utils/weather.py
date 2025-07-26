from django.conf import settings
import datetime

def get_weather(location, date):
    """
    Returns a mock weather forecast based on the location and date.
    """
    if settings.MOCK_API:
        # Make the mock weather dynamic based on the day
        conditions = ["Sunny", "Partly Cloudy", "Clear Skies", "Light Showers"]
        # Use the day of the month to cycle through conditions
        condition = conditions[date.day % len(conditions)]
        # Make the temperature vary slightly
        temp = 28 + (date.day % 5) - 2
        
        return {
            "condition": condition,
            "temp_c": temp
        }
        
    # TODO: Real Weather API call would use the 'date' for a forecast
    return {"condition": "N/A", "temp_c": 0}