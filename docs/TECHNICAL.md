# Technical Documentation

## Agentic workflow

A graph is created.
nodes:

- chatbot: a node that uses the llm to generate a response
- The tool **DuckDuckGoSearchResults** is used to browser the web

### Diagramm Visualization

find the diagramm in the file `diagramm/trip_planner_diagramm.drawio`

┌─────────────────┐ ┌──────────────────┐ ┌─────────────────────┐
│ START │───▶│ Trip Analyzer │───▶│ Destination Retriever│
└─────────────────┘ └──────────────────┘ └─────────────────────┘
│
▼
┌─────────────────┐ ┌──────────────────┐ ┌─────────────────────┐
│ END │◀───│ Trip Planner │◀───│ Budget Checker │
└─────────────────┘ └──────────────────┘ └─────────────────────┘
▲ │
│ ▼
┌──────────────────┐ ┌─────────────────────┐
│ Response Builder │◀───│ Web Search Agent │
└──────────────────┘ └─────────────────────┘

### Node Functions

**1. Trip Analyzer**

- Extracts key information from user query
- Identifies destination preferences, budget constraints, timeframe, travel style
- Structures input for downstream processing

**2. Destination Retriever**

- Uses vector database to suggest matching destinations
- Provides seasonal recommendations and activity types
- Ranks destinations based on user preferences

**3. Web Search Agent**

- Performs real-time searches for flights, hotels, weather, events
- Uses DuckDuckGoSearchResults tool
- Gathers current pricing and availability data

**4. Budget Checker**

- Validates recommendations against digital twin constraints
- Checks flight duration vs. budget correlations
- Ensures accommodation preferences match budget

**5. Trip Planner**

- Synthesizes all gathered information
- Creates optimal routing and activity suggestions
- Generates personalized itinerary recommendations

**6. Response Builder**

- Formats final response with actionable recommendations
- Provides booking links and alternative options
- Presents information in user-friendly format

### Conditional Routing Logic

- **Budget exceeded**: Budget Checker → Trip Planner (adjust recommendations)
- **Insufficient destinations**: Web Search Agent → Destination Retriever (find more options)
- **Ready for final plan**: Response Builder → END (complete workflow)
