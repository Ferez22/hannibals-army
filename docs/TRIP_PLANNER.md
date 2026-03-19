# Getting Started

## General Information

This project is a trip planner that uses a dataset of -among others- tourist destinations to generate personalized trip recommendations based on one's preferences.

The tool includes a chatbot that gathers infos about your trip idea by first asking you if you want a general trip suggestion or if you want to plan a specific type of trip. It then goes on asking you specific questions like destination wish, budget, travel style, season, etc. At the end, it generates a personalized trip based on your preferences and asks you if you want to download it as a PDF file or save it directly to your obsidian. If it is the first time you use obsidian, it helps you setup the tool and connect to your vault.

## Data

The dataset is load directly from kaggle using the script in `db/load_destinations.py`.
Alternatively, you can find the CSV inside the `/data` folder.

The idea is to clean it up, sort it then add a description column that has to be populated with more infos and testimonies about the destination.

**Please read the README.md in the `/db` folder for more information about the dataset!!**

### Save trip data

#### Obsidian

[ ] install obsidian and activate CLI
[ ] agent should be able to write to obsidian
[ ] user can plan a trip with the chatbot then export it to obsidian

## Future Work

In the future, the idea is to have clean data including not only tourist destinations and general locations but also flights, hotels, and other travel-related information.

Another great thing to add would be good descriptions (preferable testimonies) of people who have visited these places.
