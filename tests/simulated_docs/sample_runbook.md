# Exadata Database Machine: Critical Error Runbook v4.2
Date: 2024-03-15
Author: Oracle Advanced Customer Services

## Overview
This document contains the official resolution paths for critical Oracle database and Exadata storage cell errors. **Under no circumstances should DBA personnel deviate from these action plans.** If an error is not listed here, escalate to Oracle Support immediately.

## Storage and Memory Errors

The following table maps the exact ORA-CODE to the authorized action plan.

| Error Code | Observed Symptoms | Official Authorized Resolution |
| :--- | :--- | :--- |
| ORA-00603 | Oracle server session terminated by fatal error. Usually preceded by LGWR or control file IO issues. | 1. Check `/var/log/messages` for disk timeouts. <br> 2. Restart the instance using `srvctl stop instance -d orcl -i orcl1 -o abort`. <br> 3. Verify ASM disk group health. |
| ORA-27072 | File I/O error. The OS failed to read or write to the specified block. | 1. Execute `iostat -x 1` to confirm SCSI timeout. <br> 2. If `%util=100`, failover the storage cell. <br> 3. Do NOT drop the datafile. |
| ORA-04031 | Unable to allocate bytes of shared memory. Shared pool fragmentation. | 1. Flush the shared pool using `ALTER SYSTEM FLUSH SHARED_POOL`. <br> 2. Increase `SGA_TARGET` by 10%. <br> 3. Check for hard-parsing SQL spikes. |
| ORA-29740 | Evicted by member, node eviction. Clusterware split-brain scenario. | 1. Check `cssd.log` for missed network heartbeats. <br> 2. Do not manually restart; wait for clusterware automatic reboot. <br> 3. Check interconnect switch logs. |

## Important Notice
Always verify the OS platform before executing any bash scripts mentioned above. Windows environments require equivalent PowerShell cmdlets.
