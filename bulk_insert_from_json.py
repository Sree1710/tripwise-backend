import os
import json
from pathlib import Path
from dotenv import load_dotenv
from mongoengine import connect, Document, StringField, FloatField, ListField, DictField

# --- Load environment variables ---
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env")

MONGODB_URI = os.getenv("MONGODB_URI")
if not MONGODB_URI:
    raise Exception("❌ MONGODB_URI not set in .env")

connect(host=MONGODB_URI)

# --- Define your model ---
class PointOfInterest(Document):
    name = StringField(required=True, unique=True)
    destination = StringField(required=True)
    avg_time = FloatField(required=True)
    estimated_cost = FloatField(required=True)
    tags = ListField(StringField())
    type = StringField(required=True)
    location = DictField()

    meta = {'collection': 'point_of_interest'}

# --- Load JSON Data ---
json_path = BASE_DIR / "api" / "utils" / "custom_data.json"

if not json_path.exists():
    raise Exception(f"❌ File not found: {json_path}")

with open(json_path, "r") as file:
    data = json.load(file)

# --- Insert into MongoDB ---
inserted = 0
skipped = 0
for poi_name, details in data.items():
    destination = details.get("destination")
    if not destination:
        print(f"⚠️ Skipping '{poi_name}' – missing destination.")
        skipped += 1
        continue

    # Remove existing POI with same name to avoid duplicates
    PointOfInterest.objects(name=poi_name).delete()

    poi = PointOfInterest(
        name=poi_name,
        destination=destination,
        avg_time=details["avg_time"],
        estimated_cost=details["cost"],
        tags=details.get("tags", []),
        type=details.get("type", "general"),
        location=details.get("location", {"lat": 0.0, "lng": 0.0})
    )
    poi.save()
    inserted += 1

print(f"✅ Inserted {inserted} POIs successfully.")
if skipped > 0:
    print(f"⚠️ Skipped {skipped} POIs due to missing destination.")
