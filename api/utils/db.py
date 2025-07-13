from django.conf import settings

def get_hidden_spots(destination, interests):
    if settings.MOCK_API:
        return [
            {
                "name": "Secret Forest Trail",
                "location": {"lat": 10.2, "lng": 77.4},
                "avg_time": 2,
                "estimated_cost": 150,
                "type": "nature"
            }
        ]
    # TODO: Real MongoDB logic
    ...
