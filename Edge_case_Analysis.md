# Edge Case Analysis

## Vulnerabilities in Current Rules & Logic

While the deterministic matching, 60-second chunking windows, and confidence scoring models are robust for 95% of incidents, enterprise infrastructure produces rare anomalies that could break our current logic.

Here is an analysis of the critical edge cases currently missing or unhandled in the agent's logic:

---

## 1. Cross-Node RAC Evictions (The "Victim vs. Culprit" Problem)

**The Flaw:** `chunking_rules.md` strictly states that chunks are isolated by `hostname`.
**The Edge Case:** In Oracle Real Application Clusters (RAC), Node A might be evicted (crashed) because Node B experienced a massive CPU spike or network degradation.

- Node A logs show `CRS-1618: Node not responding` and an instance crash.
- Node B logs hold the _actual_ root cause (e.g., `OOM_KILLER`).
  **Why we fail:** Because our correlation logic requires `hostname == H`, the agent will fail to link the root cause on Node B to the crash on Node A.
  **Fix Required:** Introduce a "Cluster ID" or "Cross-Node Correlation" rule specifically for RAC environments, allowing ±60s correlation across sibling hostnames.

## 2. Exadata Distributed Architecture

**The Flaw:** Same as above—correlation requires matching hostnames.
**The Edge Case:** Oracle Exadata splits architecture into **Compute Nodes** (where the DB runs) and **Storage Cell Nodes** (where the disks live). If a disk fails on `cell01`, the DB crashes on `dbnode01`.
**Why we fail:** The logs on `dbnode01` will show an ASM dismount (`ORA-15080`), but the `cellcli` logs on `cell01` show the disk failure. The agent will not link them.
**Fix Required:** The agent must map Compute Nodes to their backing Cell Nodes, treating them as a single logical entity for multi-source corroboration.

## 3. Time Drift & VM Suspensions (Clock Sync Failures)

**The Flaw:** The Temporal Proximity score assumes the OS clock (`/var/log/messages`) and the Oracle internal clock (`alert.log`) are perfectly synchronized.
**The Edge Case:**

- If `ntpd`/`chronyd` dies, or if a hypervisor (VMware) briefly suspends the VM causing a time jump, the OS time and Oracle time can drift by several minutes.
- **Why we fail:** An OS hardware error could occur at `02:45:00` (OS time), but Oracle logs the crash at `02:40:00` (Oracle time). Our 60-second correlation window entirely misses the event.
  **Fix Required:** The agent must calculate the $\Delta$ between OS time and Oracle trace timestamps in the AHF collection to establish a "Drift Offset" before applying the 60-second window.

## 4. The "Sudden Death" Paradox (Lack of Corroboration)

**The Flaw:** The Multi-Source Corroboration dimension heavily rewards events seen across OS, ASM, and DB logs.
**The Edge Case:** A severe hardware failure (e.g., Kernel Panic or instantaneous power loss) kills the OS instantly.
**Why we fail:** The Database `alert.log` never gets a chance to record an `ORA-` error because the DBWn/LGWR processes are terminated instantly. The agent might assign a _Low Confidence_ score to the Kernel Panic because it lacks multi-source corroboration, even though it is 100% the root cause.
**Fix Required:** The `ScoringEngine` must include a "Fatal OS Event Override" rule. Events like `KERNEL_PANIC` or `HARD_LOCKUP` should automatically bypass corroboration requirements.

## 5. Log File Rotation Boundaries

**The Flaw:** We chunk logs sequentially.
**The Edge Case:** A cascade event starts at `23:59:58`. At `00:00:00`, `logrotate` rotates `/var/log/messages` to `messages-20240421` and starts a new file.
**Why we fail:** The incident is physically split across two different files. Our parser might treat them as two isolated, incomplete events.
**Fix Required:** The log ingestion pipeline must logically stitch rotated files together chronologically before chunking.

## 6. Shared Bus Failures (Violating Device Isolation)

**The Flaw:** `chunking_rules.md` (Rule 3) isolates events by device (e.g., `sdb` errors go to Chunk A, `sdc` errors go to Chunk B).
**The Edge Case:** An entire PCIe bus or storage controller resets. This causes `sdb`, `sdc`, `sdd`, and `eth0` to all fail simultaneously within 1 second.
**Why we fail:** The agent will generate 4 isolated chunks, missing the fact that this is a systemic bus failure, not 3 bad disks and a bad NIC.
**Fix Required:** If >3 independent hardware devices fail within a 2-second window, the agent must merge them into a new `SYSTEM_BUS_RESET` super-chunk.

## 7. The "Silent Hang" (No Logs Generated)

**The Flaw:** The agent relies on log lines existing.
**The Edge Case:** A TCP "Half-Open" connection drop (e.g., an external firewall silently drops packets without sending a TCP RST).
**Why we fail:** Neither the OS nor Oracle generates an error log. The database simply "hangs" waiting for SQL*Net client data.
**Fix Required:** The agent must ingest active connection state (`netstat` / `ss`) or AWR Wait Events (`SQL*Net message from client`) as primary evidence, even when error logs are empty.

## 8. Sparse Human Input (The "Lazy Query" Edge Case)

**The Flaw:** The RAG pipeline and Scoring Engine assume rich, multi-layered log data is ingested (e.g., full AHF zip files or complete OS syslog dumps).
**The Edge Case:** The DBA queries the chatbot with minimal, sparse text: _"Database crashed at 02:44, I see ORA-00603."_
**Why we fail:** There is no OS log, no ASM log, no hardware device ID, and no stack trace. BM25 text retrieval on "ORA-00603" might blindly match an OOM Killer cascade from the seed database, but the actual cause for this specific user could have been a multipath failure. With no corroborating logs, the system might confidently provide the wrong runbook.
**Fix Required:** The chatbot must implement a **"Progressive Disclosure" or "Dynamic Clarification" loop**. If the query lacks OS/Hardware context, the agent must _pause_ the diagnostic decision. It should automatically generate a safe shell script or prompt asking the user: _"I need OS context. Please run `grep -A 20 -B 20 02:44 /var/log/messages` and paste the output before I can diagnose this cascade."_

---

## 9. Chunking Rules Edge Case: The "Boundary Split" Regex Miss

**The Flaw:** Rule 4 limits chunks to 50 lines with a 5-line overlap.
**The Edge Case:** A Java stack trace inside the Oracle `alert.log` spans 80 lines. The actual `ORA-` code is on line 1, and the root cause `Caused by: java.lang.OutOfMemoryError` is on line 75.
**Why we fail:** The chunking engine splits this into Chunk A (Lines 1-50) and Chunk B (Lines 45-80). The agent evaluates them independently. Chunk A has the ORA code but no root cause. Chunk B has the OOM error but no ORA code. Neither chunk triggers a high-confidence match.
**Fix Required:** Introduce an "Atomic Block" rule. If a chunk detects a stack trace block (e.g., `Call Trace:` in Linux or `Exception in thread` in Java), the 50-line limit is dynamically suspended until the block ends.

## 10. Cascading Rules Edge Case: The "Domino Delay" (Delayed Cascades)

**The Flaw:** Cascade correlation assumes a ±60-second proximity window between OS and DB events.
**The Edge Case:** An ASM disk goes offline (`ORA-15080`) at 14:00:00. The database keeps running fine in memory. 15 minutes later (at 14:15:00), the Log Writer (LGWR) finally attempts to write to that specific disk and crashes the instance (`ORA-00603`).
**Why we fail:** The 15-minute gap far exceeds our 60-second window. The agent treats the disk drop and the DB crash as two entirely separate, unrelated incidents.
**Fix Required:** The Causal Graph Engine must introduce **"Stateful Cascade Memory."** If a critical infrastructure component (Disk, Network Link) drops, its failure state is held in memory indefinitely until a recovery message is seen. Any DB crash during that state is linked, regardless of the time gap.

## 11. False Positive Rules Edge Case: The "Cry Wolf" Threshold

**The Flaw:** Our strict catalog intentionally drops benign events to reduce alert fatigue. For example, `ORA-3136: Inbound connection timed out` is ignored as a routine port-scanner ping.
**The Edge Case:** A massive network routing failure (or a DDoS attack) causes 50,000 legitimate application connections to hang and drop, flooding the log with `ORA-3136`. This exhausts the Oracle listener and shared pool, eventually freezing the database.
**Why we fail:** Because `ORA-3136` is marked as a False Positive, the agent's pre-processor silently drops all 50,000 lines. When the database freezes, the agent sees zero evidence of the network flood.
**Fix Required:** False Positive rules must be **Volume-Aware Thresholds**, not absolute booleans. Rule: "Ignore `ORA-3136` UNLESS frequency exceeds >100 per minute, then escalate to CRITICAL."

## 12. Vector (BM25) Rules Edge Case: Version Terminology Drift

**The Flaw:** BM25 relies on exact lexical text overlap (term frequency) between the incoming log and our seed database.
**The Edge Case:** Our seeds are modeled on Oracle 19c, which logs `"Result Cache Exhaustion"`. In Oracle 23c, the development team changes the logging string to `"Result Memory Limit Exceeded"`.
**Why we fail:** BM25 fails to match "Cache Exhaustion" to "Memory Limit". The confidence score plummets, and the agent fails to retrieve the correct runbook despite knowing the error.
**Fix Required:** The RAG pipeline must run a **Query Expansion / Synonym Layer** before hitting BM25. It should map known terminology changes across Oracle versions (e.g., Cache <-> Memory Limit, RAC <-> Clusterware) into the search query.

## 13. AWR Correlation Edge Case: The "Symptom vs. Disease" Trap

**The Flaw:** The agent maps Oracle AWR wait events to OS root causes (e.g., `log file sync` = Slow Disk).
**The Edge Case:** The disk is actually lightning fast. However, a runaway application process has saturated the CPU to 100%. Because the CPU is saturated, the Oracle LGWR process is starved for CPU cycles and cannot issue the I/O to the fast disk. The AWR report shows massive `log file sync` waits.
**Why we fail:** The agent blindly sees `log file sync` and outputs a runbook to "Check SAN/Storage Array." The Storage Admin wastes hours investigating healthy disks.
**Fix Required:** AWR wait event rules must be **Conditional**. `log file sync` points to Storage ONLY IF `OS CPU %idle > 10%`. If `%idle < 5%`, the root cause shifts to CPU starvation, ignoring the I/O wait symptom.

---

## 14. Storage Rules Edge Case: The "Inode Exhaustion" Illusion

**The Flaw:** Storage diagnostic logic heavily relies on checking free disk space percentages (`df -h`).
**The Edge Case:** A runaway background process generates 10 million tiny 1KB trace files. The disk is technically only 50% full, but it completely runs out of _Inodes_. Oracle throws an `ORA-27040` (Failed to create file).
**Why we fail:** The agent checks the `df` command output, sees "50% Free Space," and incorrectly assumes the disk is healthy. It misdiagnoses the root cause because it failed to check `df -i` (Inodes).
**Fix Required:** The diagnostic ingestion engine must mandate parsing of `df -i` output whenever an `ORA-27040` or `ENOSPC` (Error 28) is detected, bypassing standard space percentage checks.

## 15. Network Rules Edge Case: The "Jumbo Frame Black Hole"

**The Flaw:** Network health checks rely on OS log link states (e.g., `eth0: link up`) or simple ping tests.
**The Edge Case:** In a RAC cluster, a network engineer misconfigures a switch port to MTU 1500, but the Linux server is set to MTU 9000 (Jumbo Frames). Small packets (pings) pass perfectly, so OS logs say the network is "UP". But large Oracle Cache Fusion blocks drop silently without generating OS-level disconnect errors.
**Why we fail:** There are zero errors in `/var/log/messages` and no dropped interfaces. The database grinds to a halt with massive `gc cr block lost` waits. The agent wrongly blames the database because the OS logs insist the network is healthy.
**Fix Required:** Add an explicit network rule: If RAC `gc` wait events spike, the agent must trigger a diagnostic runbook to execute `ping -s 8972 -M do <interconnect_ip>` to explicitly test MTU fragmentation, overriding the OS "link up" status.

## 16. Multi-Tenancy (CDB/PDB) Edge Case: "Resource Manager Silent Throttle"

**The Flaw:** Diagnostics typically look for global system exhaustion (OS CPU 100%).
**The Edge Case:** In an Oracle Multi-tenant environment, a specific Pluggable Database (PDB) exhausts its assigned CPU limit. Oracle Resource Manager deliberately throttles or terminates its sessions.
**The Blind Spot:** The underlying OS is perfectly healthy (CPU is only at 40%). The Container Database (CDB) alert log shows no global errors. The agent fails to diagnose the problem because the "error" is actually Oracle working exactly as designed to punish a noisy PDB.
**Fix Required:** The agent must integrate `v$rsrc_plan` and PDB-specific wait events into its symptom checks before looking at OS-level CPU metrics.

## 17. Human Error Edge Case: The "Kill -9 Murder"

**The Flaw:** The agent relies on system failure logs to diagnose crashes.
**The Edge Case:** A junior DBA or an automated script accidentally runs `kill -9` on the Oracle `pmon` process. The database crashes instantly.
**Why we fail:** The OS logs nothing (running a `kill` command is a valid user action, not a system failure). Oracle logs nothing (PMON was terminated before it could write a dump file). The agent is completely blind because neither system generated an error log.
**Fix Required:** Introduce a "Sudden Death Pattern". If an Oracle background process disappears without an `ORA-` code or an OS `OOM_KILLER` event, the agent must automatically query bash history, `auditd` logs, or `lastcomm` to trace the rogue user command.

## 18. Security Rules Edge Case: The "Silent SELinux/Audit Block"

**The Flaw:** The agent strictly parses standard `/var/log/messages` or `syslog` for OS errors.
**The Edge Case:** A security admin enforces an SELinux policy or AppArmor profile that prevents the `oracle` user from reading a specific directory. Oracle processes crash or hang with generic "Permission Denied" errors.
**Why we fail:** The OS might not print SELinux blocks to `/var/log/messages`; they are typically routed to `/var/log/audit/audit.log`. The agent completely misses the security denial because it's looking in the wrong log file.
**Fix Required:** The ingestion engine must mandate the inclusion of `/var/log/audit/audit.log` when analyzing `Permission Denied` or `EACCES` errors.

---

## 19. Memory Rules Edge Case: The "NUMA Node Imbalance" (HugePages)

**The Flaw:** The agent relies on global memory health metrics (`free -g`, `vmstat`).
**The Edge Case:** The server has 512GB of RAM, and the global OS metrics show 200GB is totally free. However, the server has multiple physical CPUs (NUMA nodes). NUMA Node 0 has 0GB free, while NUMA Node 1 has 200GB free.
**Why we fail:** Oracle processes running on Node 0 suddenly get targeted by the Linux `OOM_KILLER` because local memory is exhausted. The agent completely misdiagnoses this because it looks at global memory and thinks everything is healthy.
**Fix Required:** The agent must explicitly parse `numastat` or `numactl --hardware` metrics when an `OOM_KILLER` event occurs on a server that appears to have free global memory.

## 20. OS Kernel Edge Case: The "Unkillable Zombie" (D-State)

**The Flaw:** Standard remediation for process limits involves altering DB configuration.
**The Edge Case:** The database throws `ORA-00020: maximum number of processes exceeded`. An NFS mount hung on the backend, leaving 1,000 Oracle shadow processes stuck in Uninterruptible Sleep (**D-State**) waiting for I/O.
**Why we fail:** The agent sees "process limit exceeded" and suggests "Increase the `processes` parameter." It doesn't realize that you can't even `kill -9` these processes. The agent's fix just creates more zombies until the server crashes.
**Fix Required:** Whenever process limits are hit, the agent must check the `STAT` column of OS process logs (e.g., `top` or `ps`) for `D` (Uninterruptible Sleep). If found, the runbook must pivot to fixing the hanging storage, not the database parameters.

## 21. ASM Edge Case: The "Self-Inflicted I/O Denial of Service"

**The Flaw:** The agent looks for explicit system errors to explain performance drops.
**The Edge Case:** Application queries grind to a halt. AWR reports massive `db file sequential read` waits. There are zero hardware errors. The real cause is that a DBA just added disks to ASM and triggered a rebalance with a high power limit (`ALTER DISKGROUP DATA REBALANCE POWER 11`), which is silently consuming 100% of the SAN bandwidth.
**Why we fail:** The agent blames the Storage Area Network (SAN) or disks because it misses the fact that the DBA's "normal" administrative action is the root cause.
**Fix Required:** The agent must query the `v$asm_operation` view to detect active high-power rebalances before blaming storage hardware for unexplained I/O latency.

## 22. Cloud Infrastructure Edge Case: The "Noisy Neighbor" (CPU Steal Time)

**The Flaw:** The agent trusts the VM's internal view of its CPU usage.
**The Edge Case:** The Oracle DB is running in AWS/OCI/Azure. The underlying physical hypervisor becomes oversubscribed, and the cloud provider briefly pauses the VM.
**Why we fail:** The OS logs inside the VM show zero errors. Internal CPU usage looks low. The agent is completely blind to the fact that the VM is being starved of cycles by the host.
**Fix Required:** The agent must explicitly parse the **`%steal`** CPU metric from `sar` or `top` outputs when diagnosing unexplained database stalls in cloud environments.

## 23. Data Guard Edge Case: The "Observer Split-Brain"

**The Flaw:** Network diagnostics focus solely on the primary database server's logs.
**The Edge Case:** In a Fast-Start Failover (FSFO) setup, the network drops between the Primary DB and the Standby DB, but the Observer (third server) can still talk to both.
**Why we fail:** The `alert.log` fills with `ORA-` network timeouts. The agent diagnoses a basic network drop. But it misses the Observer's state machine, which might freeze Primary I/O or attempt an unwarranted failover.
**Fix Required:** In any Data Guard topology, the agent must require the ingestion of the `drc*.log` (Data Guard Broker log) to evaluate the cluster state, rather than relying strictly on the primary `alert.log`.

---

## 24. OS Kernel Edge Case: The "Dirty Cache Flush" Freeze

**The Flaw:** The agent looks for explicit system errors to explain database hangs.
**The Edge Case:** The Linux server has 256GB of RAM. The OS `vm.dirty_ratio` is left at the default 20%. Oracle writes heavily, filling up 50GB of RAM with "dirty" (unwritten) data. Suddenly, the OS hits the 20% limit and forcefully halts _all_ processes to flush 50GB of data to the SAN at once.
**Why we fail:** Oracle freezes for 30 seconds. The DBA checks `/var/log/messages`. There are **zero errors**. The agent finds no fault because "Linux doing its job" isn't an error. The agent completely misses the fact that the OS kernel temporarily choked the database.
**Fix Required:** The agent must explicitly check `vmstat` for massive spikes in `bo` (blocks out) combined with `wa` (I/O wait) without corresponding hardware disk errors.

## 25. OS Kernel Edge Case: The "OOM Collateral Damage" Drop

**The Flaw:** The agent typically links OOM killer events directly to database process terminations.
**The Edge Case:** The Linux OOM Killer activates, but instead of killing the Oracle database, it kills the `multipathd` daemon or the `sshd` daemon.
**Why we fail:** Oracle keeps running fine... until 10 minutes later when a storage path drops and `multipathd` isn't there to reroute the traffic, causing an ASM crash. The agent might link the ASM crash to the disk drop, but miss the fact that the OOM killer murdered the OS daemon 10 minutes prior.
**Fix Required:** The agent must implement a "Critical Daemon Watchlist." If an `OOM_KILLER` targets a daemon on that list (e.g., `multipathd`, `iscsid`, `ntpd`), it must trigger a proactive warning even if the database is currently healthy.

## 26. Chatbot/UI Edge Case: The "Out-Of-Domain" (OOD) Hallucination

**The Flaw:** BM25 is a text-similarity search engine that will always try to force a match to the seed database.
**The Edge Case:** A user uploads a completely unrelated error to the chatbot, such as a generic `"Python IndexError: list out of bounds"` or a `"Windows Update 0x80070005 Failed"` error.
**Why we fail:** BM25 might lock onto a random overlapping word (like "Index"). It will retrieve the lowest-scoring seed (e.g., `"ORA-01502: index or partition of such index is in unusable state"`) and confidently tell the user to rebuild their Oracle Database Index to fix their Python script!
**Fix Required:** The agent must enforce a strict **BM25 Confidence Floor (Relevance Threshold)**. If the highest BM25 score is `< 0.45`, the agent must **refuse to diagnose**. The Chatbot must respond: _"I am a specialized Oracle DBA Diagnostic Agent. The log you uploaded does not match any recognized Oracle Database or OS Infrastructure failure patterns."_

## 27. Chatbot/UI Edge Case: The "Fragmented Upload" (Asynchronous Correlation)

**The Flaw:** The agent evaluates log files at the exact moment they are uploaded.
**The Edge Case:** A user uploads their `alert.log` and asks, "Why did my database crash?" The agent diagnoses an `ORA-00603` with low confidence. Five minutes later in the same chat, the user says, "Oh wait, here is the OS log," and uploads `/var/log/messages`.
**Why we fail:** Because the files were uploaded separately, the agent evaluates them in isolation. It diagnoses the OS log as a disk failure, but completely misses the fact that the disk failure _caused_ the database crash uploaded 5 minutes prior. The agent is confused about which error happened "1st" because it is relying on the _upload sequence_ rather than the _chronological sequence_.
**Fix Required:** The chatbot must implement a **"Session-Scoped Temporal Graph."** Regardless of the order in which files are uploaded, the agent must extract all timestamps into a unified session memory. Every time a new file is uploaded, the agent must trigger a **Re-Evaluation Pass**—sorting all logs from the current chat session chronologically. The absolute earliest timestamp mathematically becomes the causal anchor (the Root Cause), automatically rebuilding the cascade chain across the fragmented uploads.

---

## 28. Localization Rules Edge Case: The "Non-English Log" Match Failure

**The Flaw:** The agent's regex patterns and BM25 seeds expect English keywords (`"FAILED"`, `"Out of memory"`, `"Link Down"`).
**The Edge Case:** The Linux OS or Oracle Database is installed with a non-English locale (e.g., `LANG=fr_FR.UTF-8`). The logs print `"Échec"` or `"Mémoire insuffisante"`.
**Why we fail:** BM25 text retrieval completely fails because the foreign language words do not match the English seed database. The confidence score zeroes out, and the agent fails to diagnose the problem.
**Fix Required:** The agent must implement a log-translation or localized regex layer during ingestion, normalizing critical OS/Oracle keywords back to standard English before passing the chunk to the BM25 vector engine.

## 29. Parsing Rules Edge Case: The "Massive PL/SQL Dump"

**The Flaw:** The chunking rules strictly enforce a 50-line limit per chunk.
**The Edge Case:** A developer's badly written 500-line PL/SQL block fails, and Oracle dumps all 500 lines of the user's SQL code into the `alert.log` _before_ printing the actual `ORA-` error code.
**Why we fail:** The agent chunks 50 lines of useless SQL table names into "Chunk A", and the actual error code gets pushed into "Chunk K". Because the SQL text dominates the chunk, BM25 fails to find the infrastructure keywords. The incident gets fragmented.
**Fix Required:** The agent must implement a rule to **detect and truncate/summarize user SQL text blocks** from alert logs before chunking, ensuring the actual diagnostic codes remain in the same chunk.

## 30. Concurrency Rules Edge Case: The "Coincidental Outage"

**The Flaw:** The Temporal Proximity rule automatically links any errors happening within 60 seconds of each other.
**The Edge Case:** By pure, horrible coincidence, at exactly 03:00 AM the Storage SAN crashes (`ORA-27072`), and at 03:00:05 AM a developer runs a bad script that drops a critical application table (`ORA-00942`).
**Why we fail:** Because they happened within 60 seconds, the agent forcefully links them. It hallucinates an impossible causal chain: _"The SAN failure caused the missing table."_
**Fix Required:** The Causal Graph Engine needs a strict **"Independent Layer Rule."** It must recognize that a physical I/O error cannot mathematically cause a logical DDL table drop, preventing the linking of unrelated coincidental outages.

## 31. Archiving Rules Edge Case: The "Desynced Reality"

**The Flaw:** The agent relies on OS commands (`df -h`) to verify storage health.
**The Edge Case:** The database hangs because the Fast Recovery Area (FRA) is 100% full. A panicked DBA bypasses Oracle RMAN and manually deletes 500GB of archive logs directly from the Linux OS using `rm -rf /u01/app/oracle/fast_recovery_area/*`.
**Why we fail:** The Linux OS `df -h` command now shows the disk is 80% free. The OS is happy. But Oracle's internal control file still _thinks_ the FRA is 100% full and keeps the database hung. The agent checks OS storage, sees plenty of free space, and misdiagnoses the hang because OS reality and Oracle's internal state are completely desynced.
**Fix Required:** Whenever the agent diagnoses an Archiver hang, it must cross-reference the OS `df -h` output with an explicit query to `v$recovery_file_dest` or `v$archive_dest`. If the two disagree, the agent must output an RMAN `crosscheck` runbook.

---

## 32. UI/Input Edge Case: The "Command + Result" Conversational Input

**The Flaw:** The BM25 Vector Engine is heavily optimized to parse system-generated logs (like `/var/log/messages` or `alert.log`), not human conversational text mixed with bash commands.
**The Edge Case:** The user manually runs a Linux command or an Oracle utility (`sqlplus`, `asmcmd`, `e2fsck`, `multipath -ll`) and pastes the command _along with_ the error output into the chat (e.g., _"I just ran `e2fsck -y /dev/sdb` and I am getting `Device or resource busy`"_).
**Why we fail:** BM25 uses term frequency. If the user types `e2fsck`, the search engine will try to find the word `e2fsck` in our seed database. Because our seeds are mostly raw error logs (which rarely contain the literal names of the commands used to fix them), the BM25 score gets polluted by the command name. The search engine gets confused by the Linux syntax and fails to weigh the actual error (`Device or resource busy`) highly enough, returning a low-confidence hallucination.
**Fix Required:** The agent must implement an **"Intent vs. Output" Pre-Processor**. Before sending the user's text to the BM25 search engine, it must use an NLP classifier to strip out shell syntax (e.g., things starting with `$`, `#`, or known binaries like `asmcmd`). It must isolate the _Actual Error String_ to send to the vector search, while keeping the _Command Used_ as secondary context for the final runbook generation.

---

## 33. Knowledge Base Edge Case: "OS Command Polymorphism" (Cross-Platform Translation)

**The Flaw:** If the RAG database stores runbooks as static text strings, it will blindly return Linux commands (e.g., `systemctl restart iscsid` or `multipath -ll`) even if the user uploaded an AIX or Solaris log.
**The Edge Case:** A user uploads a Solaris `/var/adm/messages` log showing a storage failure. The agent correctly diagnoses a "Multipath Drop." However, the chatbot tells the Solaris admin to run `multipath -ll` (a Linux-only command). The Solaris admin is confused because the command doesn't exist on their server, undermining trust in the agent.
**Fix Required:** The agent must decouple the _Diagnosis_ from the _Remediation_.

1. **Pre-Flight OS Fingerprinting:** The log ingestion pipeline must tag the session with the detected OS (`OS=AIX`, `OS=SOLARIS`, `OS=LINUX`).
2. **Polymorphic Runbooks:** The `errors.jsonl` seed database must store runbooks as JSON objects mapping to specific operating systems, rather than flat strings.
3. **Dynamic Routing:** When generating the output, the chatbot must query the session's OS tag and dynamically inject the correct platform-specific command (e.g., outputting `lspath` for AIX, `mpathadm` for Solaris, or `multipath -ll` for Linux) for the exact same root cause.
