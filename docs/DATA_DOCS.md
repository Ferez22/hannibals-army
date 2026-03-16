# Data Information

## Tourist Destinations

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

### Cleanup Data

working file: `utils/clean_trip_destination_data.py`
[ ] load data from `data/unchecked-destinations.csv`
[ ] convert into a pandas dataframe
[ ] load all countries of the world data to `data/all_countries`
[ ] filter by country
[ ] save the new file. but how to make it searchable quickly? index the db?
[ ] save missing countries in `data/missing-countries.csv`

### Add Missing destinations Data

[ ] load missing countries from `data/missing-countries.csv`
[ ] search for epic destinations for each missing country (tavily search? API? Manually?)
[ ] append to new file called: unchecked-new_destinations.csv
