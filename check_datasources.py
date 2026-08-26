import json
import urllib.request

# Check datasources
with urllib.request.urlopen('http://127.0.0.1:8000/api/datasources') as f:
    data = json.load(f)
    print(json.dumps(data, indent=2))