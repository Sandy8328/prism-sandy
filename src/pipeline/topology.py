import json
import os

class TopologyMap:
    def __init__(self, config_path=None):
        """
        Loads the Infrastructure Topology Map (CMDB).
        If no path is provided, it uses a default simulated enterprise layout.
        """
        self.config_path = config_path
        self.topology = {}
        
        if config_path and os.path.exists(config_path):
            self.load_from_file(config_path)
        else:
            self.load_default_topology()

    def load_from_file(self, path):
        try:
            with open(path, 'r') as f:
                self.topology = json.load(f)
        except Exception as e:
            print(f"Error loading topology from {path}: {e}")
            self.load_default_topology()

    def load_default_topology(self):
        """
        Simulates an enterprise CMDB linking RAC nodes and Exadata Cells.
        """
        self.topology = {
            "clusters": [
                {
                    "cluster_name": "PROD_EXADATA_RACK_01",
                    "compute_nodes": ["dbnode01", "dbnode02", "dbnode03", "dbnode04"],
                    "storage_cells": ["cell01", "cell02", "cell03", "cell04", "cell05", "cell06"]
                },
                {
                    "cluster_name": "STG_RAC_CLUSTER_02",
                    "compute_nodes": ["stg-db-01", "stg-db-02"],
                    "storage_cells": ["nas-storage-01"]
                }
            ]
        }

    def are_hosts_connected(self, host_a, host_b):
        """
        Determines if two hostnames are physically or logically connected 
        in the same Cluster/Rack. Solves the Victim vs Culprit edge case.
        """
        if host_a == host_b:
            return True
            
        host_a_lower = host_a.lower()
        host_b_lower = host_b.lower()

        for cluster in self.topology.get("clusters", []):
            all_cluster_nodes = cluster.get("compute_nodes", []) + cluster.get("storage_cells", [])
            all_cluster_nodes_lower = [n.lower() for n in all_cluster_nodes]
            
            # If BOTH hosts exist in the same cluster/rack, they are connected!
            if host_a_lower in all_cluster_nodes_lower and host_b_lower in all_cluster_nodes_lower:
                return True
                
        return False
        
    def get_cluster_name(self, hostname):
        """Returns the cluster name for a given host, or 'UNKNOWN'."""
        hostname_lower = hostname.lower()
        for cluster in self.topology.get("clusters", []):
            all_cluster_nodes = cluster.get("compute_nodes", []) + cluster.get("storage_cells", [])
            all_cluster_nodes_lower = [n.lower() for n in all_cluster_nodes]
            if hostname_lower in all_cluster_nodes_lower:
                return cluster.get("cluster_name")
        return "UNKNOWN"

    def get_all_connected_hosts(self, hostname):
        """Returns a list of all hostnames in the same cluster/rack, including itself."""
        hostname_lower = hostname.lower()
        for cluster in self.topology.get("clusters", []):
            all_cluster_nodes = cluster.get("compute_nodes", []) + cluster.get("storage_cells", [])
            all_cluster_nodes_lower = [n.lower() for n in all_cluster_nodes]
            if hostname_lower in all_cluster_nodes_lower:
                return all_cluster_nodes
        return [hostname]

if __name__ == "__main__":
    # Quick Test
    cmdb = TopologyMap()
    print("Testing Topology Map Correlation:")
    print(f"cell01 <-> dbnode02 : {cmdb.are_hosts_connected('cell01', 'dbnode02')} (Expected: True - Exadata Rack)")
    print(f"stg-db-01 <-> stg-db-02 : {cmdb.are_hosts_connected('stg-db-01', 'stg-db-02')} (Expected: True - RAC Sibling)")
    print(f"cell01 <-> stg-db-01 : {cmdb.are_hosts_connected('cell01', 'stg-db-01')} (Expected: False - Different Clusters)")
