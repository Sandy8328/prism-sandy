"""
DEPRECATED for production RCA — not used by ``src.agent.agent`` (evidence-first path).
Legacy session orchestrator with temporal-graph evaluation; tests and demos may still import this module.
"""

import sys
import os
import sqlite3
import re

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.append(project_root)

from src.agent.session_manager import IncidentSessionManager
from src.pipeline.temporal_graph import TemporalGraphEngine
from src.knowledge_graph.graph import get_commands_for_ora
from src.agent.evidence_aggregator import compute_confidence
from src.agent.classifier import classify_incident
from src.agent.knowledge_store import store_incident, find_known_pattern
from src.parsers.syslog_translator import translate, summarise
from src.knowledge_graph.knowledge_manager import learn_new_incident

class DBAChatbotOrchestrator:
    def __init__(self):
        self.session_manager = IncidentSessionManager()
        self.temporal_graph = TemporalGraphEngine(self.session_manager)
        self.golden_db_path = os.path.join(project_root, "tests", "vector_db", "metadata.duckdb")

    def _nlp_firewall_sanitize(self, prompt):
        """Strips bash commands from user chat input to prevent injection."""
        sanitized = re.sub(r'`[^`]*`', '[REDACTED EXECUTION]', prompt)
        sanitized = re.sub(r'\$\([^)]*\)', '[REDACTED EXECUTION]', sanitized)
        destructive = [
            r'\brm\s+-rf?\b', r'\bchmod\b', r'\bkill\b', r'\bkillall\b',
            r'\bdrop\s+table\b', r'\bdrop\s+database\b', r'\bgrant\s+dba\b',
            r'>\s*alert\.log\b', r'\bdd\b'
        ]
        for cmd in destructive:
            sanitized = re.sub(cmd, '[REDACTED COMMAND]', sanitized, flags=re.IGNORECASE)
        return sanitized

    def _fetch_authorized_resolution(self, error_code):
        """Fetches the 0% hallucinated action plan from the Golden Database."""
        try:
            conn = sqlite3.connect(self.golden_db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT action_plan FROM dba_runbooks WHERE error_code = ?", (error_code,))
            result = cursor.fetchone()
            conn.close()
            return result[0] if result else None
        except Exception as e:
            return None

    def submit_dba_feedback(self, error_code: str, log_snippet: str, runbook_commands: list[str],
                            platform: str, category: str, layer: str, fix_tier: str,
                            hostname: str = "unknown"):
        """
        Teach the agent a new error pattern at runtime.

        platform : LINUX | AIX | SOLARIS | HPUX | WINDOWS | EXADATA | UNKNOWN
        category : DB | OS | NETWORK | STORAGE | MEMORY | CLUSTER | SECURITY | APPLICATION
        layer    : INFRA | OS_TRIGGERED | ASM | MEMORY | NETWORK | CLUSTER | DB |
                   DATAGUARD | RMAN | SECURITY | APPLICATION
        fix_tier : Database | OS + Infrastructure | OS + ASM | OS + Database |
                   ASM | Network | Memory | Cluster | Application
        """
        print(f"\n[Learning Loop] Processing DBA Feedback for {error_code} "
              f"(platform={platform}, category={category}, layer={layer}, fix_tier={fix_tier})...")
        result = learn_new_incident(
            error_code=error_code,
            log_snippet=log_snippet,
            runbook_commands=runbook_commands,
            platform=platform,
            category=category,
            layer=layer,
            fix_tier=fix_tier,
            hostname=hostname
        )
        if result["status"] == "success":
            print(f"[Learning Loop] Successfully memorized fix. Node: {result['node_id']}")
        else:
            print(f"[Learning Loop] Failed to learn: {result.get('message')}")
        return result

    def handle_user_query(self, session_id, user_message):
        print("\n" + "=" * 80)
        print(" 🤖 ORACLE DBA DIAGNOSTIC AGENT (LIVE CHAT)")
        print("=" * 80)
        print(f"[User Message]: {user_message}")
        
        # 1. Firewall Sanitization
        clean_message = self._nlp_firewall_sanitize(user_message)
        if clean_message != user_message:
            print(f"  -> [Firewall] Stripped dangerous shell commands. Sanitized Input: {clean_message}")
            
        # 2. Trigger Temporal Graph on the Session
        print(f"  -> [Agent] Analyzing all logs uploaded to Session {session_id}...")
        anchor = self.temporal_graph.evaluate_session_timeline(session_id)
        
        if not anchor:
            msg = "I don't have enough logs in this session to make a diagnosis. Please upload the alert.log or /var/log/messages."
            print(f"\n[Agent Output]: '{msg}'")
            return {"root_cause": "N/A", "timestamp": "N/A", "resolution": msg}
            
        root_cause_error = anchor['content']
        # Extract the ORA or ACFS code using regex
        code_match = re.search(r'([A-Z]{2,5}-\d{4,5})', root_cause_error)
        os_match = re.match(r'^([A-Z0-9_]+)$', root_cause_error.strip())
        
        if code_match:
            error_code = code_match.group(1)
            print(f"  -> [Agent] Graph traversal complete. Root cause verified as {error_code}.")

            # 3a. Fetch graph-based exact commands (PDF runbook commands)
            cmd_result = get_commands_for_ora(error_code)
            graph_commands = cmd_result.get("commands", [])

            # 3b. Fetch narrative resolution from Golden DB (SQLite)
            print(f"  -> [Agent] Fetching authorized runbook for {error_code}...")
            resolution = self._fetch_authorized_resolution(error_code)

            if graph_commands or resolution:
                return {
                    "root_cause":     error_code,
                    "timestamp":      anchor.get("extracted_timestamp", "N/A"),
                    "resolution":     resolution or cmd_result.get("title", "See commands below."),
                    "commands":       graph_commands,
                    "runbook_title":  cmd_result.get("title", ""),
                    "fix_source":     cmd_result.get("source", "N/A"),
                    "fix_node_id":    cmd_result.get("fix_node_id"),
                    "raw_content":    anchor.get("content", ""),
                }
            else:
                msg = f"I found the root cause ({error_code}), but I do not have an authorized runbook for it in my Golden Database. Escalating to Senior DBA."
                print(f"\n[Agent Output]: '{msg}'")
                return {
                    "root_cause":  error_code,
                    "timestamp":   anchor.get("extracted_timestamp", "N/A"),
                    "resolution":  msg,
                    "commands":    [],
                    "fix_source":  "not_found",
                    "fix_node_id": None,
                    "raw_content": anchor.get("content", ""),
                }
        elif os_match:
            os_code = os_match.group(1)
            print(f"  -> [Agent] Graph traversal complete. Root cause verified as {os_code}.")
            msg = f"I have chronologically analyzed your uploaded logs. A systemic hardware/OS failure was detected causing the Oracle Database to cascade and crash. The specific OS error detected is: {os_code}. Because this is an OS-layer hardware failure, there is no Oracle Database runbook available. Please escalate this incident to your Linux/Sysadmin infrastructure team for immediate hardware troubleshooting."
            print(f"\n[Agent Output]: '{msg}'")
            return {
                "root_cause": os_code,
                "timestamp": anchor.get("extracted_timestamp", "N/A"),
                "resolution": msg,
                "raw_content": anchor.get("content", ""),
            }
        else:
            msg = f"I have chronologically analyzed your uploaded logs. The root cause appears to be: {root_cause_error}. Please follow standard OS troubleshooting."
            print(f"\n[Agent Output]: '{msg}'")
            return {
                "root_cause": "UNKNOWN",
                "timestamp": anchor.get("extracted_timestamp", "N/A"),
                "resolution": msg,
                "raw_content": anchor.get("content", ""),
            }

    def handle_enriched_query(
        self,
        session_id:   str,
        user_message: str,
        awr_filepath: str | None = None,
        osw_filepath: str | None = None,
        crs_is_clean: bool = False,
        raw_log_text: str | None = None,
    ) -> dict:
        """
        Full multi-evidence diagnostic path.

        In addition to the existing temporal graph analysis, this method:
          1. Parses AWR report (HTML or text) if provided
          2. Parses OSWatcher file if provided
          3. Computes weighted confidence score across all evidence
          4. Classifies the incident with heatmap and recommendations
          5. Checks knowledge store for known patterns
          6. Persists confirmed patterns (confidence >= 60) to duckdb

        Args:
            session_id   : Active session with uploaded alert.log / syslog
            user_message : User's diagnostic query
            awr_filepath : Path to AWR .html or .txt file (optional)
            osw_filepath : Path to OSWatcher .dat or .txt file (optional)
            crs_is_clean : True if CRS/ASM log has no critical events

        Returns extended dict with all diagnostic fields.
        """
        # ── Step 0: Syslog translation — raw text → OS_ERROR_PATTERN codes ───────
        # Runs BEFORE everything else so that pasted log snippets are immediately
        # mapped to internal graph codes, preventing false Tier 3 escalations.
        os_signals_from_text: list[str] = []
        if raw_log_text and raw_log_text.strip():
            translation_matches = translate(raw_log_text)
            if translation_matches:
                os_signals_from_text = [m.code for m in translation_matches]
                print(f"  -> [Syslog Translator] {summarise(translation_matches)}")
                # Inject translated OS codes into the session as synthetic log entries
                # so the temporal graph and evidence aggregator can see them.
                synthetic_entries = [
                    {
                        "hostname":           None,
                        "timestamp":          "2024-01-01T00:00:00",
                        "content":            m.code,
                        "file_source":        "syslog_translator",
                        "severity":           m.severity,
                        "translated_from":    m.matched_text,
                    }
                    for m in translation_matches
                ]
                self.session_manager.upload_log_to_session(session_id, synthetic_entries)
            else:
                print("  -> [Syslog Translator] No known OS patterns detected in pasted text.")

        # ── Step 1: Run base temporal graph analysis ──────────────────────────
        base_result = self.handle_user_query(session_id, user_message)

        # ── Step 2: Parse AWR if provided ─────────────────────────────────────
        awr_result = None
        if awr_filepath:
            try:
                from src.parsers.awr_parser import parse_awr_report
                awr_result = parse_awr_report(awr_filepath)
                if awr_result.get("parse_error"):
                    print(f"  -> [AWR Parser] Warning: {awr_result['parse_error']}")
                else:
                    print(f"  -> [AWR Parser] Signals: {awr_result.get('awr_signals', [])}")
            except Exception as e:
                print(f"  -> [AWR Parser] Error: {e}")

        # ── Step 3: Parse OSWatcher if provided ───────────────────────────────
        osw_result = None
        if osw_filepath:
            try:
                from src.parsers.osw_parser import parse_osw_report
                osw_result = parse_osw_report(osw_filepath)
                if osw_result.get("parse_error"):
                    print(f"  -> [OSW Parser] Warning: {osw_result['parse_error']}")
                else:
                    print(f"  -> [OSW Parser] Signals: {osw_result.get('osw_signals', [])}")
            except Exception as e:
                print(f"  -> [OSW Parser] Error: {e}")

        # ── Step 4: Compute confidence ────────────────────────────────────────
        confidence = compute_confidence(
            anchor_result = base_result if base_result.get("root_cause") != "N/A" else None,
            awr_result    = awr_result,
            osw_result    = osw_result,
            crs_is_clean  = crs_is_clean,
        )
        print(f"  -> [Confidence] Score: {confidence['confidence_score']} / 100 "
              f"({confidence['confidence_label']}) | "
              f"Sources: {confidence['evidence_sources']}")

        # ── Tier 3 intercept: code not found in graph.json or PDF ────────────
        # Ask the user for more evidence rather than producing an inaccurate diagnosis.
        if confidence.get("needs_more_info"):
            ora_code = base_result.get("root_cause", "the detected error")
            question = (
                f"I identified **{ora_code}** in your logs, but this error code is not "
                f"present in my knowledge base or the Oracle error message database. "
                f"To diagnose this accurately, could you please provide one or more of "
                f"the following from the same time window?\n"
                f"  1. AWR report (HTML or text) — shows database performance at the time\n"
                f"  2. OSWatcher archive (.dat) — shows OS memory/CPU at the time\n"
                f"  3. Any other ORA error codes that appeared alongside {ora_code}\n"
                f"  4. CRS alert log — if this is a RAC/Grid environment\n"
                f"  5. The full alert.log section around the incident time\n"
                f"The more evidence you provide, the more accurate the diagnosis will be."
            )
            print(f"\n[Agent Output — Needs More Info]: '{question}'")
            enriched = dict(base_result)
            enriched.update({
                "evidence_sources":  confidence["evidence_sources"],
                "active_signals":    confidence["active_signals"],
                "score_breakdown":   confidence["score_breakdown"],
                "confidence_score":  confidence["confidence_score"],
                "confidence_label":  confidence["confidence_label"],
                "issue_category":    "Needs More Information",
                "rca":               question,
                "risk_score":        "UNDETERMINED",
                "heatmap":           {},
                "recommendations":   [question],
                "rule_matched":      "TIER_3_NEEDS_MORE_INFO",
                "knowledge_stored":  False,
                "known_pattern_id":  None,
                "needs_more_info":   True,
            })
            
            # [Phase 4 - Edge Case 14: Inode Exhaustion]
            if ora_code in ("ORA-27040", "ORA-19502", "ORA-00270"):
                inode_msg = "MANDATORY: Run `df -i` on the database server. If `df -h` shows free space but the database reports 'No space left on device', the filesystem has likely run out of inodes."
                if inode_msg not in enriched["recommendations"]:
                    enriched["recommendations"].append(inode_msg)

            # [Phase 4 - Edge Case 20: Unkillable Zombie]
            if "PROCESS_D_STATE_ZOMBIE" in confidence["active_signals"]:
                zombie_msg = "MANDATORY: OSWatcher detected processes stuck in 'D' state (Uninterruptible Sleep). These processes are hung in kernel space, likely due to a storage or NFS hang. They cannot be terminated with `kill -9`. You must resolve the underlying storage hang or reboot the server."
                if zombie_msg not in enriched["recommendations"]:
                    enriched["recommendations"].append(zombie_msg)

            # [Phase 4 - Edge Case 21: ASM Self-Inflicted DoS]
            if "ASM_HIGH_POWER_REBALANCE" in confidence["active_signals"]:
                asm_msg = "MANDATORY: A high-power ASM rebalance operation was detected. This can monopolize storage I/O and cause a self-inflicted Denial of Service. Check `v$asm_operation` and reduce the rebalance power limit."
                if asm_msg not in enriched["recommendations"]:
                    enriched["recommendations"].append(asm_msg)

            # [Phase 4 - Edge Case 31: Desynced Reality (FRA Split Brain)]
            if ora_code in ("ORA-19815", "ORA-19809", "ORA-19804"):
                fra_msg = "MANDATORY: The database reports the Fast Recovery Area (FRA) is 100% full. If `df -h` at the OS level shows plenty of free space, someone deleted archive logs directly from the OS without using RMAN. You must run `RMAN> CROSSCHECK ARCHIVELOG ALL; DELETE EXPIRED ARCHIVELOG ALL;` to resync the database with reality."
                if fra_msg not in enriched["recommendations"]:
                    enriched["recommendations"].append(fra_msg)

            # [Phase 4 - Edge Case 23: Observer Split-Brain]
            if ora_code.startswith("ORA-166") or "LAYER_DATAGUARD" in confidence["active_signals"]:
                dg_msg = "MANDATORY: Data Guard Broker issue detected. You must analyze the broker log (`drc*.log`) in the DIAG trace directory to determine if the Fast-Start Failover (FSFO) Observer has lost contact or if there is a split-brain scenario."
                if dg_msg not in enriched["recommendations"]:
                    enriched["recommendations"].append(dg_msg)

            # [Phase 4 - Edge Cases 17 & 18: Kill -9 Murder & SELinux]
            if "AUDITD_KILL_9" in confidence["active_signals"]:
                kill_msg = "CRITICAL: The OS audit log detected a `kill -9` signal sent to an Oracle background process by a user. This is a manual termination, not an Oracle crash. Please investigate user activity."
                if kill_msg not in enriched["recommendations"]:
                    enriched["recommendations"].append(kill_msg)
            elif "OS_SELINUX_BLOCK" in confidence["active_signals"]:
                selinux_msg = "CRITICAL: SELinux is actively blocking Oracle from accessing necessary files or network ports. Check `/var/log/audit/audit.log` for AVC denial messages."
                if selinux_msg not in enriched["recommendations"]:
                    enriched["recommendations"].append(selinux_msg)
            
            return enriched

        # ── Step 5: Classify incident ─────────────────────────────────────────
        classification = classify_incident(
            active_signals   = confidence["active_signals"],
            confidence_score = confidence["confidence_score"],
        )
        print(f"  -> [Classifier] Category: {classification['issue_category']} "
              f"| Risk: {classification['risk_score']}")

        # ── Step 6: Check knowledge store for known pattern ───────────────────
        known_pattern = None
        ora_code = base_result.get("root_cause", "UNKNOWN")
        if ora_code not in ("N/A", "UNKNOWN"):
            known_pattern = find_known_pattern(
                ora_code       = ora_code,
                active_signals = confidence["active_signals"],
            )
            if known_pattern:
                print(f"  -> [KnowledgeStore] KNOWN PATTERN found: "
                      f"{known_pattern['incident_id']} "
                      f"(overlap: {known_pattern['signal_overlap']} signals)")

        # ── Step 7: Persist to knowledge store if confidence is high ──────────
        knowledge_stored = False
        if ora_code not in ("N/A", "UNKNOWN"):
            knowledge_stored = store_incident(
                incident_id      = session_id,
                ora_code         = ora_code,
                issue_category   = classification["issue_category"],
                rca              = classification["rca"],
                confidence_score = confidence["confidence_score"],
                risk_score       = classification["risk_score"],
                active_signals   = confidence["active_signals"],
                resolution_cmds  = base_result.get("commands", []),
                heatmap          = classification["heatmap"],
            )
            if knowledge_stored:
                print(f"  -> [KnowledgeStore] Pattern persisted for {ora_code}")

        # ── Build extended result dict ────────────────────────────────────────
        enriched = dict(base_result)   # keep all base fields intact
        enriched.update({
            # Evidence
            "evidence_sources":   confidence["evidence_sources"],
            "active_signals":     confidence["active_signals"],
            "score_breakdown":    confidence["score_breakdown"],
            # Confidence
            "confidence_score":   confidence["confidence_score"],
            "confidence_label":   confidence["confidence_label"],
            # Classification
            "issue_category":     classification["issue_category"],
            "rca":                classification["rca"],
            "risk_score":         classification["risk_score"],
            "heatmap":            classification["heatmap"],
            "recommendations":    classification["recommendations"],
            "rule_matched":       classification["rule_matched"],
            # Knowledge store
            "knowledge_stored":   knowledge_stored,
            "known_pattern_id":   known_pattern["incident_id"] if known_pattern else None,
        })
        # [Phase 4 - Edge Case 14: Inode Exhaustion]
        # If the DB reports no space, but df -h might look fine, force the user to check inodes.
        if ora_code in ("ORA-27040", "ORA-19502", "ORA-00270"):
            inode_msg = "MANDATORY: Run `df -i` on the database server. If `df -h` shows free space but the database reports 'No space left on device', the filesystem has likely run out of inodes."
            if inode_msg not in enriched["recommendations"]:
                enriched["recommendations"].append(inode_msg)

        # [Phase 4 - Edge Case 20: Unkillable Zombie]
        if "PROCESS_D_STATE_ZOMBIE" in confidence["active_signals"]:
            zombie_msg = "MANDATORY: OSWatcher detected processes stuck in 'D' state (Uninterruptible Sleep). These processes are hung in kernel space, likely due to a storage or NFS hang. They cannot be terminated with `kill -9`. You must resolve the underlying storage hang or reboot the server."
            if zombie_msg not in enriched["recommendations"]:
                enriched["recommendations"].append(zombie_msg)

        # [Phase 4 - Edge Case 21: ASM Self-Inflicted DoS]
        if "ASM_HIGH_POWER_REBALANCE" in confidence["active_signals"]:
            asm_msg = "MANDATORY: A high-power ASM rebalance operation was detected. This can monopolize storage I/O and cause a self-inflicted Denial of Service. Check `v$asm_operation` and reduce the rebalance power limit."
            if asm_msg not in enriched["recommendations"]:
                enriched["recommendations"].append(asm_msg)

        # [Phase 4 - Edge Case 31: Desynced Reality (FRA Split Brain)]
        if ora_code in ("ORA-19815", "ORA-19809", "ORA-19804"):
            fra_msg = "MANDATORY: The database reports the Fast Recovery Area (FRA) is 100% full. If `df -h` at the OS level shows plenty of free space, someone deleted archive logs directly from the OS without using RMAN. You must run `RMAN> CROSSCHECK ARCHIVELOG ALL; DELETE EXPIRED ARCHIVELOG ALL;` to resync the database with reality."
            if fra_msg not in enriched["recommendations"]:
                enriched["recommendations"].append(fra_msg)

        # [Phase 4 - Edge Case 23: Observer Split-Brain]
        if ora_code.startswith("ORA-166") or "LAYER_DATAGUARD" in confidence["active_signals"]:
            dg_msg = "MANDATORY: Data Guard Broker issue detected. You must analyze the broker log (`drc*.log`) in the DIAG trace directory to determine if the Fast-Start Failover (FSFO) Observer has lost contact or if there is a split-brain scenario."
            if dg_msg not in enriched["recommendations"]:
                enriched["recommendations"].append(dg_msg)

        # [Phase 4 - Edge Cases 17 & 18: Kill -9 Murder & SELinux]
        if "AUDITD_KILL_9" in confidence["active_signals"]:
            kill_msg = "CRITICAL: The OS audit log detected a `kill -9` signal sent to an Oracle background process by a user. This is a manual termination, not an Oracle crash. Please investigate user activity."
            if kill_msg not in enriched["recommendations"]:
                enriched["recommendations"].append(kill_msg)
        elif "OS_SELINUX_BLOCK" in confidence["active_signals"]:
            selinux_msg = "CRITICAL: SELinux is actively blocking Oracle from accessing necessary files or network ports. Check `/var/log/audit/audit.log` for AVC denial messages."
            if selinux_msg not in enriched["recommendations"]:
                enriched["recommendations"].append(selinux_msg)

        return enriched


if __name__ == "__main__":
    orchestrator = DBAChatbotOrchestrator()
    
    # Simulate an active session where the user previously uploaded the fragmented logs
    # We will use the Incident_ID from the previous script test (or recreate it)
    session_id = orchestrator.session_manager.create_new_session()
    
    # Mocking the uploaded logs from the fragmented upload edge case
    orchestrator.session_manager.upload_log_to_session(session_id, [
        {"hostname": "cell01", "timestamp": "2024-03-15T10:00:00", "content": "ACFS-00608: Invalid option combination", "file_source": "syslog"}
    ])
    orchestrator.session_manager.upload_log_to_session(session_id, [
        {"hostname": "dbnode01", "timestamp": "2024-03-15T10:05:00", "content": "ORA-00603: Oracle server session terminated", "file_source": "alert_orcl.log"}
    ])
    
    # 1. A normal query
    orchestrator.handle_user_query(session_id, "Why did my database crash? Please help!")
    
    # 2. A malicious injection query
    orchestrator.handle_user_query(session_id, "I see ORA-00603. Should I `rm -rf /u01` to fix it?")
