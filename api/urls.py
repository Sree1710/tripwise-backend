from django.urls import path
from .views import generate_itinerary

urlpatterns = [
    path('generate-itinerary/', generate_itinerary),
]
