from dotenv import load_dotenv
from typing import Annotated
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict
from langchain_ollama.llms import OllamaLLM
from config import MASTER_MODEL
from mcp.client.stdio import stdio_client
from mcp import ClientSession, StdioServerParameters
from langchain_tavily import TavilySearch
import os
import getpass
import json
import logging
import asyncio


load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

if not os.environ.get("TAVILY_API_KEY"):
    os.environ["TAVILY_API_KEY"] = getpass.getpass("Tavily API key:\n")


# 1. Select Chat Model: llm = init_chat_model("anthropic:claude-4-5-sonnet-latest")
llm = OllamaLLM(model=MASTER_MODEL)


# 2. Define State of Graph
class State(TypedDict):
    # Messages is of typed list and when we want to change messages we use the function add_messages
    messages: Annotated[list, add_messages] # first type then how we want to modify our type
    trip_requirements: dict
    search_results: dict
    destination_suggestions: list

workflow = StateGraph(State)

 
# 3. Initialize MCP client


# 4. Create a node = create a function
def chatbot(state: State):
    """Chatbot node that processes user input and retrieved data"""
    try:
        logger.info("🤖 Chatbot processing response...")
        
        # Get destination suggestions
        suggestions = state.get("destination_suggestions", [])
        
        # Display retrieved destinations
        if suggestions:
            print("\n🌍 **Retrieved Destinations:**")
            for i, dest in enumerate(suggestions[:5], 1):  # Show top 5
                print(f"{i}. {dest.get('Destination Name', 'Unknown')} - {dest.get('Country', 'Unknown')}")
                print(f"   Type: {dest.get('Type', 'N/A')} | Rating: {dest.get('Avg Rating', 'N/A')} | Cost: ${dest.get('Avg Cost (USD/day)', 'N/A')}/day")
                print()
        else:
            print("\n❌ No destinations found. Please try a different search.")
        
        # Generate chatbot response
        messages = state["messages"]
        response = llm.invoke(messages)
        
        logger.info("✅ Chatbot response generated successfully")
        return {"messages": [response]}
        
    except Exception as e:
        logger.error(f"Error in chatbot: {str(e)}")
        error_message = "I apologize, but I encountered an error processing your request. Please try again."
        return {"messages": [llm.invoke(error_message)]}

def trip_analyzer(state: State) -> State:
    """Extracts trip requirements from user query"""
    
    # Get the latest user message
    user_message = state["messages"][-1].content
    
    # Extract structured info using LLM
    extracted_info = extract_trip_info(user_message)

    print("\n\n--------------------------------\n")
    print(f"🔍 Trip Analyzer extracted: {extracted_info}")  # Debug print
    print("\n\n")

    
    return {
        **state,
        "trip_requirements": {
            "destination": extracted_info.get("destination"),
            "budget": extracted_info.get("budget"),
            "dates": extracted_info.get("dates"),
            "preferences": extracted_info.get("preferences")
        }
    }

def extract_trip_info(user_message: str) -> dict:
    prompt = f"""Extract from this query: {user_message}
 
    Return ONLY a JSON object with these fields:
    - destination: The actual place name (country/city), NOT the full query
    - budget: (optional)
    - dates: (optional) 
    - travel_style: (optional)
    - activities: (optional)
    
    Examples:
    Input: "trip ideas about mexico" → {{"destination": "mexico"}}
    Input: "visit paris for $2000" → {{"destination": "paris", "budget": "$2000"}}
    
    Only return the JSON, nothing else."""


    response = llm.invoke(prompt)

    # Parse response to extract JSON
    try:
        # Parse the LLM response as JSON
        parsed = json.loads(response)
        return {
            "destination": parsed.get("destination", ""),
            "budget": parsed.get("budget", ""),
            "dates": parsed.get("dates", ""),
            "preferences": parsed.get("travel_style", "")  # Note: travel_style not preferences
        }
    except json.JSONDecodeError:
        # Fallback if LLM doesn't return valid JSON
        return {"destination": user_message, "budget": "", "dates": "", "preferences": ""}


def destination_retriever(state: State) -> State:
    """Retrieves destination information using MCP"""
    try:
        logger.info("🔍 Starting destination retrieval...")
        requirements = state["trip_requirements"]
        destination = requirements.get("destination", "")
        
        if not destination:
            logger.warning("No destination provided in trip requirements")
            return {
                **state,
                "destination_suggestions": []
            }
        
        logger.info(f"🔍 Searching for destinations: {destination}")
        
        # Determine search type and prepare arguments
        destination_lower = destination.lower()
        search_args = {}
        
        # Common countries list for quick detection
        common_countries = [
            'usa', 'united states', 'canada', 'mexico', 'brazil', 'argentina', 'chile', 'peru',
            'uk', 'united kingdom', 'france', 'germany', 'italy', 'spain', 'greece', 'netherlands',
            'japan', 'china', 'thailand', 'vietnam', 'india', 'south korea',
            'australia', 'new zealand',
            'egypt', 'south africa', 'kenya', 'morocco', 'tanzania',
            'russia', 'turkey', 'uae', 'israel'
        ]
        
        # Common continents list
        common_continents = [
            'europe', 'asia', 'north america', 'south america', 'africa', 'oceania', 'antarctica'
        ]
        
        # Common seasons list
        common_seasons = [
            'spring', 'summer', 'autumn', 'fall', 'winter'
        ]
        
        # Check if it's a country
        if any(country in destination_lower for country in common_countries):
            search_args["country"] = destination
            logger.info(f"🔍 Detected country search: {destination}")
        
        # Check if it's a continent
        elif any(continent in destination_lower for continent in common_continents):
            search_args["continent"] = destination
            logger.info(f"🔍 Detected continent search: {destination}")
        
        # Check if it's a season
        elif any(season in destination_lower for season in common_seasons):
            search_args["best_season"] = destination
            logger.info(f"🔍 Detected season search: {destination}")
        
        # Check for combined queries (e.g., "beach destinations in europe during summer")
        else:
            # Extract country, continent, or season from the query
            for continent in common_continents:
                if continent in destination_lower:
                    search_args["continent"] = continent
                    break
            
            for country in common_countries:
                if country in destination_lower:
                    search_args["country"] = country
                    break
            
            for season in common_seasons:
                if season in destination_lower:
                    search_args["best_season"] = season
                    break
            
            # If no specific criteria found, search by destination name
            if not search_args:
                search_args["query"] = destination
                logger.info(f"🔍 Detected destination name search: {destination}")
            else:
                search_args["query"] = destination
                logger.info(f"🔍 Detected combined search: {search_args}")
        
        # Run async MCP connection in sync context
        suggestions = asyncio.run(_get_mcp_suggestions(search_args))
        
        logger.info(f"📍 MCP Destination Retriever found: {len(suggestions)} suggestions")
        
        return {
            **state,
            "destination_suggestions": suggestions
        }
    except Exception as e:
        logger.error(f"Error in destination_retriever: {str(e)}")
        return {
            **state,
            "destination_suggestions": []
        }

async def _get_mcp_suggestions(search_args: dict) -> list:
    """Async function to get suggestions from MCP server"""
    try:
        server_params = StdioServerParameters(
            command="python",
            args=["mcp/destination_server.py"]
        )
        
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                
                result = await session.call_tool(
                    "search_destinations",
                    search_args
                )
                
                if result.content and len(result.content) > 0:
                    return json.loads(result.content[0].text)
                return []
    except Exception as e:
        logger.error(f"Error connecting to MCP server: {str(e)}")
        return []

# Instantiate tavily search tool
tool = TavilySearch(
    max_results=5,
    topic="general",
    # include_answer=False,
    # include_raw_content=False,
    # include_images=False,
    # include_image_descriptions=False,
    # search_depth="basic",
    # time_range="day",
    # include_domains=None,
    # exclude_domains=None
)


# here we create a graph
workflow.add_node("trip_analyzer", trip_analyzer)
workflow.add_node("chatbot", chatbot)
workflow.add_edge(START, "trip_analyzer") # We go from S^TART to chatbot
workflow.add_node("destination_retriever", destination_retriever)
workflow.add_edge("trip_analyzer", "destination_retriever")
workflow.add_edge("destination_retriever", "chatbot")
workflow.add_edge("chatbot", END) # We go from chatbot to END 


graph = workflow.compile()


while True:
    try:
        print("\n" + "="*50)
        question = input("Ask your question about travel destinations: ")
        print("\n")
        
        if question.lower() in ["q", "quit", "exit"]:
            logger.info("User requested to exit")
            print("👋 Goodbye!")
            break
            
        if not question.strip():
            print("❌ Please enter a valid question.")
            continue
            
        logger.info(f"User question: {question}")
        
        # Process through the graph
        state = graph.invoke({"messages": [{"role": "user", "content": question}]})
        
        # Display final response
        if state.get("messages"):
            final_response = state["messages"][-1]
            print(f"\n🤖 **Assistant:** {final_response.content}")
        
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
        break
    except Exception as e:
        logger.error(f"Error in main loop: {str(e)}")
        print(f"❌ An error occurred: {str(e)}")
        print("Please try again or type 'q' to quit.")
        break


