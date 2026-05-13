import os
import sys
import json
import duckdb
from pprint import pprint

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)

print("\n" + "="*60)
print(" 1. RELATIONAL METADATA (DUCKDB)")
print("="*60)
db_path = os.path.join(project_root, "data/duckdb/metadata.duckdb")
if os.path.exists(db_path):
    con = duckdb.connect(db_path, read_only=True)
    try:
        data = con.execute("SELECT * FROM chunks LIMIT 5").df()
        print(data.to_string())
    except Exception as e:
        print("Table chunks might not exist yet:", e)
    con.close()
else:
    print("DuckDB database not found.")

print("\n" + "="*60)
print(" 2. SEMANTIC METADATA (QDRANT VECTOR DB)")
print("="*60)
try:
    from src.vectordb.qdrant_client import _get_client, COLLECTION_NAME
    client = _get_client()
    # Scroll to get the first 5 points with their payload
    response, _ = client.scroll(
        collection_name=COLLECTION_NAME,
        limit=5,
        with_payload=True,
        with_vectors=False
    )
    for i, point in enumerate(response, 1):
        print(f"\n--- Qdrant Point {i} ---")
        payload = point.payload
        print(f"ID: {point.id}")
        print(f"Platform: {payload.get('platform')}")
        print(f"Category: {payload.get('category')}")
        print(f"ORA Code: {payload.get('ora_code')}")
        print(f"Severity: {payload.get('severity')}")
        print(f"Log Snippet: {str(payload.get('raw_text', ''))[:80]}...")
except Exception as e:
    print("Could not query Qdrant:", e)

print("\n" + "="*60)
print(" 3. KNOWLEDGE & RUNBOOK METADATA (GRAPH.JSON)")
print("="*60)
graph_path = os.path.join(project_root, "src/knowledge_graph/data/graph.json")
if os.path.exists(graph_path):
    with open(graph_path, 'r') as f:
        graph_data = json.load(f)
    print(f"Total Nodes in Graph: {len(graph_data.get('nodes', []))}\n")
    print("Showing first 5 nodes:")
    for node in graph_data.get('nodes', [])[:5]:
        print("-" * 40)
        pprint(node)
else:
    print("graph.json not found.")
print("\n" + "="*60)
