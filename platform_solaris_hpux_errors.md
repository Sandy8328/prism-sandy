# Solaris + HP-UX Platform — Critical Error Logs
## 20 Authentic Solaris / HP-UX Oracle DBA Errors
## Temperature: 0.0 | Real log formats

---

## SOLARIS-01: SCSI DISK FAULT (FMA — Fault Management Architecture)

**ORA Code: ORA-27072**

```
# fmadm faulty output — Solaris hardware fault manager
---------------------------------------------------------------------------
 TIME                 UUID                                 MSG-ID
Apr 21 03:14:18 2024 8b2f21a8-4c7e-82b1-f821-00144f821821 DISK-8003-0F

Affect       fmri
             dev:///dev/dsk/c0t50050768018182D3d0

Problem in:  hc:///:chassis-id=500508B3000082B1:server-id=dbhost01/
             pciexrc=1/pciexbus=1/pciexdev=0/pciexfn=0/
             pciexbus=2/pciexdev=0/pciexfn=0/disk=0

Suspect 1 of 1: disk (certainty 100%, uuid 8b2f21a8...)
       Problem class: fault.io.scsi.cmd.disk.dev.rqs.norecover
       FRU:           "SEAGATE ST3600057SS" SN: 9XG0JKZT

Fault enabled,  faulty,  repaired=no, replaced=no

# fmdump -e output
Apr 21 03:14:17.821 ereport.io.scsi.cmd.disk.dev.rqs.norecover
                    detector = dev:///devices/pci@0,0/pci@0/disk@0
                    class    = ereport.io.scsi.cmd.disk.dev.rqs.norecover
```

**Oracle alert.log:**
```
Mon Apr 21 03:14:18 2024
ORA-27072: File I/O error
Solaris-AMD64 Error: 5: I/O error
Additional information: 4
Additional information: 0
```

---

## SOLARIS-02: ZFS POOL I/O ERROR

**ORA Code: ORA-27072**

```
# /var/adm/messages on Solaris
Apr 21 03:14:18 dbhost01 zfs: [ID 977671 kern.notice] NOTICE: ZFS: I/O error -
       pool=orapool vdev=/dev/dsk/c0t1d0 offset=8192 size=8192 error=5
Apr 21 03:14:18 dbhost01 scsi: [ID 107833 kern.warning] WARNING: /pci@0,0/
       pci1000,3060@0/sd@0,0 (sd0): Error for Command: read(10)
       Error Level: Fatal
       Sense Key: Hardware Error
       Vendor 'SEAGATE': ASC: 0x44 (internal target failure), ASCQ: 0x0

# zpool status showing degraded pool
# zpool status orapool
  pool: orapool
 state: DEGRADED
status: One or more devices has been removed by the administrator.
  scan: scrub repaired 0B in 00:00:01 with 0 errors on ...
config:
	NAME        STATE     READ WRITE CKSUM
	orapool     DEGRADED     0     0     0
	  mirror-0  DEGRADED     0     0     0
	    c0t0d0  ONLINE       0     0     0
	    c0t1d0  FAULTED      8     0     0  ← disk faulted, 8 read errors
```

---

## SOLARIS-03: ZFS FILESYSTEM FULL

**ORA Code: ORA-00257**

```
# Solaris df output (different from Linux)
# df -h /arch
Filesystem      Size  Used Avail Use% Mounted on
orapool/arch    200G  200G     0 100% /arch

# /var/adm/messages
Apr 21 03:14:18 dbhost01 zfs: [ID 855088 kern.err] NOTICE: ZFS: No space left
       pool=orapool fs=orapool/arch

# Oracle alert.log
Mon Apr 21 03:14:18 2024
ARC3: Archival stopped, error occurred. Will continue retrying
ORA-16038: log 2 sequence# 18821 cannot be archived
ORA-00257: archiver error. Connect internal only, until freed.
Solaris-AMD64 Error: 28: No space left on device
```

---

## SOLARIS-04: SHARED MEMORY FAILURE (Solaris-specific limits)

**ORA Code: ORA-27102**

```
# Oracle startup failure on Solaris
Mon Apr 21 03:14:18 2024
Starting ORACLE instance (normal)
ORA-27102: out of memory
Solaris-AMD64 Error: 12: Not enough memory
Additional information: 18821

# Solaris shared memory config (project-based, not sysctl-based like Linux)
# prctl -n project.max-shm-memory -i project group.dba
project: 3: group.dba
NAME    PRIVILEGE       VALUE    FLAG   ACTION                        RECIPIENT
project.max-shm-memory
        privileged      16.0GB   -      deny                          -
# Oracle SGA = 96GB > project.max-shm-memory = 16GB → FAIL

# Fix (Solaris-specific):
# projmod -sK "project.max-shm-memory=(privileged,128g,deny)" group.dba
```

---

## SOLARIS-05: MPXIO PATH FAILURE (Solaris Multipath)

**ORA Code: ORA-15080**

```
# /var/adm/messages showing MPXIO path failure
Apr 21 03:14:17 dbhost01 scsi_vhci: [ID 821232 kern.err] 
       /scsi_vhci/disk@g600508b3000082b10000900000760000: path 
       /pci@0,0/pci8086,340a@2/pci1000,3060@0/sd@0 is now OFFLINE

Apr 21 03:14:17 dbhost01 scsi_vhci: remaining paths: 0
       Class: err, Subclass: none
       Replacing device with error device node

# mpathadm showing failed paths
# mpathadm show initiator-port
Initiator Port Name: iqn.1986-03.com.sun:01:001a4b821821
    Transport Type: iSCSI
    OS Device File: /dev/iscsi/0
  Path:
    State: Error
    Logical Unit: /dev/rdsk/c4t600508B3000082B1d0

# Oracle alert.log
Mon Apr 21 03:14:18 2024
ORA-15080: synchronous I/O request to a disk failed
Solaris-AMD64 Error: 5: I/O error
ORA-15081: failed to submit an I/O operation to a disk
```

---

## SOLARIS-06: SOLARIS ZONE RESOURCE LIMIT HIT

**ORA Code: ORA-27102 / ORA-04031**

```
# Oracle runs inside Solaris Zone — zone memory capped
# /var/adm/messages in global zone
Apr 21 03:14:18 dbhost01 vm_usage: Zone 'orazone' exceeded physical memory cap
       usage=96GB cap=80GB

# Inside the zone, Oracle sees:
ORA-27102: out of memory
Solaris-AMD64 Error: 12: Not enough memory

# Check zone config
# zonecfg -z orazone info capped-memory
capped-memory:
   physical: 80g       ← hard cap 80GB, but Oracle needs 96GB
   locked: 80g
   swap: 160g

# No equivalent of this on Linux (cgroups equivalent but different implementation)
```

---

## SOLARIS-07: NIC FAILURE ON SOLARIS (DLPI Driver)

**ORA Code: ORA-03113**

```
# /var/adm/messages
Apr 21 03:14:17 dbhost01 nxge: [ID 752849 kern.err] nxge0: link is down
Apr 21 03:14:17 dbhost01 nxge: [ID 752849 kern.info] nxge0: 0-Mbps link up

# Solaris ipmpstat (IP Multipathing — equivalent of Linux bonding)
# ipmpstat -g
GROUP       GROUPNAME  STATE    FDT         INTERFACES
ip0         ipmp0      ok       --          nxge0 nxge1

# After NIC failure:
# ipmpstat -g
GROUP       GROUPNAME  STATE    FDT         INTERFACES
ip0         ipmp0      degraded --          nxge0(inactive) nxge1(active)

# netstat -i showing errors
Name  Mtu  Net/Dest      Address    Ipkts Ierrs Opkts Oerrs Collis Queue
nxge0 1500 192.168.1.0   192.168.1.1 18821 1821  18200    12      0  182
```

---

## SOLARIS-08: SOLARIS PROCESS KILLED BY MEMORY PRESSURE (rcapd)

**ORA Code: ORA-00603**

```
# /var/adm/messages — Solaris resource cap daemon kills Oracle
Apr 21 03:14:18 dbhost01 rcapd[821]: killing oracle (pid 18821) for exceeding
       rss cap of 80GB (current rss = 96GB)

# Solaris rcapd (Resource CAP Daemon) equivalent of Linux cgroup OOM killer
# prctl -n zone.max-rss -i zone orazone
zone: 34: orazone
NAME    PRIVILEGE       VALUE    FLAG   ACTION
zone.max-rss
        priv            80.0GB   -      deny

# Oracle alert.log
Mon Apr 21 03:14:19 2024
ORA-00603: ORACLE server session terminated by fatal error
ORA-00600: internal error code, arguments: [ksmgprem1], ...
PMON: terminating instance due to error 603
```

---

## SOLARIS-09: SWAP EXHAUSTION ON SOLARIS

**ORA Code: ORA-04031 (indirect)**

```
# Solaris swap is different from Linux swap
# swap -l
swapfile             dev   swaplo blocks   free
/dev/zvol/dsk/rpool/swap 256,2       8 16777208 0  ← 0 free blocks

# /var/adm/messages
Apr 21 03:14:18 dbhost01 unix: [ID 479303 kern.warning] WARNING: 
       /usr/kernel/drv/sd: out of swap space

# Oracle alert.log
Mon Apr 21 03:14:18 2024
WARNING: Shared memory is running low (96% used)
ORA-04031: unable to allocate 65560 bytes of shared memory
("shared pool","unknown object","sga heap(1,0)","free memory")
```

---

## SOLARIS-10: SOLARIS FC HBA ERROR (qla2xxx Solaris equivalent)

**ORA Code: ORA-27072**

```
# /var/adm/messages
Apr 21 03:14:16 dbhost01 qlc: [ID 201814 kern.warning] qlc(0): LOOP DOWN
Apr 21 03:14:16 dbhost01 qlc: [ID 201814 kern.err] qlc(0): Loop or point to
       point connection lost. Login procedure started.
Apr 21 03:14:17 dbhost01 qlc: [ID 201814 kern.info] qlc(0): Loop Init LIPA Complete.
Apr 21 03:14:18 dbhost01 scsi: [ID 107833 kern.err] /pci@0,0/SUNW,qlc@5/fp@0,0/
       ssd@w50050768018182D3,0 (ssd0): Error for Command: write(10) Error Level: Fatal

# Oracle alert.log
Mon Apr 21 03:14:19 2024
ORA-27072: File I/O error
Solaris-AMD64 Error: 5: I/O error
Additional information: 4
```

---

## HP-UX-01: DISK I/O ERROR (HP-UX SCSI)

**ORA Code: ORA-27072**

```
# /var/adm/syslog/syslog.log on HP-UX
Apr 21 03:14:18 dbhost01 vmunix: SCSI Error - dev: b 31 0x820000
       CMD: 0x2a STATUS: 0x2 KEY: 0x3 ASC: 0x11 ASCQ: 0x0
       MSG: I/O ERROR - disk failure

# HP-UX disk naming: /dev/disk/disk3, /dev/rdisk/disk3
# ioscan -fnC disk
Class       I  H/W Path       Driver  S/W State   H/W Type     Description
=====================================================================
disk        3  0/2/1/0.6.0    sdisk   CLAIMED     DEVICE       HP 146 GMAP3

# diskinfo /dev/rdisk/disk3
SCSI describe of /dev/rdisk/disk3:
                vendor:   HP
                product id: 146 GMAP3
                type: Direct-Access
                status: NOT READY   ← disk not ready

# Oracle alert.log
Mon Apr 21 03:14:18 2024
ORA-27072: File I/O error
HP-UX Error: 5: I/O error
Additional information: 4
```

---

## HP-UX-02: ORACLE MEMORY ALLOCATION FAILURE (HP-UX)

**ORA Code: ORA-27102**

```
# Oracle startup failure on HP-UX
Mon Apr 21 03:14:18 2024
Starting ORACLE instance (normal)
ORA-27102: out of memory
HP-UX Error: 12: Not enough space
Additional information: 18821

# HP-UX kernel parameters for Oracle (set in /stand/system or SAM)
# kctune shmmax
Parameter  Current   Pending   Dynamic  Units
shmmax     17179869184   -     Yes     bytes   ← 16GB, but Oracle needs 96GB

# HP-UX-specific fix:
# kctune shmmax=103079215104   ← set to 96GB
# Reboot required if not dynamic
```

---

## HP-UX-03: HP-UX SERVICE GUARD FAILOVER (Cluster failover)

**ORA Code: ORA-29740 (equivalent event)**

```
# /var/adm/syslog/syslog.log on HP-UX
Apr 21 03:14:18 dbhost01 cmcld[821]: Node dbhost02 failed to respond to heartbeat.
Apr 21 03:14:21 dbhost01 cmcld[821]: Node dbhost02 is being removed from cluster.
Apr 21 03:14:22 dbhost01 cmcld[821]: Cluster reformation starting. New cluster.
Apr 21 03:14:25 dbhost01 cmcld[821]: Package OraclePkg starting on dbhost01.

# HP-UX uses ServiceGuard for HA (not Oracle CRS in traditional setups)
# cmviewcl output after failover
Cluster: ProdCluster
  Status: up

  Node: dbhost01
     Status: up
     Packages:
       OraclePkg    up (running, previously on dbhost02)

  Node: dbhost02
     Status: down   ← failed node
```

---

## HP-UX-04: ORACLE SEMAPHORE FAILURE ON HP-UX

**ORA Code: ORA-27300**

```
Mon Apr 21 03:14:18 2024
ORA-27154: post/wait create failed
ORA-27300: OS system dependent operation:semget failed with status: 28
ORA-27301: OS failure message: No space left on device
ORA-27302: failure occurred at: sskgpsemsper

# HP-UX kernel parameter for semaphores
# kctune | grep sem
semmni    1024                ← max semaphore IDs (often too low for Oracle RAC)
semmns    32768               ← max semaphores
semvmx    32767               ← max semaphore value
semume    100

# Fix:
# kctune semmni=4096
# kctune semmns=65536
```

---

## HP-UX-05: ORACLE FILE I/O ON HP-UX LVM

**ORA Code: ORA-27072**

```
# /var/adm/syslog/syslog.log
Apr 21 03:14:18 dbhost01 vmunix: LVM: dev 64 0x000001 read error
Apr 21 03:14:18 dbhost01 vmunix: I/O error to /dev/vg01/lvol2
Apr 21 03:14:18 dbhost01 vmunix: Physical extent 821 on disk /dev/disk/disk2
       received I/O error, retrying on next mirror copy

# HP-UX LVM mirror status
# vgdisplay -v vg01 | grep PVName
   PVName                     /dev/disk/disk1
   PVName                     /dev/disk/disk2 (stale)  ← one mirror stale

# Oracle alert.log
Mon Apr 21 03:14:19 2024
ORA-27072: File I/O error
HP-UX Error: 5: I/O error
Additional information: 4
Additional information: 0

# Fix: sync the stale mirror
# vgsync vg01
```
