from mcp.server import Server
from mcp.types import Resource, Tool, TextContent
import pandas as pd
import json
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Server("destination-registry")

# Load destinations data
try:
    df = pd.read_csv("data/tourist_destinations_sorted.csv")
    logger.info(f"Loaded {len(df)} destinations")
except Exception as e:
    logger.error(f"Error loading destinations: {e}")
    df = pd.DataFrame()

@app.list_resources()
async def list_resources() -> list[Resource]:
    """List available destination resources"""
    return [
        Resource(
            uri="destinations://all",
            name="All Tourist Destinations",
            description="Complete dataset of tourist destinations",
            mimeType="application/json"
        )
    ]

@app.read_resource()
async def read_resource(uri: str) -> str:
    """Read destination data"""
    try:
        if uri == "destinations://all":
            return df.to_json(orient="records")
        raise ValueError(f"Unknown resource: {uri}")
    except Exception as e:
        logger.error(f"Error reading resource {uri}: {e}")
        return json.dumps([])

@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available destination tools"""
    return [
        Tool(
            name="search_destinations",
            description="Search destinations by country, name, continent, season, or criteria",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "country": {"type": "string"},
                    "continent": {"type": "string"},
                    "best_season": {"type": "string"},
                    "type": {"type": "string"}
                }
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Execute destination search"""
    try:
        logger.info(f"Calling tool: {name} with args: {arguments}")
        
        # Check if DataFrame is loaded
        if df.empty:
            logger.error("No destination data available")
            return [TextContent(type="text", text=json.dumps([]))]
        
        if name == "search_destinations":
            filtered_df = df.copy()
            
            if "country" in arguments and arguments["country"]:
                filtered_df = filtered_df[filtered_df["Country"].str.contains(arguments["country"], case=False, na=False)]
            
            if "continent" in arguments and arguments["continent"]:
                filtered_df = filtered_df[filtered_df["Continent"].str.contains(arguments["continent"], case=False, na=False)]
            
            if "best_season" in arguments and arguments["best_season"]:
                filtered_df = filtered_df[filtered_df["Best Season"].str.contains(arguments["best_season"], case=False, na=False)]
            
            if "query" in arguments and arguments["query"]:
                query = arguments["query"]
                # Search in destination name and description
                name_mask = filtered_df["Destination Name"].str.contains(query, case=False, na=False)
                desc_mask = filtered_df.get("Description", pd.Series([""] * len(filtered_df))).str.contains(query, case=False, na=False)
                filtered_df = filtered_df[name_mask | desc_mask]
            
            if "type" in arguments and arguments["type"]:
                filtered_df = filtered_df[filtered_df["Type"].str.contains(arguments["type"], case=False, na=False)]
            
            results = filtered_df.head(10).to_dict("records")
            logger.info(f"Found {len(results)} results")
            
            return [TextContent(type="text", text=json.dumps(results))]
        
        raise ValueError(f"Unknown tool: {name}")
        
    except Exception as e:
        logger.error(f"Error calling tool {name}: {e}")
        return [TextContent(type="text", text=json.dumps([]))]

# Run the server
if __name__ == "__main__":
    import asyncio
    from mcp.server.stdio import stdio_server
    
    async def main():
        async with stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())
    
    asyncio.run(main())