import chromadb
from sentence_transformers import SentenceTransformer

client = chromadb.PersistentClient(path='evaluation/index/l9')
collection = client.get_collection('schema_index')

model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
query_emb = model.encode(['how many rooms are there'])[0]
results = collection.query(query_embeddings=[query_emb.tolist()], n_results=5)

print(f'Results: {len(results["ids"][0])}')
for i, (doc_id, dist) in enumerate(zip(results['ids'][0], results['distances'][0])):
    print(f'  {doc_id}: distance={dist:.4f}')

# Also check what documents exist
print("\nSample documents:")
results = collection.get(limit=10)
for i, (doc_id, meta) in enumerate(zip(results['ids'][:10], results['metadatas'][:10])):
    print(f'  {doc_id}: {meta}')