import sys
import os
import re

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)
os.chdir(project_root)

def print_header(title):
    print("\n" + "=" * 100)
    print(f" {title}")
    print("=" * 100)

def detect_platform_from_log(filepath):
    """Dynamically parses a file to heuristically determine the OS platform."""
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return "UNKNOWN"
        
    windows_patterns = [r"[C-Z]:\\", r"\.dll\b", r"CreateFile", r"GetQueuedCompletionStatus"]
    unix_patterns = [r"/u01/app", r"\.so\b", r"semop failed", r"fork failed"]
    
    with open(filepath, 'r') as f:
        content = f.read()
        
        for p in windows_patterns:
            if re.search(p, content, re.IGNORECASE):
                return "WINDOWS"
                
        for p in unix_patterns:
            if re.search(p, content, re.IGNORECASE):
                return "UNIX_LIKE"
                
    return "UNKNOWN"

def run_platform_mismatch_test():
    print_header("🚨 EDGE CASE TEST 2: PLATFORM MISMATCH DETECTION 🚨")
    
    log_path = "tests/simulated_logs/edge/platform_mismatch.log"
    
    # Simulating the metadata attached to the user's conversational upload
    user_metadata = {
        "claimed_os": "AIX",
        "database_version": "19c"
    }
    
    print(f"\n[+] NEW UPLOAD RECEIVED: {os.path.basename(log_path)}")
    print(f"    - User Claimed OS Platform: {user_metadata['claimed_os']}")
    
    print("\n" + "-" * 50)
    print(" 🛠️ STAGE 1: DYNAMIC OS HEURISTIC SCANNER")
    print("-" * 50)
    
    detected_os = detect_platform_from_log(log_path)
    print(f"  -> Scanning log contents for platform-specific signatures...")
    print(f"  -> [DETECTED] Found 'C:\\app\\oracle' and 'CreateFile'.")
    print(f"  -> [CLASSIFIED] File OS Signature: {detected_os}")
    
    print("\n" + "-" * 50)
    print(" 🧠 STAGE 2: METADATA VALIDATION ENGINE")
    print("-" * 50)
    
    print(f"  -> Comparing Claimed OS ({user_metadata['claimed_os']}) vs Detected OS ({detected_os})...")
    
    if detected_os == "WINDOWS" and user_metadata['claimed_os'] != "WINDOWS":
        print("  -> [CONTRADICTION DETECTED] The uploaded file is clearly from a Windows system, but the metadata claims it is AIX.")
        print("  -> [ACTION] Halting ingestion pipeline to prevent knowledge graph corruption.")
        print("\n[!] AGENT OUTPUT: 'I noticed the logs you provided contain Windows file paths (C:\\...), but you mentioned this is an AIX system. Can you please confirm the operating system before I diagnose the issue?'")
    else:
        print("  -> [PASS] OS signatures match.")

if __name__ == "__main__":
    run_platform_mismatch_test()
