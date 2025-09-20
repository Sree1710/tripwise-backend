from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.viewsets import ViewSet
from django.conf import settings
from django.contrib.auth.models import User
from api.models import (
    Destination, EmergencyInfo, MetadataTag,
    UserProfile, Complaint, UserItinerary, DestinationSuggestion
)
from rest_framework.decorators import authentication_classes, permission_classes
from api.auth import JWTAuthentication
from api.permissions import IsAdmin, IsUser, IsAdminOrUser
from collections import Counter
from datetime import datetime, timedelta



# Destination approval and deletion
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdmin])
class DestinationAdminView(ViewSet):
    def list(self, request):
        destinations = Destination.objects.all()
        data = [{"id": str(dest.id), "name": dest.name, "approved": dest.approved} for dest in destinations]
        return Response(data)

    def update(self, request, pk=None):
        try:
            destination = Destination.objects.get(id=pk)
            destination.approved = request.data.get("approved", destination.approved)
            destination.save()
            return Response({"message": "Destination status updated"})
        except Destination.DoesNotExist:
            return Response({"message": "Destination not found"}, status=status.HTTP_404_NOT_FOUND)

    def destroy(self, request, pk=None):
        try:
            destination = Destination.objects.get(id=pk)
            destination.delete()
            return Response({"message": "Destination deleted"})
        except Destination.DoesNotExist:
            return Response({"message": "Destination not found"}, status=status.HTTP_404_NOT_FOUND)



# Emergency info management
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdmin])
class EmergencyInfoView(ViewSet):
    def list(self, request):
        infos = EmergencyInfo.objects.all()
        data = [{"id": str(i.id), "location": i.location, "hospital": i.hospital, "police": i.police, "helpline": i.helpline} for i in infos]
        return Response(data)

    def create(self, request):
        info = EmergencyInfo(**request.data)
        info.save()
        return Response({"message": "Emergency info added"}, status=201)


# Metadata tags (cultural, accessibility)
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdmin])
class MetadataTagView(ViewSet):
    def list(self, request):
        tags = MetadataTag.objects.all()
        data = [{"id": str(t.id), "poi_id": t.poi_id, "tag": t.tag} for t in tags]
        return Response(data)

    def create(self, request):
        tag = MetadataTag(**request.data)
        tag.save()
        return Response({"message": "Metadata tag created"}, status=201)


# View all users (only for admin)
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdmin])
class AdminUserView(APIView):
    def get(self, request):
        users = UserProfile.objects.all()
        data = []

        for u in users:
            # Build image URL if available
            image_url = None
            if u.profile_image_id:
                image_url = request.build_absolute_uri(
                    f"/api/user/{u.id}/profile-picture/"
                )

            data.append({
                "id": str(u.id),
                "user_id": u.user_id,
                "first_name": u.first_name,
                "last_name": u.last_name,
                "dob": u.dob,
                "gender": u.gender,
                "contact_number": u.contact_number,
                "email": u.email,
                "location": u.location,
                "is_approved": u.is_approved,
                "profile_image": image_url,   # add image URL here
            })

        return Response(data)




# View/respond to user complaints
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdmin])
class AdminComplaintView(APIView):
    def get(self, request):
        complaints = Complaint.objects.all().order_by('-id')
        data = []
        for c in complaints:
            data.append({
                "id": str(c.id),
                "user_id": c.user_id,
                "subject": c.subject,
                "message": c.message,
                "reply": c.reply,
                "created_at": c.created_at.isoformat() if hasattr(c, 'created_at') and c.created_at else None,
                "has_reply": bool(c.reply)
            })
        return Response(data)

    def post(self, request):
        try:
            from bson import ObjectId
            complaint = Complaint.objects(id=ObjectId(request.data["complaint_id"])).first()
            if not complaint:
                return Response({"message": "Complaint not found"}, status=404)
                
            complaint.reply = request.data["reply"]
            complaint.save()  # This will update the updated_at field
            return Response({"message": "Reply sent to user"})
        except Exception as e:
            return Response({"message": "Invalid complaint ID or server error"}, status=400)


#Admin analytics
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdmin])
class AdminAnalyticsView(APIView):
    def get(self, request):
        # Total users
        user_count = User.objects.count()

        # Total trips
        trip_count = UserItinerary.objects.count()

        # Top destinations
        destinations = [
            t.itinerary_data.get("summary", {}).get("destination", "Unknown")
            for t in UserItinerary.objects
            if t.itinerary_data.get("summary", {}).get("destination", None)
        ]
        dest_counter = Counter(destinations)
        top_destinations = sorted(
            [{"destination": dest, "trips": count} for dest, count in dest_counter.items()],
            key=lambda x: x["trips"],
            reverse=True
        )[:5]

        # Trips in last 30 days
        one_month_ago = datetime.now().date() - timedelta(days=30)
        recent_trips = [
            t for t in UserItinerary.objects
            if datetime.strptime(t.itinerary_data.get("summary", {}).get("start_date", "1900-01-01"), "%Y-%m-%d").date() >= one_month_ago
        ]

        # Top users by number of trips
        user_trips_counter = Counter([t.user_id for t in UserItinerary.objects])
        top_users_by_trips = sorted(
            [{"user_id": uid, "no_of_trips": count} for uid, count in user_trips_counter.items()],
            key=lambda x: x["no_of_trips"],
            reverse=True
        )[:5]

        return Response({
            "total_users": user_count,
            "total_trips": trip_count,
            "top_destinations": top_destinations,
            "trips_last_30_days": len(recent_trips),
            "top_users_by_trips": top_users_by_trips
        })

# Approve or reject user-suggested destinations
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdmin])
class DestinationSuggestionAdminView(ViewSet):
    def list(self, request):
        suggestions = DestinationSuggestion.objects.all()
        data = [{"id": str(s.id), "name": s.name, "description": s.description, "coordinates": s.coordinates} for s in suggestions]
        return Response(data)

    def approve(self, request, pk=None):
        try:
            suggestion = DestinationSuggestion.objects.get(id=pk)
            # Create Destination
            dest = Destination(
                name=suggestion.name,
                description=suggestion.description,
                coordinates=suggestion.coordinates,
                approved=True
            )
            dest.save()
            suggestion.delete()
            return Response({"message": "Destination approved and added to main list"})
        except DestinationSuggestion.DoesNotExist:
            return Response({"message": "Suggestion not found"}, status=404)

    def destroy(self, request, pk=None):
        try:
            suggestion = DestinationSuggestion.objects.get(id=pk)
            suggestion.delete()
            return Response({"message": "Suggestion deleted"})
        except DestinationSuggestion.DoesNotExist:
            return Response({"message": "Suggestion not found"}, status=404)

