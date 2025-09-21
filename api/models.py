# api/models.py

from mongoengine import Document, StringField, BooleanField, DateField, FloatField, ListField, DictField, DateTimeField, EmbeddedDocument, EmbeddedDocumentField
from datetime import datetime, timezone

class Destination(Document):
    name = StringField(required=True, max_length=100)
    approved = BooleanField(default=False)
    description = StringField()
    coordinates = StringField()
    meta = {'collection': 'destination'}

class EmergencyInfo(Document):
    location = StringField(required=True)
    hospital = StringField()
    police = StringField()
    helpline = StringField()
    meta = {'collection': 'emergency_info'}

class MetadataTag(Document):
    poi_id = StringField(required=True)
    tag = StringField(required=True)
    meta = {'collection': 'metadata_tag'}

class UserProfile(Document):
    user_id = StringField(required=True)  # Django User.id or uuid
    first_name = StringField(max_length=150)
    last_name = StringField(max_length=150)
    email = StringField(required=True)  # keep unique if you want
    dob = DateField()
    location = StringField()
    contact_number = StringField()
    gender = StringField(required=True)
    profile_image_id = StringField()  
    is_approved = BooleanField(default=False)
    role = StringField(choices=["admin", "user"], default="user")  # optional
    meta = {
        'collection': 'user_profile',
        'indexes': ['email']  # faster lookup
    }


class TripLog(Document):
    user_id = StringField(required=True)
    destination = StringField()
    budget = FloatField()
    date = DateField(default=None)
    meta = {'collection': 'trip_log'}


class Location(EmbeddedDocument):
    lat = FloatField(required=True)
    lng = FloatField(required=True)

class DestinationSuggestion(Document):
    user_id = StringField()
    name = StringField()
    destination = StringField()
    avg_time = FloatField()
    estimated_cost = FloatField()
    tags = ListField(StringField())
    type = StringField()
    location = EmbeddedDocumentField(Location)   # instead of coordinates string

    meta = {'collection': 'destination_suggestion'}

class Complaint(Document):
    user_id = StringField()
    subject = StringField()
    message = StringField()
    reply = StringField(default="")
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)
    
    meta = {'collection': 'complaint'}
    
    def save(self, *args, **kwargs):
        if not self.created_at:
            self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
        return super(Complaint, self).save(*args, **kwargs)

class TripReview(Document):
    user_id = StringField()
    trip_id = StringField()
    rating = FloatField()
    review = StringField()
    origin = StringField()  # New field
    destination = StringField()  # New field
    start_date = DateTimeField()  # New field
    end_date = DateTimeField()  # New field
    created_at = DateTimeField(default=datetime.utcnow)
    meta = {'collection': 'trip_review'}


class PointOfInterest(Document):
    name = StringField(required=True)
    destination = StringField(required=True)
    type = StringField(default="sightseeing")  # general type
    location = StringField(default="10.2,77.0")  # dummy GPS
    avg_time = FloatField()
    estimated_cost = FloatField()
    hidden = BooleanField(default=False)
    tags = ListField(StringField())
    meta = {'collection': 'point_of_interest'}

class UserItinerary(Document):
    user_id = StringField(required=True)
    itinerary_data = DictField(required=True)  # stores the full response JSON
    created_at = DateTimeField(default=lambda: datetime.now(timezone.utc))

    meta = {"collection": "user_itineraries"}