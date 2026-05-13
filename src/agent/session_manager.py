import sqlite3
import uuid
import os

# Resolve DB path relative to this file's location — works from any CWD
_DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "tests", "vector_db", "session_memory.duckdb"
)

class IncidentSessionManager:
    def __init__(self, db_path=_DEFAULT_DB_PATH):
        """
        Initializes the DuckDB (mocked via SQLite) Session Memory.
        This bucket holds all logs uploaded by a user during a single chat session.
        """
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS session_chunks (
            session_id TEXT,
            chunk_id TEXT PRIMARY KEY,
            hostname TEXT,
            extracted_timestamp DATETIME,
            content TEXT,
            file_source TEXT
        )
        ''')
        conn.commit()
        conn.close()

    def create_new_session(self):
        """Generates a unique Incident ID when a user opens the chatbot."""
        session_id = f"INC-{uuid.uuid4().hex[:8].upper()}"
        return session_id

    def upload_log_to_session(self, session_id, log_chunks):
        """
        Takes raw parsed chunks from a log file and forcefully dumps them 
        into the Session Bucket, ignoring when they were uploaded.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        for chunk in log_chunks:
            chunk_id = f"CHK-{uuid.uuid4().hex[:6]}"
            cursor.execute('''
            INSERT INTO session_chunks (session_id, chunk_id, hostname, extracted_timestamp, content, file_source)
            VALUES (?, ?, ?, ?, ?, ?)
            ''', (session_id, chunk_id, chunk.get("hostname", "unknown"), 
                  chunk.get("timestamp"), chunk.get("content"), chunk.get("file_source")))
                  
        conn.commit()
        conn.close()
        print(f"  -> [SessionManager] Successfully attached {len(log_chunks)} chunks to {session_id}")

    def get_all_session_chunks(self, session_id):
        """Retrieves all chunks belonging to an incident."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM session_chunks WHERE session_id = ?", (session_id,))
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
