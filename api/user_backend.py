from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db import transaction
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
import re
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from api.models import (
    UserProfile, TripLog, DestinationSuggestion, Complaint, TripReview
)
from datetime import datetime


class RegisterUser(APIView):
    def post(self, request):
        data = request.data

        # --- Extract fields ---
        email = data.get("email", "").strip()
        password = data.get("password", "").strip()
        first_name = data.get("first_name", "").strip()
        last_name = data.get("last_name", "").strip()
        dob = data.get("dob", "").strip()
        location = data.get("location", "").strip()
        contact_number = data.get("contact_number", "").strip()

        # --- Validation ---
        if not first_name:
            return Response({"error": "First name is required"}, status=status.HTTP_400_BAD_REQUEST)
        if not first_name.isalpha():
            return Response({"error": "First name should contain only letters"}, status=status.HTTP_400_BAD_REQUEST)

        if not last_name:
            return Response({"error": "Last name is required"}, status=status.HTTP_400_BAD_REQUEST)
        if not re.match(r"^[A-Za-z ]+$", last_name):
            return Response({"error": "Last name should contain only letters and spaces"}, status=status.HTTP_400_BAD_REQUEST)
        
        if not dob:
            return Response({"error": "Date of birth is required"}, status=status.HTTP_400_BAD_REQUEST)

        if not location:
            return Response({"error": "Location is required"}, status=status.HTTP_400_BAD_REQUEST)

        if not contact_number:
            return Response({"error": "Contact number is required"}, status=status.HTTP_400_BAD_REQUEST)

        contact_number = contact_number.replace(" ", "")  # remove any spaces
        # ✅ Normalize phone number (remove +91 or leading 0)
        if contact_number.startswith("+91"):
            contact_number = contact_number[3:]
        elif contact_number.startswith("0"):
            contact_number = contact_number[1:]

        if not contact_number.isdigit() or len(contact_number) != 10:
            return Response({"error": "Contact number must be exactly 10 digits"}, status=status.HTTP_400_BAD_REQUEST)

        if not email:
            return Response({"error": "Email is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            validate_email(email)  # ✅ Django email validator
        except ValidationError:
            return Response({"error": "Invalid email format"}, status=status.HTTP_400_BAD_REQUEST)

        if not password:
            return Response({"error": "Password is required"}, status=status.HTTP_400_BAD_REQUEST)

        # ✅ Password complexity
        if len(password) < 8:
            return Response({"error": "Password must be at least 8 characters long"}, status=status.HTTP_400_BAD_REQUEST)
        if not re.search(r"[A-Za-z]", password):
            return Response({"error": "Password must contain at least one letter"}, status=status.HTTP_400_BAD_REQUEST)
        if not re.search(r"\d", password):
            return Response({"error": "Password must contain at least one digit"}, status=status.HTTP_400_BAD_REQUEST)
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
            return Response({"error": "Password must contain at least one special character"}, status=status.HTTP_400_BAD_REQUEST)

        # ✅ Prevent duplicate email
        if User.objects.filter(username=email).exists():
            return Response({"error": "Email already registered"}, status=status.HTTP_400_BAD_REQUEST)

        # --- Create User & Profile (atomic transaction) ---
        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    username=email,
                    email=email,
                    password=password,
                    first_name=first_name,
                    last_name=last_name
                )

                profile = UserProfile(
                    user_id=str(user.id),
                    email=email,
                    first_name=first_name,
                    last_name=last_name,
                    dob=dob,
                    location=location,
                    contact_number=contact_number,  # ✅ normalized number only
                    is_approved=False
                )
                profile.save()

        except Exception as e:
            # Rollback Django user if Mongo fails
            if User.objects.filter(username=email).exists():
                User.objects.filter(username=email).delete()
            return Response({"error": f"Registration failed: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"message": "User registered, pending approval"}, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    def post(self, request):
        username = request.data.get("username")
        password = request.data.get("password")

        if not username or not password:
            return Response({"error": "Username and password are required"}, status=400)

        # ✅ Admin login check
        if username == settings.ADMIN_USERNAME and password == settings.ADMIN_PASSWORD:
            return Response({
                "message": "Admin login successful",
                "role": "admin",
                "admin": username
            })

        # ✅ Normal user login check
        user = authenticate(username=username, password=password)
        if user:
            profile = UserProfile.objects(user_id=str(user.id)).first()
            if profile and profile.is_approved:
                return Response({
                    "message": "Login successful",
                    "role": "user",
                    "user_id": str(user.id)
                })
            return Response({"error": "Account not approved yet"}, status=403)

        return Response({"error": "Invalid credentials"}, status=401)


class PlanTrip(APIView):
    def post(self, request):
        data = request.data
        try:
            trip = TripLog(
                user_id=data["user_id"],
                destination=data["destination"],
                budget=float(data["budget"]),
                date=datetime.strptime(data["date"], "%Y-%m-%d")
            )
            trip.save()
            return Response({"message": "Trip saved"}, status=201)
        except Exception as e:
            return Response({"error": str(e)}, status=400)


class PastTrips(APIView):
    def get(self, request):
        user_id = request.query_params.get("user_id")
        trips = TripLog.objects(user_id=user_id)
        data = [{
            "destination": t.destination,
            "budget": t.budget,
            "date": t.date.strftime("%Y-%m-%d")
        } for t in trips]
        return Response(data)


class SuggestDestination(APIView):
    def post(self, request):
        data = request.data
        suggestion = DestinationSuggestion(
            user_id=data["user_id"],
            name=data["name"],
            description=data.get("description", ""),
            coordinates=data.get("coordinates", "")
        )
        suggestion.save()
        return Response({"message": "Destination suggestion submitted"}, status=201)


class SubmitComplaint(APIView):
    def post(self, request):
        data = request.data
        complaint = Complaint(
            user_id=data["user_id"],
            subject=data["subject"],
            message=data["message"]
        )
        complaint.save()
        return Response({"message": "Complaint submitted"}, status=201)


class ReviewTrip(APIView):
    def post(self, request):
        data = request.data
        review = TripReview(
            user_id=data["user_id"],
            trip_id=data["trip_id"],
            rating=float(data["rating"]),
            review=data["review"]
        )
        review.save()
        return Response({"message": "Review submitted"}, status=201)


class DashboardStats(APIView):
    def get(self, request):
        user_id = request.query_params.get("user_id")
        total_trips = TripLog.objects(user_id=user_id).count()
        avg_budget = TripLog.objects(user_id=user_id).average("budget") or 0
        complaints = Complaint.objects(user_id=user_id).count()
        return Response({
            "total_trips": total_trips,
            "average_budget": avg_budget,
            "complaints_filed": complaints
        })
