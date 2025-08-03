# api/models.py

from mongoengine import Document, StringField, BooleanField, DateField, FloatField, ListField

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
    user_id = StringField(required=True)
    dob = DateField()
    location = StringField()
    is_approved = BooleanField(default=False)
    meta = {'collection': 'user_profile'}

class TripLog(Document):
    user_id = StringField(required=True)
    destination = StringField()
    budget = FloatField()
    date = DateField(default=None)
    meta = {'collection': 'trip_log'}

class DestinationSuggestion(Document):
    user_id = StringField()
    name = StringField()
    description = StringField()
    coordinates = StringField()
    meta = {'collection': 'destination_suggestion'}

class Complaint(Document):
    user_id = StringField()
    subject = StringField()
    message = StringField()
    reply = StringField(default="")
    meta = {'collection': 'complaint'}

class TripReview(Document):
    user_id = StringField()
    trip_id = StringField()
    rating = FloatField()
    review = StringField()
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
