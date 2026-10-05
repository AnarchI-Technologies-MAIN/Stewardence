# Local WSL clock investigation — 2026-10-04

Read-only investigation. No clock settings, services, configuration, tracing, or production systems were changed. This report concerns local qualification infrastructure, not DigitalOcean clock behavior.

## Corrected trial interpretation

The historical trial at `evidence/clock-controller-trial/20261004T211646.399109Z` uses filenames labelled `both_controllers_before` and `both_controllers_restored`. Those labels are inaccurate: Ubuntu's chronyd processes 392 and 406 both run with `-x`. They form a parent/child pair, and both have effective capability mask `0x400`, without CAP_SYS_TIME. `/etc/default/chrony` specifies `SYNC_IN_CONTAINER=no`. They must not be counted as clock controllers. Official [chronyd documentation](https://chrony-project.org/doc/latest/chronyd.html) specifies that `-x` disables system-clock control.

The actual controlled variable was AnarchI-Mail's systemd-timesyncd active → stopped → restored. The transition receipt proves restoration to active. Reported backward-step counts were six before, two while stopped, and three after restoration. The 64-second stopped observation establishes that stopping Mail did not immediately eliminate steps. It does not prove that Mail is uninvolved, or identify the sole steady-state cause.

## Verified local observations

- Ubuntu, AnarchI-Mail, superagent, and docker-desktop expose boot ID `66f516cf-128e-4447-9041-bb77b970ab64`. Inspected Linux time namespaces share the initial time-namespace identity. CLOCK_REALTIME is not virtualized by Linux time namespaces; see the [Linux time_namespaces documentation](https://man7.org/linux/man-pages/man7/time_namespaces.7.html).
- Mail's active systemd-timesyncd PID 108875 had CAP_SYS_TIME (`0x2000000`), and an external NTP source with a 32-second poll interval. Ubuntu's observer pair lacks that capability. Windows W32Time was stopped at inspection; this alone does not exclude WSL/Hyper-V synchronization.
- Ubuntu exposes two listeners on each loopback UDP port 323: inodes 12414/12415 belong to visible chronyd 392; inodes 5332/5333 have no process owner visible in that distro. Two Unix socket entries also exist: `/run/chrony/chronyd.sock` inode 12416 belongs to 392 on filesystem device 0/46; `/var/run/chrony/chronyd.sock` inode 5335 has no visible owner on device 0/26.
- Explicit Unix-socket `chronyc` tracking and sources consistently identified Ubuntu's NTP observer. Consecutive UDP queries to 127.0.0.1 returned NTP tracking and PHC0 sources. With duplicate listeners, those answers cannot safely be paired as one daemon's state. This resolves the apparent tracking/sources contradiction without identifying the hidden daemon.
- The clocksource was `tsc`, PTP clock name `hyperv`, and `hv_utils.timesync_implicit` was `Y`. Kernel version was `6.18.40.1-microsoft-standard-WSL2`. The previously reported adjtimex tick of 10662 was not independently refreshed in this investigation.
- Filtered process inspection in ordinary distros and a capability-dropped, network-disabled Docker host-PID probe did not identify the hidden listener's process. These are scoped namespace observations, not an exhaustive inventory of the WSL utility VM.
- A read-only `wsl --system --exec` process/configuration probe was rejected before its Linux command ran with `WSL_E_GUI_APPLICATIONS_DISABLED`. Existing GUI configuration was left unchanged. No unsupported namespace escape or tracing was attempted.

## Mechanisms versus attribution

The [upstream Hyper-V driver](https://raw.githubusercontent.com/torvalds/linux/master/drivers/hv/hv_util.c) contains an explicit synchronization path that schedules a system-clock update using `do_settimeofday64`. Its implicit path checks whether the guest is at least five seconds behind the host. That implicit forward catch-up condition does not by itself explain the observed approximately one-second backward changes. Explicit host synchronization remains a candidate mechanism; no invocation was captured, and upstream master is not proof of the exact installed build's execution.

A [Microsoft WSL issue](https://github.com/microsoft/WSL/issues/10024) describes an invisible PHC0 chrony responder after stopping a user-distro daemon. This is relevant precedent, not proof of this machine's hidden PID, configuration, capabilities, or behavior. The [WSLg system-distro documentation](https://raw.githubusercontent.com/microsoft/wslg/main/CONTRIBUTING.md) explains that its separate system distro can be inspected; local disabled GUI support prevented the supported access attempt here.

The current evidence supports possible interaction between Mail's capable NTP daemon, a hidden PHC responder, host/kernel synchronization, and accumulated frequency correction. It does not establish which process or kernel path issued any particular observed step. A daemon's monitoring response, capability, or configured correction policy is not an executed clock-adjustment receipt.

## Next bounded reversible test

Repeat only the already-authorized temporary stop of Mail systemd-timesyncd, keeping every other setting/service unchanged. Use at least 384 seconds (six consecutive 64-second windows) while stopped, plus comparable active-before and restored-after windows. A longer interval tests persistence after settlement; six windows is a bounded observation choice, not a theoretical guarantee of steady state.

Record service-state receipts, monotonic-versus-realtime residuals, and read-only adjtimex fields per window. Attribute monitoring queries through the explicit Unix socket; do not merge ambiguous UDP tracking and sources. Put restoration in an unconditional cleanup path and verify active afterward, including on sampling failure or interruption. Preserve failures and the original short trial.

If backward steps continue across all stopped windows, that strengthens evidence against Mail being necessary for their persistence during this interval. If they diminish or disappear, repeat the contrast before asserting causality. Neither outcome identifies the hidden setter. Process-attributed clock-adjustment tracing would require a separately coordinated, bounded instrumentation step; it was not performed here.

No billing, receipt, nonce, or lease tolerance should be widened to accommodate this local infrastructure fault. Production readiness still requires stable qualification infrastructure and exact candidate qualification; this investigation supplies causal limits rather than an authority bypass.


## Extended authorized trial

Evidence `evidence/clock-controller-trial/20261004T213056.326301Z`: four backward jumps in the initial 64-second mail-active window; six consecutive 64-second mail-disabled windows recorded 2, 2, 3, 2, 2 and 2 jumps; three after restoration. Largest observed residual jump was about 1.951 seconds. The script restored only AnarchI-Mail systemd-timesyncd in its finally block. A separate subsequent `systemctl is-active systemd-timesyncd` returned `active`. Mail and LocalAI remained running.

This rejects the hypothesis that stopping this service alone produces a stable shared-kernel clock. It does not identify the remaining setter. HOST-CLOCK-DISCONTINUITY-01 remains open; future-time admission guards remain unchanged. No production configuration was changed.


## Read-only raw-clock discriminator

`evidence/clock-correlation/20261004T215651.136207Z` records repeated journald backward-time rotations, Ubuntu chronyd `-x`, read-only adjtimex tick 10530 us/frequency -3977406, and explicit Unix-socket observer state. Windows w32tm status and peers both report the service not started; no configuration was changed. This is correlation, not process attribution.

`evidence/clock-correlation/20261004T215828.741608Z/raw-rate.json` sampled realtime, CLOCK_MONOTONIC and CLOCK_MONOTONIC_RAW for 64 adjusted-monotonic seconds. Across 1176 samples it observed four backward residual jumps (about0.492–1.029 seconds), while monotonic/raw rate was1.05505264 and realtime/raw rate excluding jumps was1.05507235. The adjusted clocks therefore ran roughly5.5percent faster than RAW in this window. Prior time-discipline tick changes and this rate are compatible with an abnormal frequency correction plus separate wall-time resets; they do not prove which setter/configuration caused either. A stable reference or hardware truth is not inferred from RAW.

Lyra accepted the extended stop trial as bounded negative causal evidence (`evidence/lyra-clock-trial-disposition-20261004.txt`) and recommends read-only correlation before any additional service changes. All admission time guards remain unchanged.

## Later read-only regression correlation and kernel state

[Read-only correlation receipt](../evidence/clock-correlation/read-only-regression-20261004T235015Z.txt) records the subsequent canonical qualification failure at `evidence/20261004T233946.893548Z/qualification.log`, lines 441–442. The request supplied `23:44:09.043330+00:00`; PostgreSQL recorded transaction time `23:44:09.024266+00`. Later Python and PostgreSQL wall-clock samples were approximately `23:44:07.94`, a backward discontinuity of about 1.10 seconds. Only `effective_future` was true; the other eleven identity predicates were false and the PostgreSQL timestamp round trip differed by zero microseconds. The existing admission guard correctly rejected the request. This does not justify subtracting time, changing the assertion, or widening an authority tolerance.

A bounded Ubuntu journald tail independently records backward-time rotation at `23:44:08` and approximately 28-second intervals across `23:42–23:50 UTC`. Exact journal `--since/--until` queries initially returned no entries despite the bounded tail containing entries in that interval; their empty result cannot establish absence here. Windows Kernel-General event 1, Time-Service, and selected Hyper-V operational/admin logs returned explicit `NoMatchingEventsFound` for `23:42–23:46 UTC`. Those missing recorded events do not exclude a host or kernel synchronization path. W32Time remained stopped, Mail systemd-timesyncd remained active, Ubuntu chronyd remained in observer mode `-x`, and `hv_utils.timesync_implicit` remained `Y`. No setter invocation was identified.

[Read-only adjtimex receipt](../evidence/clock-correlation/adjtimex-readonly-20261004T235347Z.json) captures native Linux state at `23:53:47 UTC`. The installed x86-64 header, eight-byte native long, 208-byte `struct timex`, and relevant field offsets were checked before calling `adjtimex` with a zero-initialized `modes=0`. The call returned state 0 and errno 0. Tick was 10,701 microseconds, differing from the earlier 10,530-microsecond observation; scaled frequency was −2,861,060, equivalent to −43.656311 ppm. Offset was zero and status 8192 selected nanosecond mode. The exported USER_HZ was 100. These are observed kernel correction parameters, not attribution to a process or proof of a newly measured current clock rate.

`clock_getres` reported one-nanosecond resolution for REALTIME, MONOTONIC and MONOTONIC_RAW. Resolution does not prove accuracy, rate, or a stable reference. This inspection changed no services, settings, time, capabilities, containers or tracing. The actual setter remains unknown; identifying it would require a separately coordinated process/kernel adjustment trace. HOST-CLOCK-DISCONTINUITY-01 remains open, and production clock behavior was not inspected.
