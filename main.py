from dotenv import load_dotenv
from typing import Annotated
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict
from langchain_ollama.llms import OllamaLLM
from config import MASTER_MODEL

load_dotenv()

# 1. Select Chat Model: llm = init_chat_model("anthropic:claude-4-5-sonnet-latest")
llm = OllamaLLM(model=MASTER_MODEL)


# 2. Define State of Graph
class State(TypedDict):
    # Messages is of typed list and when we want to change messages we use the function add_messages
    messages: Annotated[list, add_messages] # first type then how we want to modify our type


graph_builder = StateGraph(State)

# create a node = create a function
def chatbot(state: State):
    return {"messages": [llm.invoke(state["messages"])]}


# here we create a graph that only has a chat node
graph_builder.add_node("chatbot", chatbot) # Make the chatbot our starting node
graph_builder.add_edge(START, "chatbot") # We go from START to chatbot
graph_builder.add_edge("chatbot", END) # We go from chatbot to END 

graph = graph_builder.compile()

user_input = input("Enter a message: ")
state = graph.invoke({"messages": [{"role": "user", "content": user_input}]})

print(state["messages"][-1].content)


