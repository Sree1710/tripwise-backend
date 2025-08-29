from django.urls import path
from .admin_backend import *
from .user_backend import *
from . import user_itinerary
from .pdf_export import ExportPDFView

urlpatterns = [

    # Single Login (Admin + User)
    path("login/", LoginView.as_view()),

    # Admin
    path("admin/destinations/", DestinationAdminView.as_view({"get": "list"})),
    path("admin/destination/<str:pk>/", DestinationAdminView.as_view({"put": "update", "delete": "destroy"})),
    path("admin/emergency/", EmergencyInfoView.as_view({"get": "list", "post": "create"})),
    path("admin/tags/", MetadataTagView.as_view({"get": "list", "post": "create"})),
    path("admin/users/", AdminUserView.as_view()), # View all users
    path("admin/approve-user/", ApproveUserView.as_view()), # Approve user
    path("admin/complaints/", AdminComplaintView.as_view()),
    path("admin/analytics/", AdminAnalyticsView.as_view()),
    path("admin/suggestions/", DestinationSuggestionAdminView.as_view({"get": "list", "delete": "destroy"})),

    # User
    path("user/register/", RegisterUser.as_view()),
    path("user/past-trips/", PastTrips.as_view()),
    path("user/suggest/", SuggestDestination.as_view()),
    path("user/complaint/", SubmitComplaint.as_view()),
    path("user/review/", ReviewTrip.as_view()),
    path("user/dashboard/", DashboardStats.as_view()),
    path('generate-itinerary/', user_itinerary.generate_itinerary, name='generate-itinerary'),
    path("export-itinerary-pdf/", ExportPDFView.as_view(), name="export-pdf"),
]
