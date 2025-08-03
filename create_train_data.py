import pandas as pd

data = {
    "days": [2, 3, 4, 5, 7, 1, 6, 3, 4, 2, 5, 6, 7, 3, 4],
    "travelers": [1, 2, 2, 3, 4, 1, 2, 1, 3, 2, 4, 3, 5, 2, 1],
    "season": [0, 1, 1, 2, 2, 0, 2, 1, 2, 0, 2, 1, 2, 1, 0],
    "budget": [5000, 7000, 8500, 12000, 18000, 3000, 14000, 6000, 10000, 5500, 15000, 16000, 20000, 7500, 8000]
}

df = pd.DataFrame(data)
df.to_csv("train_data.csv", index=False)
print("train_data.csv created!")
