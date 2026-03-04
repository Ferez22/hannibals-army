
from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma
from langchain_core.documents import Document
import os
import pandas as pd

df = pd.read_csv("./data/tourist_destinations.csv")  # Path from project root
embeddings = OllamaEmbeddings(model="mxbai-embed-large")

db_location = "./data/chroma_tourist_destinations"
add_documents = not os.path.exists(db_location)

if add_documents:
    documents = []
    ids = []

    for i, row in df.iterrows():
        document = Document(
            page_content=f'{row["Destination Name"]} {row["Country"]} {row["Continent"]}  {row["Best Season"]}',
            metadata={"Type": row["Type"], "Avg Cost (USD/day)": row["Avg Cost (USD/day)"], "Avg Rating": row["Avg Rating"], "Annual Visitors (M)": row["Annual Visitors (M)"], "UNESCO Site": row["UNESCO Site"]},
            id=str(i)
        )
        ids.append(str(i))
        documents.append(document)


vector_store = Chroma(
    collection_name="feedbacks",
    persist_directory=db_location,
    embedding_function=embeddings
)

if add_documents:
    vector_store.add_documents(documents=documents, ids=ids)

# In your vector.py, modify the retriever:
retriever = vector_store.as_retriever(
    search_type="similarity_score_threshold",
    search_kwargs={"k": 5, "score_threshold": 0.5}
)