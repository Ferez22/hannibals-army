# Getting Started

## General Information

This project is a trip planner that uses a dataset of -among others- tourist destinations to generate personalized trip recommendations based on one's preferences.

## Data

The dataset is load directly from kaggle using the script in `db/load_destinations.py`.
Alternatively, you can find the CSV inside the `/data` folder.

**Please read the README.md in the `/db` folder for more information about the dataset!!**

The dataset contains the following columns:

```csv
- Destination Name
- Country
- Continent
- Type
- Avg Cost (USD/day)
- Best Season
- Avg Rating
- Annual Visitors (M)
- UNESCO Site
```

## Future Work

In the future, the idea is to have clean data including not only tourist destinations and general locations but also flights, hotels, and other travel-related information.

Another great thing to add would be good descriptions (preferable testimonies) of people who have visited these places.
