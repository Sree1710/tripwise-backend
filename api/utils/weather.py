from django.conf import settings

def get_weather(location):
    if settings.MOCK_API:
        return {
            "condition": "Sunny",
            "temp_c": 30
        }
    # TODO: Real Weather API
    ...
