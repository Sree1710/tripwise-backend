# train_model.py

import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import OneHotEncoder
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
import joblib
import os

# Load data
df = pd.read_csv("train_data.csv")

X = df[["destination", "duration", "travel_type", "interest"]]
y = df["budget"]

# One-hot encode categorical columns
preprocessor = ColumnTransformer(transformers=[
    ('cat', OneHotEncoder(handle_unknown="ignore"), ["destination", "travel_type", "interest"])
], remainder='passthrough')

# Create pipeline
pipeline = Pipeline(steps=[
    ('preprocessor', preprocessor),
    ('regressor', LinearRegression())
])

# Train the model
pipeline.fit(X, y)

# Save the trained model
model_path = os.path.join(os.path.dirname(__file__), "tripwise_budget_model.pkl")
joblib.dump(pipeline, model_path)

print("✅ Model trained and saved as tripwise_budget_model.pkl")
