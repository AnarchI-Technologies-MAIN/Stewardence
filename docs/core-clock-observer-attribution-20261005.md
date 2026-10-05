# Approved observer attribution review — 2026-10-05

Source receipts: `evidence/clock-observer/20261005-approved-successor/{summary,events,clock}.json[l]`. This lane performed only subsequent read-only correlation/process metadata inspection; it did not execute another observer, change clocks/services, or create containers.

The root-executed approved observer recorded 90.03659385 RAW seconds, 97 parsed events, 644 clock samples, no output cap and zero reported per-CPU loss counters. Cleanup reported private instance, probe event and descriptor absent, with matching global configuration hashes. These receipts qualify that bounded observation, not production time stability.

## Exact event identity and residual correlation

Six negative REALTIME-minus-RAW residual jumps above 50ms form three pairs:

| RAW sample interval | Residual change | Nearby admitted event |
|---|---:|---|
| 453753.177098–453753.288809 | −0.785688s | `do_settimeofday64` at453753.287785, initd PID3570, caller `do_sys_settimeofday64` |
| 453753.288809–453753.399559 | −1.181604s | `do_adjtimex_modes` at453753.398973, PID14275, modes8476 |
| 453781.181674–453781.315723 | −0.792275s | `do_settimeofday64` at453781.315313, initd PID3570, same caller |
| 453781.315723–453781.418386 | −1.187458s | `do_adjtimex_modes` at453781.417959, systemd-timesyn PID14275, modes8476 |
| 453809.363233–453809.497621 | −0.721201s | `do_settimeofday64` at453809.401478, comm `<...>`, PID3567, same caller |
| 453809.497621–453809.625320 | −1.186012s | `do_adjtimex_modes` at453809.528201, systemd-timesyn PID14275, modes8476 |

Do not describe all three set events as PID3570: the third is PID3567. The other recurring adjustment actor in the actual receipt is chronyd PID140, not PID14047. Its observed modes include28 and16386. Local Ubuntu chronyd392/406 is separately observed with no CAP_SYS_TIME; matching a daemon name does not establish identical process identity.

Modes8476 includes ADJ_SETOFFSET(256), ADJ_NANO(8192), and28. It is a mutating request at the verified kernel timex boundary, distinct from modes0 observation. Function-entry evidence plus a coincident residual step strongly supports adjustment execution; this scope did not collect the timex offset value or return value at the kernel function. Do not infer the requested numeric offset or successful return merely from entry.

[Primary upstream Linux source](https://raw.githubusercontent.com/torvalds/linux/master/kernel/time/posix-timers.c) binds `posix_clock_realtime_adj` to CLOCK_REALTIME and calls `do_adjtimex`. The locally recorded caller therefore supports system-realtime adjustment rather than attributing these events to a PHC solely from the actor's name. Upstream establishes mechanism, not exact installed execution beyond the recorded symbol.

## Read-only namespace/process identity limits

Exact `/proc` lookup of3570/3567/14275/140 did not match in the ordinary Ubuntu, Mail and superagent process views;3570 was also absent from docker-desktop. These are namespace-scoped observations, not evidence that the traced tasks ceased to exist.

Docker-desktop has visible `initd` processes40 and60 with executable `/initd`, cgroup `/non-systemd`, parent39/40 and PID namespace4026532324. Their NSpid pairs are40→1 and60→21; process60 had44 visible tasks. The inspection shell's PID namespace was4026532259. These are a plausible identity family, not a proven mapping of traced3570/3567 to those tasks. AnarchI-Mail has visible systemd-timesyn109277 with CAP_SYS_TIME; exact correspondence with tracePID14275 remains unproven. No process environment or arbitrary arguments were read.

Read-only Docker container name/PID metadata showed the currently running LocalAI, visual qualification app/database and stockpile database. None had top-level PID3570/3567. Thread/namespace ancestry was not exhaustively resolved; do not conclude the setter is outside every container from that list.

## Confidence and next narrow step

The source of backward steps is no longer wholly unobserved: a userspace settimeofday path and a separate modes8476 system-realtime adjustment path are directly recorded adjacent to the three paired discontinuities. Strong temporal/path attribution is justified; exact responsible distro/service ownership and the root configuration causing repeated corrections remain open. These receipts do not prove Windows calibration caused them.

Next use supported read-only namespace identity mapping to connect initial-kernel traced task IDs to visible namespace task IDs, recording only task names/PIDs, parent/namespace identity and executable path. Resolve `/initd` ownership/version through Docker Desktop's documented diagnostics before considering a controller change. Any fresh observer or controller intervention needs separately coordinated scope; never stop `/initd`, Docker, Mail or clock controllers from these correlations alone. Preserve future-time guards and the prior controlled Mail-stop evidence, which showed recurring steps despite Mail being stopped.
