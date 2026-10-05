"""REVIEW ONLY until authorized: bounded shared-kernel tracefs instrumentation.

Run inside Ubuntu WSL as root after explicit approval. No installs, clock setters,
service changes or global trace-buffer reads. Only created resources are removed.
"""

import argparse
import hashlib
import json
import os
import platform
import re
import selectors
import struct
import time
import uuid
from pathlib import Path

DURATION_SECONDS = 90
MAX_RECORDS = 10_000
MAX_OUTPUT_BYTES = 2 * 1024 * 1024
MAX_BTF_BYTES = 32 * 1024 * 1024
SYSCALLS = ("clock_settime", "settimeofday", "adjtimex", "clock_adjtime")
FUNCTIONS = ("do_settimeofday64", "do_adjtimex")
TRACE_ROOT = Path("/sys/kernel/tracing")
LINE = re.compile(
    r"^\s*(?P<comm>.{1,16})-(?P<pid>\d+)\s+\[\d+\].*?"
    r"\s(?P<timestamp>\d+\.\d+):\s*(?P<message>.*)$"
)


def read_bounded(path, limit=MAX_BTF_BYTES):
    with path.open("rb") as stream:
        value = stream.read(limit + 1)
    if len(value) > limit:
        raise RuntimeError("Preflight input exceeds bounded size")
    return value


def write_probe_command(path, command):
    """One tracefs command, no truncation/append flag and no seeking.

    Unlike ordinary append streams, this control file interprets writes as
    commands. Never clear it or retry a partial command as a second command.
    """
    payload = command.encode("ascii")
    if not payload or len(payload) > 1024 or not payload.endswith(b"\n"):
        raise ValueError("Probe command must be a bounded newline-terminated command")
    if b"\n" in payload[:-1]:
        raise ValueError("Only one probe command is admitted per write")
    descriptor = os.open(path, os.O_WRONLY)
    try:
        if os.write(descriptor, payload) != len(payload):
            raise OSError("Partial tracefs command write; inspect exact owned resource")
    finally:
        os.close(descriptor)


def global_state():
    """Hash configuration only; never consume any existing trace contents."""
    files = [
        TRACE_ROOT / "tracing_on",
        TRACE_ROOT / "current_tracer",
        TRACE_ROOT / "trace_clock",
        TRACE_ROOT / "kprobe_events",
    ]
    files.extend(sorted((TRACE_ROOT / "events").glob("*/*/enable")))
    if len(files) > 8192:
        raise RuntimeError("Too many global event controls for bounded preflight")
    digest = hashlib.sha256()
    for path in files:
        digest.update(str(path.relative_to(TRACE_ROOT)).encode())
        digest.update(read_bounded(path, 2 * 1024 * 1024))
    return digest.hexdigest()


def verified_timex_modes_offset():
    """Verify installed BTF before dereferencing a kernel timex argument.

    Return None when exact do_adjtimex(pointer-to-struct) / unsigned32 modes at
    offset zero cannot be established. Never dereference userspace pointers.
    """
    try:
        data = read_bounded(Path("/sys/kernel/btf/vmlinux"))
        magic, version, flags, header, off, length, soff, slength = struct.unpack_from(
            "<HBBIIIII", data
        )
        if magic != 0xEB9F or version != 1 or flags != 0:
            return None
        strings = data[header + soff : header + soff + slength]
        end = header + off + length
        position = header + off
        if end > len(data) or header + soff + slength > len(data):
            return None

        def name(index):
            if index >= len(strings):
                raise ValueError("Invalid BTF string offset")
            return strings[index : strings.index(b"\0", index)].decode("ascii")

        types = {}
        identifier = 1
        while position < end:
            noff, info, target = struct.unpack_from("<III", data, position)
            kind, count = (info >> 24) & 31, info & 65535
            position += 12
            sizes = {
                1: 4,
                2: 0,
                3: 12,
                4: count * 12,
                5: count * 12,
                6: count * 8,
                7: 0,
                8: 0,
                9: 0,
                10: 0,
                11: 0,
                12: 0,
                13: count * 8,
                14: 4,
                15: count * 12,
                16: 0,
                17: 4,
                18: 0,
                19: count * 12,
            }
            size = sizes.get(kind)
            if size is None or position + size > end or identifier > 500_000:
                return None
            extra = data[position : position + size]
            types[identifier] = (kind, name(noff), target, count, extra)
            position += size
            identifier += 1

        def resolve(identifier):
            for _ in range(16):
                item = types[identifier]
                if item[0] not in (8, 9, 10, 11, 18):
                    return item
                identifier = item[2]
            raise ValueError("BTF qualifier cycle")

        functions = [item for item in types.values() if item[:2] == (12, "do_adjtimex")]
        if len(functions) != 1:
            return None
        prototype = resolve(functions[0][2])
        if prototype[0] != 13 or prototype[3] != 1:
            return None
        _, parameter = struct.unpack_from("<II", prototype[4])
        pointer = resolve(parameter)
        if pointer[0] != 2:
            return None
        timex = resolve(pointer[2])
        if timex[0] != 4 or timex[1] not in ("timex", "__kernel_timex"):
            return None
        for index in range(timex[3]):
            noff, field_type, bits = struct.unpack_from("<III", timex[4], index * 12)
            if name(noff) == "modes":
                integer = resolve(field_type)
                encoding = struct.unpack_from("<I", integer[4])[0]
                if integer[0] == 1 and integer[2] == 4 and bits == 0 and encoding == 32:
                    return 0
        return None
    except (OSError, ValueError, KeyError, struct.error, UnicodeError):
        return None


def parsed_event(line):
    match = LINE.match(line)
    if match is None:
        return None
    message = match["message"]
    event = re.match(r"(?:syscalls:)?sys_(enter|exit)_(\w+):", message)
    record = {
        "comm": match["comm"].strip(),
        "pid": int(match["pid"]),
        "trace_timestamp": match["timestamp"],
    }
    if event and event[2] in SYSCALLS:
        record["event"] = f"sys_{event[1]}_{event[2]}"
        if event[1] == "exit":
            result = re.search(r"\bret=(-?\d+)", message)
            hexadecimal = re.search(r":\s*0x([0-9a-fA-F]{1,16})\s*$", message)
            value = None
            if result:
                value = int(result[1])
            if hexadecimal:
                value = int(hexadecimal[1], 16)
                if value >= 2**63:
                    value -= 2**64
            record["result_class"] = (
                "success" if value is not None and value >= 0 else "failure_or_unknown"
            )
        return record
    modes = re.search(r"\bmodes=(0x[0-9a-fA-F]+|\d+)\b", message)
    if message.startswith("timex_modes:") and modes:
        value = int(modes[1], 16 if modes[1].startswith("0x") else 10)
        return record | {"event": "do_adjtimex_modes", "modes": value}
    function = re.match(r"(do_settimeofday64|do_adjtimex)\s+<-([\w.$]+)", message)
    if function:
        return record | {"event": function[1], "caller_symbol": function[2]}
    return None


def observe(output):
    if os.geteuid() != 0 or platform.machine() != "x86_64":
        raise RuntimeError("Requires explicitly authorized root x86-64 WSL execution")
    if (os.cpu_count() or 1) > 256:
        raise RuntimeError("CPU count exceeds bounded trace-buffer plan")
    output.mkdir(parents=True, exist_ok=False)
    before = global_state()
    name = "steward_clock_" + uuid.uuid4().hex
    instance = TRACE_ROOT / "instances" / name
    group = name
    probe_created = False
    instance_created = False
    summary = {"schema": "anarchi.clock.observer.v1", "global_before_sha256": before}
    ownership = {
        "schema": "anarchi.clock.observer.resources.v1",
        "instance_name": name,
        "probe_group": group,
        "planned_probe_name": "timex_modes",
        "global_before_sha256": before,
    }
    # Public exact ownership evidence survives abrupt termination. No pointer,
    # trace contents, credential or arbitrary process argument is persisted.
    with (output / "ownership.json").open("x", encoding="utf-8") as manifest:
        json.dump(ownership, manifest, indent=2)
        manifest.write("\n")
        manifest.flush()
        os.fsync(manifest.fileno())

    def write(path, value):
        path.write_text(value, encoding="ascii")

    try:
        instance.mkdir()
        instance_created = True
        write(instance / "tracing_on", "0")
        write(instance / "buffer_size_kb", "16")
        write(instance / "trace_clock", "mono_raw")
        available = read_bounded(TRACE_ROOT / "available_filter_functions").decode()
        names = {line.split()[0] for line in available.splitlines() if line.split()}
        if not set(FUNCTIONS) <= names:
            raise RuntimeError("Exact narrow function targets unavailable")
        write(instance / "set_ftrace_filter", "\n".join(FUNCTIONS))
        write(instance / "current_tracer", "function")
        for syscall in SYSCALLS:
            for direction in ("enter", "exit"):
                write(
                    instance
                    / "events"
                    / "syscalls"
                    / f"sys_{direction}_{syscall}"
                    / "enable",
                    "1",
                )
        offset = verified_timex_modes_offset()
        summary["timex_modes_verified"] = offset == 0
        if offset == 0:
            # Verified kernel pointer argument only; no syscall user-memory fetch.
            write_probe_command(
                TRACE_ROOT / "kprobe_events",
                f"p:{group}/timex_modes do_adjtimex modes=+0($arg1):u32\n",
            )
            probe_created = True
            write(instance / "events" / group / "timex_modes" / "enable", "1")

        with (
            (instance / "trace_pipe").open("rb", buffering=0) as pipe,
            (output / "events.jsonl").open("xb") as events,
            (output / "clock.jsonl").open("xb") as clocks,
            selectors.DefaultSelector() as selector,
        ):
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ)
            write(instance / "tracing_on", "1")
            start = time.clock_gettime(time.CLOCK_MONOTONIC_RAW)
            pending = b""
            records = written = samples = 0
            capped = False
            next_sample = start
            while (
                time.clock_gettime(time.CLOCK_MONOTONIC_RAW) - start < DURATION_SECONDS
            ):
                now = time.clock_gettime(time.CLOCK_MONOTONIC_RAW)
                if now >= next_sample and samples < 1000:
                    sample = {
                        "raw": now,
                        "realtime": time.time(),
                        "monotonic": time.monotonic(),
                    }
                    clocks.write((json.dumps(sample) + "\n").encode())
                    samples += 1
                    next_sample = now + 0.1
                for key, _ in selector.select(timeout=0.05):
                    block = os.read(key.fd, 65536)
                    pending += block
                    while b"\n" in pending:
                        line, pending = pending.split(b"\n", 1)
                        record = parsed_event(line.decode("utf-8", "replace"))
                        if record is None:
                            continue
                        encoded = (
                            json.dumps(record, ensure_ascii=True) + "\n"
                        ).encode()
                        if (
                            records >= MAX_RECORDS
                            or written + len(encoded) > MAX_OUTPUT_BYTES
                        ):
                            capped = True
                            break
                        events.write(encoded)
                        records += 1
                        written += len(encoded)
                    if capped or len(pending) > 65536:
                        capped = True
                        break
                if capped:
                    break
            summary.update(
                duration_raw_seconds=time.clock_gettime(time.CLOCK_MONOTONIC_RAW)
                - start,
                events=records,
                bytes=written,
                clock_samples=samples,
                capped=capped,
            )
        write(instance / "tracing_on", "0")
        losses = []
        for stats in sorted((instance / "per_cpu").glob("cpu*/stats")):
            for line in stats.read_text().splitlines():
                if line.startswith(("overrun:", "commit overrun:", "dropped events:")):
                    losses.append(
                        {
                            "cpu": stats.parent.name,
                            "counter": line.split(":")[0],
                            "value": int(line.split(":")[1].strip()),
                        }
                    )
        summary["loss_counters"] = losses
    finally:
        cleanup_errors = []
        if instance_created and instance.exists():
            try:
                write(instance / "tracing_on", "0")
                instance.rmdir()
            except OSError as error:
                cleanup_errors.append(type(error).__name__)
        if probe_created or (TRACE_ROOT / "events" / group / "timex_modes").exists():
            try:
                write_probe_command(
                    TRACE_ROOT / "kprobe_events", f"-:{group}/timex_modes\n"
                )
            except OSError as error:
                cleanup_errors.append(type(error).__name__)
        summary["cleanup_errors"] = cleanup_errors
        summary["private_instance_absent"] = not instance.exists()
        summary["owned_probe_event_absent"] = not (
            TRACE_ROOT / "events" / group / "timex_modes"
        ).exists()
        descriptors = read_bounded(
            TRACE_ROOT / "kprobe_events", 2 * 1024 * 1024
        ).decode("ascii")
        summary["owned_probe_descriptor_absent"] = (
            re.search(
                rf"^[pr](?:\d+)?:{re.escape(group)}/timex_modes(?:\s|$)",
                descriptors,
                re.MULTILINE,
            )
            is None
        )
        summary["global_after_sha256"] = global_state()
        summary["global_state_unchanged"] = summary["global_after_sha256"] == before
        (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    if (
        cleanup_errors
        or not summary["private_instance_absent"]
        or not summary["owned_probe_event_absent"]
        or not summary["owned_probe_descriptor_absent"]
        or not summary["global_state_unchanged"]
    ):
        raise RuntimeError("Observer cleanup/state verification needs explicit review")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--authorized-shared-kernel-observer", action="store_true")
    arguments = parser.parse_args()
    if not arguments.authorized_shared_kernel_observer:
        parser.error("Explicit shared-kernel instrumentation approval is required")
    observe(arguments.output)
