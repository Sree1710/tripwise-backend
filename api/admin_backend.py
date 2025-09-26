from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.viewsets import ViewSet
from django.conf import settings
from django.contrib.auth.models import User
from api.models import (
    Destination, EmergencyInfo, MetadataTag,
    UserProfile, Complaint, UserItinerary, DestinationSuggestion, PointOfInterest
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
        destinations = DestinationSuggestion.objects.all()
        data = [
            {
                "id": str(dest.id),
                "user_id": dest.user_id,
                "name": dest.name,
                "destination": dest.destination,
                "avg_time": dest.avg_time,
                "estimated_cost": dest.estimated_cost,
                "tags": dest.tags,
                "type": dest.type,
                "location": dest.location.to_mongo() if dest.location else None,
                "approved": getattr(dest, "approved", False)
            }
            for dest in destinations
        ]
        return Response(data)

    def update(self, request, pk=None):
        try:
            destination = DestinationSuggestion.objects.get(id=pk)
            approved_status = request.data.get("approved")

            if approved_status is None:
                return Response({"error": "approved field is required"}, status=400)

            destination.approved = bool(approved_status)
            destination.save()

            # ✅ If approved, insert into PointOfInterest
            if destination.approved:
                poi = PointOfInterest(
                    name=destination.name,
                    destination=destination.destination,
                    type=destination.type or "sightseeing",
                    location=f"{destination.location.lat},{destination.location.lng}" if destination.location else "0.0,0.0",
                    avg_time=destination.avg_time,
                    estimated_cost=destination.estimated_cost,
                    tags=destination.tags,
                    hidden=False
                )
                poi.save()

            return Response({"message": "Destination status updated"})

        except DestinationSuggestion.DoesNotExist:
            return Response({"message": "Destination not found"}, status=status.HTTP_404_NOT_FOUND)

    def destroy(self, request, pk=None):
        try:
            destination = DestinationSuggestion.objects.get(id=pk)
            destination.delete()
            return Response({"message": "Destination deleted"})
        except DestinationSuggestion.DoesNotExist:
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



# Hidden/Unpopular Spots Management
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdmin])
class HiddenSpotsAdminView(ViewSet):

    def _is_hidden(self, spot):
        """Determine if a spot should be considered hidden."""
        return (
            "hidden" in (spot.tags or []) or
            "offbeat" in (spot.tags or []) or
            "secret" in (spot.name.lower() if spot.name else "")
        )

    def list(self, request):
        all_spots = PointOfInterest.objects.all()
        hidden_spots = [spot for spot in all_spots if self._is_hidden(spot)]

        data = [
            {
                "id": str(spot.id),
                "name": spot.name,
                "destination": spot.destination,
                "type": spot.type,
                "location": {
                    "lat": spot.location.get("lat", 0.0) if isinstance(spot.location, dict) else 0.0,
                    "lng": spot.location.get("lng", 0.0) if isinstance(spot.location, dict) else 0.0,
                },
                "avg_time": float(spot.avg_time) if spot.avg_time else 0.0,
                "estimated_cost": float(spot.estimated_cost) if spot.estimated_cost else 0.0,
                "tags": spot.tags or [],
                "hidden": True
            }
            for spot in hidden_spots
        ]
        return Response(data)

    def retrieve(self, request, pk=None):
        try:
            spot = PointOfInterest.objects.get(id=pk)
            if not self._is_hidden(spot):
                return Response({"message": "Hidden spot not found"}, status=status.HTTP_404_NOT_FOUND)

            data = {
                "id": str(spot.id),
                "name": spot.name,
                "destination": spot.destination,
                "type": spot.type,
                "location": {
                    "lat": spot.location.get("lat", 0.0) if isinstance(spot.location, dict) else 0.0,
                    "lng": spot.location.get("lng", 0.0) if isinstance(spot.location, dict) else 0.0,
                },
                "avg_time": float(spot.avg_time) if spot.avg_time else 0.0,
                "estimated_cost": float(spot.estimated_cost) if spot.estimated_cost else 0.0,
                "tags": spot.tags or [],
                "hidden": True
            }
            return Response(data)
        except PointOfInterest.DoesNotExist:
            return Response({"message": "Hidden spot not found"}, status=status.HTTP_404_NOT_FOUND)

    def update(self, request, pk=None):
        try:
            spot = PointOfInterest.objects.get(id=pk)
            data = request.data

            if "name" in data:
                spot.name = data["name"]
            if "destination" in data:
                spot.destination = data["destination"]
            if "type" in data:
                spot.type = data["type"]
            if "location" in data:
                # Expecting {"lat": 10.2, "lng": 77.0}
                loc = data["location"]
                if isinstance(loc, dict):
                    spot.location = {"lat": loc.get("lat", 0.0), "lng": loc.get("lng", 0.0)}
            if "avg_time" in data:
                spot.avg_time = data["avg_time"]
            if "estimated_cost" in data:
                spot.estimated_cost = data["estimated_cost"]
            if "tags" in data:
                spot.tags = data["tags"]

            spot.save()
            return Response({"message": "Hidden spot updated"})
        except PointOfInterest.DoesNotExist:
            return Response({"message": "Hidden spot not found"}, status=status.HTTP_404_NOT_FOUND)

    def destroy(self, request, pk=None):
        try:
            spot = PointOfInterest.objects.get(id=pk)
            if not self._is_hidden(spot):
                return Response({"message": "Hidden spot not found"}, status=status.HTTP_404_NOT_FOUND)

            spot.delete()
            return Response({"message": "Hidden spot deleted"})
        except PointOfInterest.DoesNotExist:
            return Response({"message": "Hidden spot not found"}, status=status.HTTP_404_NOT_FOUND)


