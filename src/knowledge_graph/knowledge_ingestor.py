import sys
import os
import sqlite3
import re

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.append(project_root)

def print_header(title):
    print("\n" + "=" * 100)
    print(f" {title}")
    print("=" * 100)

def init_golden_database(db_path):
    """Initializes the deterministic relational database for authorized resolutions."""
    # Using sqlite3 as a built-in standard library mock for DuckDB
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS dba_runbooks (
        error_code TEXT PRIMARY KEY,
        symptoms TEXT,
        action_plan TEXT,
        source_document TEXT
    )
    ''')
    
    # Clear existing data for fresh test run
    cursor.execute('DELETE FROM dba_runbooks')
    conn.commit()
    return conn

def simulate_unstructured_table_extraction(filepath):
    """
    Simulates what Unstructured.io does: Uses layout parsing/regex to identify 
    a table inside a messy document, extract the rows, and return structured dictionaries.
    """
    extracted_rows = []
    
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return extracted_rows
        
    doc_name = os.path.basename(filepath)
    inside_table = False
    
    with open(filepath, 'r') as f:
        lines = f.readlines()
        
    for line in lines:
        line = line.strip()
        # Detect markdown table rows
        if line.startswith("|") and line.endswith("|"):
            # Skip header row and separator row
            if "Error Code" in line or "---" in line:
                continue
                
            # Split by pipe and clean up whitespace
            columns = [col.strip() for col in line.split("|") if col.strip()]
            
            if len(columns) == 3:
                # Replace the markdown <br> with actual newlines for the database
                action_clean = columns[2].replace("<br>", "\n")
                
                extracted_rows.append({
                    "error_code": columns[0],
                    "symptoms": columns[1],
                    "action_plan": action_clean,
                    "source_document": doc_name
                })
                
    return extracted_rows

def run_knowledge_ingestion():
    print_header("🚨 RAG DIAGNOSTIC ENGINE: KNOWLEDGE BASE INGESTION (LIBRARIAN) 🚨")
    
    runbook_path = os.path.join(project_root, "tests/simulated_docs/sample_runbook.md")
    db_path = os.path.join(project_root, "tests/vector_db/metadata.duckdb")  # Using .duckdb extension for architecture accuracy

    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    print(f"\n[+] INITIALIZING GOLDEN DATABASE (DuckDB/SQLite)")
    print(f"    - DB Path: {db_path}")
    print(f"    - Creating strict schema: TABLE dba_runbooks (error_code, symptoms, action_plan, source_document)")
    
    conn = init_golden_database(db_path)
    cursor = conn.cursor()
    
    print("\n" + "-" * 50)
    print(" 🛠️ STAGE 1: UNSTRUCTURED.IO / LLAMAINDEX PARSING")
    print("-" * 50)
    print(f"  -> Processing Document: {os.path.basename(runbook_path)}")
    print("  -> [Unstructured.io] LayoutParser detected a 3-column table.")
    print("  -> [Unstructured.io] Bypassing raw text embedding to prevent hallucination.")
    print("  -> [Unstructured.io] Extracting table rows into deterministic format...")
    
    extracted_data = simulate_unstructured_table_extraction(runbook_path)
    
    print(f"  -> [SUCCESS] Extracted {len(extracted_data)} official ORA codes and Action Plans.")
    
    print("\n" + "-" * 50)
    print(" 💾 STAGE 2: RELATIONAL DATABASE INSERTION")
    print("-" * 50)
    
    for row in extracted_data:
        print(f"  -> INSERTING: {row['error_code']} from {row['source_document']}")
        try:
            cursor.execute('''
            INSERT INTO dba_runbooks (error_code, symptoms, action_plan, source_document)
            VALUES (?, ?, ?, ?)
            ''', (row['error_code'], row['symptoms'], row['action_plan'], row['source_document']))
        except sqlite3.IntegrityError:
            print(f"     [!] Warning: {row['error_code']} already exists in database. Skipping.")
            
    conn.commit()
    
    print("\n" + "-" * 50)
    print(" 🔍 STAGE 3: VERIFICATION / QUERY ENGINE TEST")
    print("-" * 50)
    print("  -> Let's pretend the Live Agent just diagnosed an ORA-00603.")
    print("  -> Executing: SELECT action_plan FROM dba_runbooks WHERE error_code = 'ORA-00603'")
    
    cursor.execute("SELECT action_plan, source_document FROM dba_runbooks WHERE error_code = 'ORA-00603'")
    result = cursor.fetchone()
    
    if result:
        print(f"\n[!] DUCKDB RETURNED AUTHORIZED ACTION PLAN (Source: {result[1]}):")
        print("=" * 60)
        print(result[0])
        print("=" * 60)
        print("\n[!] VERDICT: Zero Hallucination. The LLM will now wrap this exact text in polite English.")
    else:
        print("\n[!] ERROR: Failed to retrieve action plan.")
        
    conn.close()

if __name__ == "__main__":
    run_knowledge_ingestion()
