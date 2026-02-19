# query_service.py

import pickle
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer
from normalizer import normalize_question

# Load SQL mapping
with open("data.pkl", "rb") as f:
    sql_queries = pickle.load(f)

# Load embeddings
embeddings = np.load("embeddings.npy")

# Load FAISS index
index = faiss.read_index("index.faiss")

# Load model
model = SentenceTransformer('all-MiniLM-L6-v2')


def get_sql(user_question):
    normalized_input = normalize_question(user_question)

    query_embedding = model.encode([normalized_input], convert_to_numpy=True)

    distances, indices = index.search(query_embedding, k=1)

    best_match_idx = indices[0][0]

    return sql_queries[best_match_idx]


# Example test
if __name__ == "__main__":
    print(get_sql("Give me information of pqrs"))
