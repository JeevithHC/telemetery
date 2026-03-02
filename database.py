from pymongo import MongoClient, ASCENDING, DESCENDING
from dotenv import load_dotenv
import os
import ssl

load_dotenv()

from urllib.parse import quote_plus
from dotenv import load_dotenv
import os

load_dotenv()


username = "telemetry_user"
password = quote_plus("Jjsvbba@2024")  

MONGO_URI = f"mongodb+srv://{username}:{password}@telemetry-cluster.bn75s43.mongodb.net/?appName=telemetry-cluster"
DB_NAME         = os.getenv("DB_NAME", "vehicle_telemetry")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "telemetry")

# Connect to MongoDB Atlas
client = MongoClient(
    MONGO_URI,
     tls=True,
    tlsAllowInvalidCertificates=True,
    serverSelectionTimeoutMS=20000
)
db         = client[DB_NAME]
collection = db[COLLECTION_NAME]

# Create indexes for fast querying on vehicle_id + timestamp
collection.create_index([("vehicle_id", ASCENDING), ("timestamp", DESCENDING)])
collection.create_index([("data_type", ASCENDING)])
collection.create_index([("timestamp", ASCENDING)])  # needed for downsampling queries

print("✅ Connected to MongoDB Atlas successfully!")
