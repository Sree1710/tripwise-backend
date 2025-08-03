# api/ml/predict.py
import joblib
import os
import pandas as pd

MODEL_PATH = os.path.join(os.path.dirname(__file__), "../../tripwise_budget_model.pkl")
model = joblib.load(MODEL_PATH)

def predict_budget(input_data):
    df = pd.DataFrame([input_data])
    return int(model.predict(df)[0])
