from backend.retrieval.schema_retriever import SchemaRetriever

retriever = SchemaRetriever(
    db_path='backend/data/enterprise.db',
    persist_dir='evaluation/index/l9'
)

# Debug the full retrieve method step by step
embedding = retriever._embedder.encode(['how many rooms are there'])[0]
hits = retriever.index.query(list(embedding), top_k=5)
print(f'Hits: {len(hits)}')
for hit in hits:
    print(f'  {hit["doc_id"]}: distance={hit["distance"]:.4f}')

# Check documents
doc = retriever._document_by_id.get(hits[0]["doc_id"])
print(f'First hit doc: {doc}')
print(f'Doc type: {doc.doc_type}')

# Check relationship matching
related = retriever._match_relationships(doc)
print(f'Related: {len(related)}')
for r in related:
    print(f'  {r.doc_id}')

# Now check what happens in full retrieve
# The issue might be the deduping - if related items have same doc_id as hits
print("\n--- Full retrieve debug ---")
result = retriever.retrieve('how many rooms are there', top_k=5)
print(f'Final items: {len(result.items)}')
print(f'Schema context length: {len(result.schema_context_text)}')