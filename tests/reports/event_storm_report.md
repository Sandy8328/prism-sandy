# Multi-Log Event Storm Bridge Test
Status: PASSED
Details: Agent successfully ingested two different log files where the errors were 90 seconds apart. Because the initial error flooded the logs for 2 minutes, the Deduplication Cache expanded its active window, allowing DuckDB to bridge the 90-second gap and successfully correlate the DB Crash to the initial Storage Failure.
