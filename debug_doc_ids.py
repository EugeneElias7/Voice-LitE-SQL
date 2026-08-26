from backend.retrieval.schema_retriever import SchemaRetriever

retriever = SchemaRetriever(
    db_path='backend/data/enterprise.db',
    persist_dir='evaluation/index/l9'
)

# Check what IDs are in the document_by_id
print(f'Total documents: {len(retriever._documents)}')
print('Sample document IDs:')
for doc in retriever._documents[:10]:
    print(f'  {doc.doc_id}: {doc.doc_type}')

# Check the hit IDs vs document IDs
hit_ids = [
    'column:Room.RoomNumber',
    'column:Room.RoomType',
    'relationship:Stay.Room->Room.RoomNumber',
    'column:Room.Unavailable',
    'column:Stay.Room'
]
for hit_id in hit_ids:
    doc = retriever._document_by_id.get(hit_id)
    print(f'{hit_id}: {"FOUND" if doc else "NOT FOUND"}')