

import pandas as pd
import os
print("Current directory:", os.getcwd())
print("File exists:", os.path.exists("../data/tourist_destinations.csv"))

data_csv = pd.read_csv("../data/tourist_destinations.csv")
df = pd.DataFrame(data_csv)

print(df)

