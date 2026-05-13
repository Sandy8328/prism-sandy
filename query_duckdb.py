import duckdb
import pandas as pd

# Connect to the DuckDB file
db_path = "data/duckdb/metadata.duckdb"
con = duckdb.connect(db_path)

# Show all tables
print("--- Tables in Database ---")
tables = con.execute("SHOW TABLES").fetchall()

for table in tables:
    table_name = table[0]
    print(f"\nTable: {table_name}")
    
    # Print schema
    schema = con.execute(f"PRAGMA table_info('{table_name}')").df()
    print("\nColumns:")
    print(schema[['name', 'type']])
    
    # Print top 3 rows
    print("\nSample Data:")
    data = con.execute(f"SELECT * FROM {table_name} LIMIT 10").df()
    print(data)

con.close()
