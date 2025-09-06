from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db import transaction
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
import re
import jwt
import os
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from api.models import (
    UserProfile, TripLog, DestinationSuggestion, Complaint, TripReview
)
from datetime import datetime, timedelta, timezone
from rest_framework.decorators import authentication_classes, permission_classes
from api.auth import JWTAuthentication
from api.permissions import IsAdmin, IsUser, IsAdminOrUser
import gridfs
from pymongo import MongoClient
from django.http import HttpResponse
from bson import ObjectId
import uuid

# Setup MongoDB connection for GridFS (profile pictures)
client = MongoClient(os.getenv("MONGODB_URI"))
db = client[settings.MONGO_DB_NAME]
fs = gridfs.GridFS(db)

# User Registration with validation
class RegisterUser(APIView):
    authentication_classes = []   # 🚫 No JWT required
    permission_classes = []

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
        gender = data.get("gender", "").strip()

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
        else:
            try:
                datetime.strptime(dob, "%Y-%m-%d")
            except ValueError:
                return Response({"error": "Date of birth must be in YYYY-MM-DD format"}, status=status.HTTP_400_BAD_REQUEST)

        if not location:
            return Response({"error": "Location is required"}, status=status.HTTP_400_BAD_REQUEST)

        if not contact_number:
            return Response({"error": "Contact number is required"}, status=status.HTTP_400_BAD_REQUEST)

        contact_number = contact_number.replace(" ", "")  # remove spaces
        if contact_number.startswith("+91"):
            contact_number = contact_number[3:]
        elif contact_number.startswith("0"):
            contact_number = contact_number[1:]

        if not contact_number.isdigit() or len(contact_number) != 10:
            return Response({"error": "Contact number must be exactly 10 digits"}, status=status.HTTP_400_BAD_REQUEST)

        if not email:
            return Response({"error": "Email is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            validate_email(email)
        except ValidationError:
            return Response({"error": "Invalid email format"}, status=status.HTTP_400_BAD_REQUEST)

        if not password:
            return Response({"error": "Password is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        if not gender:
            return Response({"error": "Gender is required"}, status=status.HTTP_400_BAD_REQUEST)

        if len(password) < 8:
            return Response({"error": "Password must be at least 8 characters long"}, status=status.HTTP_400_BAD_REQUEST)
        if not re.search(r"[A-Za-z]", password):
            return Response({"error": "Password must contain at least one letter"}, status=status.HTTP_400_BAD_REQUEST)
        if not re.search(r"\d", password):
            return Response({"error": "Password must contain at least one digit"}, status=status.HTTP_400_BAD_REQUEST)
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
            return Response({"error": "Password must contain at least one special character"}, status=status.HTTP_400_BAD_REQUEST)

        if User.objects.filter(username=email).exists():
            return Response({"error": "Email already registered"}, status=status.HTTP_400_BAD_REQUEST)

        # --- Handle Profile Image Upload ---
        MAX_IMAGE_SIZE_MB = 5  # Maximum allowed size in MB
        ALLOWED_IMAGE_TYPES = ["image/jpeg", "image/jpg", "image/png", "image/pjpeg", "image/x-png"]  # Allowed MIME types

        profile_image_id = None
        if "profile_image" in request.FILES:
            uploaded_file = request.FILES["profile_image"]
            
            # 1️⃣ Check file size
            if uploaded_file.size > MAX_IMAGE_SIZE_MB * 1024 * 1024:
                return Response({"error": f"Profile image size must not exceed {MAX_IMAGE_SIZE_MB} MB"},status=status.HTTP_400_BAD_REQUEST)

            # 2️⃣ Check file type
            content_type = getattr(uploaded_file, "content_type", "")
            if content_type.lower() not in ALLOWED_IMAGE_TYPES:
                return Response({"error": "Invalid file type. Only JPG, JPEG, and PNG are allowed."},status=status.HTTP_400_BAD_REQUEST)

            # 3️⃣ Read bytes and store in GridFS
            file_bytes = uploaded_file.read()
            safe_filename = f"{uuid.uuid4()}_{uploaded_file.name}"
            try:
                profile_image_id = fs.put(
                file_bytes,
                filename=safe_filename,
                content_type=content_type)
            except Exception as e:
                return Response({"error": f"Failed to store profile image: {str(e)}"},status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            return Response({"error": "Image is mandatory"}, status=status.HTTP_400_BAD_REQUEST)
            

        # --- End Profile Image Upload ---

        # --- Create User & Profile ---
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
                    contact_number=contact_number,
                    profile_image_id=str(profile_image_id) if profile_image_id else None,  # ✅ consistent field
                    gender=gender,
                    is_approved=False
                )
                profile.save()

        except Exception as e:
            User.objects.filter(username=email).delete()
            # delete GridFS file if uploaded (avoid orphans)
            try:
                if profile_image_id:
                    fs.delete(ObjectId(profile_image_id))
            except Exception:
                pass
            return Response({"error": f"Registration failed: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"message": "User registered, pending approval"}, status=status.HTTP_201_CREATED)



# User Login (admin and normal user)
class LoginView(APIView):
    authentication_classes = []   # 🚫 No JWT required
    permission_classes = []
    def post(self, request):
        username = request.data.get("username")
        password = request.data.get("password")

        if not username or not password:
            return Response({"error": "Username and password are required"}, status=400)

        # ✅ Admin login check
        if username == settings.ADMIN_USERNAME and password == settings.ADMIN_PASSWORD:
            payload = {
                "username": username,
                "role": "admin",
                "exp": datetime.now(timezone.utc) + timedelta(seconds=settings.JWT_EXP_DELTA)
            }
            token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

            return Response({
                "message": "Admin login successful",
                "role": "admin",
                "token": token
            })

        # ✅ Normal user login check
        user = authenticate(username=username, password=password)
        if user:
            profile = UserProfile.objects(user_id=str(user.id)).first()
            if profile and profile.is_approved:
                payload = {
                    "user_id": str(user.id),
                    "username": username,
                    "role": "user",
                    "exp": datetime.now(timezone.utc) + timedelta(seconds=settings.JWT_EXP_DELTA)
                }
                token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

                return Response({
                    "message": "Login successful",
                    "role": "user",
                    "token": token,
                    "user": {
                        "id": str(user.id),
                        "email": user.email,
                        "first_name": user.first_name,
                        "last_name": user.last_name,
                        "contact_number": profile.contact_number,
                        "gender": profile.gender,
                        "location": profile.location,
                        "dob": profile.dob,
                        "profile_image_id": profile.profile_image_id
                    }
                })
            return Response({"error": "Account Not Approved Yet. Kindly Contact Admin."}, status=403)

        return Response({"error": "Invalid Credentials."}, status=401)


#Past Trips
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdminOrUser])
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


#Suggest Destination
@authentication_classes([JWTAuthentication])
@permission_classes([IsUser])
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

#Submit Complaint
@authentication_classes([JWTAuthentication])
@permission_classes([IsUser])
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

#Review Trip
@authentication_classes([JWTAuthentication])
@permission_classes([IsUser])
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

#Dashboard Stats
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdminOrUser])
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

# Profile Picture Retrieval
@authentication_classes([JWTAuthentication])
@permission_classes([IsUser])
class ProfilePictureView(APIView):
    def get(self, request):
        # Fetch the profile for the logged-in user
        profile = UserProfile.objects(user_id=str(request.user.id)).first()
        
        # If no profile or no image
        if not profile or not profile.profile_image_id:
            return Response({"error": "No profile picture found"}, status=404)

        # Fetch image from GridFS
        try:
            grid_out = fs.get(ObjectId(profile.profile_image_id))
        except Exception:
            return Response({"error": "Failed to retrieve image"}, status=500)

        # Return the image as binary
        return HttpResponse(grid_out.read(), content_type="image/jpeg")

# View other user's profile picture (Admin only)
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdmin])
class UserProfilePictureView(APIView):
    def get(self, request, user_id):
        profile = UserProfile.objects(id=user_id).first()

        if not profile or not profile.profile_image_id:
            return Response({"error": "No profile picture found"}, status=404)

        try:
            grid_out = fs.get(ObjectId(profile.profile_image_id))
        except Exception:
            return Response({"error": "Failed to retrieve image"}, status=500)

        return HttpResponse(grid_out.read(), content_type="image/jpeg")
