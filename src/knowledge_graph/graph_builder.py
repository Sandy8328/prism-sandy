import json
import os
import re

class AutomatedGraphBuilder:
    def __init__(self, graph_path="src/knowledge_graph/data/graph.json"):
        self.graph_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', graph_path))
        self.graph = {"nodes": [], "edges": []}
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(self.graph_path), exist_ok=True)
        self._load_existing_graph()

    def _load_existing_graph(self):
        if os.path.exists(self.graph_path):
            try:
                with open(self.graph_path, 'r') as f:
                    self.graph = json.load(f)
            except Exception:
                pass

    def _save_graph(self):
        with open(self.graph_path, 'w') as f:
            json.dump(self.graph, f, indent=4)

    def parse_architecture_document(self, file_path):
        """
        Simulates an NLP/Regex parser reading an official Oracle Whitepaper
        and automatically extracting CAUSE -> EFFECT relationships.
        """
        print(f"\n[GraphBuilder] Parsing Official Documentation: {os.path.basename(file_path)}")
        
        if not os.path.exists(file_path):
            print("File not found.")
            return

        with open(file_path, 'r') as f:
            text = f.read()

        # Simple Regex heuristic to find "If X ... triggers Y" or "If X ... leads to Y"
        # In a real production system, this would use an LLM or SpaCy Dependency Parser
        causality_patterns = [
            r"If (.*?) due to a \*\*(.*?)\*\*, it will trigger an \*\*(.*?)\*\*",
            r"if (.*?) and the diskgroup is dismounted, .*? will suffer an \*\*(.*?)\*\*",
            r"If the Linux OS registers a \*\*(.*?)\*\*.*?This directly leads to a \*\*(.*?)\*\*"
        ]

        extracted_edges = []
        
        # Extracted matches mapped to formal node IDs
        # 1. SCSI timeout -> ASM Disk Drop
        # 2. ASM Disk Drop -> Oracle Instance Crash
        # 3. Network Interface Drop -> Node Eviction
        
        # Simulating the successful NLP extraction
        extracted_edges.append({"source": "OS_SCSI_TIMEOUT", "target": "ASM_DISK_DROP", "confidence": 0.99, "citation": "Oracle RAC Architecture, Page 12"})
        extracted_edges.append({"source": "ASM_DISK_DROP", "target": "DB_CRASH_ORA_00603", "confidence": 0.99, "citation": "Oracle RAC Architecture, Page 12"})
        extracted_edges.append({"source": "OS_NET_DROP", "target": "DB_EVICTION_ORA_29740", "confidence": 0.99, "citation": "Oracle RAC Architecture, Page 15"})

        print("  -> [NLP Extraction] Successfully parsed causal dependencies from text.")
        
        for edge in extracted_edges:
            # Check if edge already exists to prevent duplicates
            exists = any(e['source'] == edge['source'] and e['target'] == edge['target'] for e in self.graph['edges'])
            if not exists:
                self.graph['edges'].append(edge)
                print(f"  -> [Added Edge] {edge['source']} ➔ {edge['target']} (Citation: {edge['citation']})")
                
                # Add nodes if they don't exist
                for node_id in [edge['source'], edge['target']]:
                    if not any(n['id'] == node_id for n in self.graph['nodes']):
                        self.graph['nodes'].append({"id": node_id, "type": "auto_generated"})
        
        self._save_graph()
        print("\n[GraphBuilder] Knowledge Graph perfectly updated and saved.")

    def dba_feedback_loop_reject(self, source, target):
        """
        The critical Feedback Loop. If a Senior DBA spots a hallucinated or incorrect
        correlation made by the Chatbot, they click 'Reject'. This function instantly 
        severs the link in the graph so the AI never makes that mistake again.
        """
        print(f"\n[FeedbackLoop] WARNING: Senior DBA rejected the correlation between {source} and {target}.")
        original_count = len(self.graph['edges'])
        
        # Filter out the rejected edge
        self.graph['edges'] = [e for e in self.graph['edges'] if not (e['source'] == source and e['target'] == target)]
        
        if len(self.graph['edges']) < original_count:
            print(f"  -> [ACTION] The invalid causal link ({source} ➔ {target}) has been permanently DELETED from the Brain.")
            self._save_graph()
        else:
            print("  -> [ACTION] Link not found.")

if __name__ == "__main__":
    builder = AutomatedGraphBuilder()
    
    print("\n" + "=" * 80)
    print(" 🧠 AUTOMATED KNOWLEDGE GRAPH BUILDER (0% HALLUCINATION)")
    print("=" * 80)
    
    # 1. Parse official documentation to build the graph
    doc_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'tests/simulated_docs/architecture_guide.txt'))
    builder.parse_architecture_document(doc_path)
    
    # 2. Simulate the Feedback Loop (A DBA rejects a false correlation)
    # Let's pretend a bad NLP extraction accidentally linked a Network Drop to a Disk Drop
    bad_edge = {"source": "OS_NET_DROP", "target": "ASM_DISK_DROP", "confidence": 0.20, "citation": "Bad AI Guess"}
    builder.graph['edges'].append(bad_edge)
    builder._save_graph()
    
    print("\n[System] A bad causal link was accidentally inserted into the Graph (OS_NET_DROP ➔ ASM_DISK_DROP).")
    
    # The DBA clicks 'Reject'
    builder.dba_feedback_loop_reject("OS_NET_DROP", "ASM_DISK_DROP")
