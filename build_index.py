# build_index.py

import pickle
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer
from normalizer import normalize_question

# Your dataset
EXAMPLES = [
    "question: What is the name of employee TR12345?, query: sqlaaa",
    "question: What are the average working hours of ABCD department employees?, query: sqlbbb",
    "question: List 3 employees who recently got retired, query: sqlccc",
    "question: Give me info about pqrs, query: sqlddd",
    "question: Tell me info about Sarang Deshpande, query: sqlsss"
]

questions = []
sql_queries = []

for item in EXAMPLES:
    q_part, sql_part = item.split(", query:")
    question = q_part.replace("question:", "").strip()
    sql = sql_part.strip()

    questions.append(question)
    sql_queries.append(sql)

# Normalize
normalized_questions = [normalize_question(q) for q in questions]

# Save SQL mapping
with open("data.pkl", "wb") as f:
    pickle.dump(sql_queries, f)

# Build embeddings
model = SentenceTransformer('all-MiniLM-L6-v2')
embeddings = model.encode(normalized_questions, convert_to_numpy=True)

# Save embeddings
np.save("embeddings.npy", embeddings)

# Build FAISS index
dimension = embeddings.shape[1]
index = faiss.IndexFlatL2(dimension)
index.add(embeddings)

faiss.write_index(index, "index.faiss")

print("Index built and saved successfully.")
