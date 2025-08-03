from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from api.models import (
    UserProfile, TripLog, DestinationSuggestion, Complaint, TripReview
)
from datetime import datetime


class RegisterUser(APIView):
    def post(self, request):
        data = request.data
        if User.objects.filter(username=data["username"]).exists():
            return Response({"error": "Username already exists"}, status=400)

        user = User.objects.create_user(
            username=data["username"],
            email=data.get("email", ""),
            password=data["password"]
        )
        profile = UserProfile(
            user_id=str(user.id),
            dob=data.get("dob"),
            location=data.get("location"),
            is_approved=False
        )
        profile.save()
        return Response({"message": "User registered, pending approval"}, status=201)


class LoginUser(APIView):
    def post(self, request):
        user = authenticate(username=request.data["username"], password=request.data["password"])
        if user:
            profile = UserProfile.objects(user_id=str(user.id)).first()
            if profile and profile.is_approved:
                return Response({"message": "Login successful", "user_id": str(user.id)})
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
