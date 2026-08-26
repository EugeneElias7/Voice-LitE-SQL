import chromadb
from backend.retrieval.embeddings import SentenceTransformerEmbedder

embedder = SentenceTransformerEmbedder()
client = chromadb.PersistentClient(path='evaluation/index/l9')
collection = client.get_collection('schema_index')

query_emb = embedder.encode(['how many rooms are there'])[0]
results = collection.query(query_embeddings=[query_emb.tolist()], n_results=5)

print(f'Results: {len(results["ids"][0])}')
for i, (doc_id, dist) in enumerate(zip(results['ids'][0], results['distances'][0])):
    print(f'  {doc_id}: distance={dist:.4f}')