from dotenv import load_dotenv
from typing import Annotated
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict
from langchain_ollama.llms import OllamaLLM
from config import MASTER_MODEL
from src.vector import retriever
from langchain_tavily import TavilySearch
import os
import getpass

load_dotenv()

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

# create a node = create a function
def chatbot(state: State):
    return {"messages": [llm.invoke(state["messages"])]}

def trip_analyzer(state: State) -> State:
    """Extracts trip requirements from user query"""
    
    # Get the latest user message
    user_message = state["messages"][-1].content
    
    # Extract structured info using LLM
    extracted_info = extract_trip_info(user_message)

    print(f"🔍 Trip Analyzer extracted: {extracted_info}")  # Debug print

    
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
    Return JSON with: destination, budget, dates, travel_style, activities"""
    
    response = llm.invoke(prompt)
    # Parse response to extract JSON
    return {"destination": "...", "budget": "...", "dates": "...", "preferences": "..."}

def destination_retriever(state: State) -> State:
    """Retrieves destination information based on trip requirements"""
    requirements = state["trip_requirements"]
    suggestions = retriever.invoke(requirements.get("destination", ""))
    
    print(f"📍 Destination Retriever found: {len(suggestions)} suggestions")  # Debug print
    print(f"📍 Suggestion: {suggestions if suggestions else 'None'}")  # Debug print

    return {
        **state,
        "destination_suggestions": suggestions
    }

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

# PROBLEM: retrieve data is not working well. extraacts all the time same thing. cache?

while True:
    print("\n\n--------------------------------\n")
    question = input("Ask your question: ")
    print("\n\n")
    if question == "q":
        break
    
    # Use tavily search tool
    search_results = tool.invoke(question)

    feedbacks = retriever.invoke(question)

    state = graph.invoke({"messages": [{"role": "user", "content": question}]})

    print(state["messages"][-1].content)







