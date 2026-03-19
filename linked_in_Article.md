# LinkedIn Post

The value of learning by doing.

I’d heard of MCP (a way for AI to use your data and tools) and had a rough idea of what it was. But it only clicked when I had a real problem: a trip planner where the chatbot had to pull the right destinations from our database depending on what the user asked for: “fun trip in South America”, Visit castles in winter”, and so on.

First I tried the “find similar stuff” (RAG) approach: the AI would search our list of places by meaning and suggest whatever sounded closest to what the user said. We even have descriptions for each destination, so there was plenty to search. But that approach only cares about similarity, not logic. So it could suggest very absurd things like “Go to Whitehaven Beach (Australia), then grab a quick lunch Puebla (Mexico)” in the same trip recommendation. Nobody expects that from a travel planner. The data is organized: Destination, Country, continent, type of trip, season, price and description... I needed exact filters and coherent results, not “something that sounds similar”. The other option was to write custom code for every kind of question, but then every app or tool that wanted to use our data would need its own way to talk to it.

That’s when I remembered MCP. Instead of many workarounds, you set up one place that knows how to answer questions about your data. The AI says “here’s what the user wants” and gets back exactly the right destinations—no weird mixes, no rewriting code for each new question. One interface, any request.

Understanding MCP didn’t come from the docs alone. It came from trying other approaches, seeing why they didn’t fit, and realizing we needed one standard way for the AI to use our data. That’s what MCP gives you.

And for what’s next—adding flights, hotels, testimonials, or export to PDF—the same idea holds: we add new data and capabilities in one place. The way the AI talks to our system stays simple. If you’re building something where a chatbot or AI has to use your data in many different ways, MCP is worth a look. It might fit better than you expect.

#MCP #AI #BuildInPublic #TripPlanner
