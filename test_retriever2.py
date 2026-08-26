from backend.retrieval.schema_retriever import SchemaRetriever

retriever = SchemaRetriever(
    db_path='backend/data/enterprise.db',
    persist_dir='evaluation/index/l9'
)

# Test the internal query
embedding = retriever._embedder.encode(['how many rooms are there'])[0]
print(f"Embedding type: {type(embedding)}, shape: {embedding.shape}")

hits = retriever.index.query(list(embedding), top_k=5)
print(f"Hits: {len(hits)}")
for hit in hits:
    print(f"  {hit['doc_id']}: distance={hit['distance']:.4f}")

# Now test the full retrieve method
result = retriever.retrieve('how many rooms are there', top_k=5)
print(f"\nFull retrieve - Items: {len(result.items)}")
for item in result.items:
    print(f"  {item.doc_type}: {item.table}.{item.column} score={item.score:.4f}")