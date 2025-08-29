from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.viewsets import ViewSet
from django.conf import settings
from django.contrib.auth.models import User
from api.models import (
    Destination, EmergencyInfo, MetadataTag,
    UserProfile, Complaint, TripLog, DestinationSuggestion
)
from rest_framework.decorators import authentication_classes, permission_classes
from api.auth import JWTAuthentication
from api.permissions import IsAdmin, IsUser, IsAdminOrUser



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


# Approve users after registration
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdmin])
class AdminUserView(APIView):
    def get(self, request):
        users = UserProfile.objects.all()
        data = [{"id": str(u.id), "user_id": u.user_id, "location": u.location, "is_approved": u.is_approved} for u in users]
        return Response(data)

    def post(self, request):
        try:
            user = UserProfile.objects.get(id=request.data["user_id"])
            user.is_approved = True
            user.save()
            return Response({"message": "User approved"})
        except UserProfile.DoesNotExist:
            return Response({"message": "User not found"}, status=404)


# View/respond to user complaints
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdmin])
class AdminComplaintView(APIView):
    def get(self, request):
        complaints = Complaint.objects.all()
        data = [{"id": str(c.id), "user_id": c.user_id, "subject": c.subject, "message": c.message, "reply": c.reply} for c in complaints]
        return Response(data)

    def post(self, request):
        try:
            complaint = Complaint.objects.get(id=request.data["complaint_id"])
            complaint.reply = request.data["reply"]
            complaint.save()
            return Response({"message": "Reply sent to user"})
        except Complaint.DoesNotExist:
            return Response({"message": "Complaint not found"}, status=404)


# Admin dashboard with analytics
@authentication_classes([JWTAuthentication])
@permission_classes([IsAdmin])
class AdminAnalyticsView(APIView):
    def get(self, request):
        user_count = User.objects.count()
        trip_count = TripLog.objects.count()
        try:
            avg_budget = sum(t.budget for t in TripLog.objects if t.budget) / trip_count
        except ZeroDivisionError:
            avg_budget = 0
        return Response({
            "total_users": user_count,
            "total_trips": trip_count,
            "average_budget": avg_budget
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

