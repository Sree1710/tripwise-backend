import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import OneHotEncoder
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
import joblib

data = pd.DataFrame({
    'destination': ['Goa', 'Munnar', 'Delhi'],
    'duration': [4, 3, 5],
    'travel_type': ['friends', 'solo', 'family'],
    'interest': ['beach', 'nature', 'history'],
    'budget': [12000, 4000, 9000]
})

X = data.drop('budget', axis=1)
y = data['budget']

categorical = ['destination', 'travel_type', 'interest']
numerical = ['duration']

preprocessor = ColumnTransformer([
    ('cat', OneHotEncoder(), categorical),
    ('num', 'passthrough', numerical)
])

pipeline = Pipeline([
    ('preprocess', preprocessor),
    ('model', RandomForestRegressor())
])

pipeline.fit(X, y)
joblib.dump(pipeline, 'tripwise_budget_model.pkl')
print("✅ Model trained and saved to tripwise_budget_model.pkl")
