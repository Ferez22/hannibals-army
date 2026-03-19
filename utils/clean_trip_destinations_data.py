

import pandas as pd
import os
print("Current directory:", os.getcwd())
print("File exists:", os.path.exists("../data/tourist_destinations.csv"))

data_csv = pd.read_csv("../data/tourist_destinations.csv")
df = pd.DataFrame(data_csv)

df_sorted = df.sort_values(by=["Country", "Destination Name"])  # use your actual column names

# add a column named description that is empty
df_sorted["Description"] = ""

# save the sorted dataframe to a new csv file
df_sorted.to_csv("../data/tourist_destinations_sorted.csv", index=False)
print(df_sorted)