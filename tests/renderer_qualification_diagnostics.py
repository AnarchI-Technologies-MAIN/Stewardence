"""Optional pytest plugin: observe actual renderer stages without changing limits."""
import json
import os
from pathlib import Path
import sys
import time

import pytest


def resource_snapshot():
    observed = {'process_id': os.getpid()}
    for name in ('memory.current', 'memory.peak', 'memory.events',
                 'pids.current', 'pids.max', 'cpu.stat'):
        path = Path('/sys/fs/cgroup') / name
        try:
            observed[name] = path.read_text()[:2048]
        except OSError:
            observed[name] = 'unavailable'
    try:
        observed['direct_children'] = Path(f'/proc/{os.getpid()}/task/{os.getpid()}/children').read_text()[:2048]
    except OSError:
        observed['direct_children'] = 'unavailable'
    # Only process names/state/parent IDs inside the qualification PID namespace;
    # no command lines or environment values are collected.
    processes = []
    try:
        entries = sorted((entry for entry in Path('/proc').iterdir()
                          if entry.name.isdecimal()), key=lambda entry: int(entry.name))[:64]
        for entry in entries:
            try:
                fields = dict(line.split(':', 1) for line in (entry/'status').read_text().splitlines() if ':' in line)
                processes.append({name: fields[name].strip()
                                  for name in ('Name', 'State', 'Pid', 'PPid')})
            except (OSError, KeyError):
                continue
    except OSError:
        pass
    observed['processes'] = processes
    return observed


@pytest.fixture(autouse=True)
def actual_renderer_stage_diagnostics(request):
    if request.node.name != 'test_actual_chromium_pdf_preserves_unknowns_and_known_cost':
        yield
        return
    record = {'test_id': request.node.nodeid, 'before': resource_snapshot(),
              'stages': [], 'observation_only': True,
              'production_timeout_unchanged': True}
    started = time.monotonic()
    active = {}
    prior = sys.getprofile()
    def profile(frame, event, arg):
        filename = frame.f_code.co_filename.replace('\\', '/')
        name = frame.f_code.co_name
        selected = (
            filename.endswith('/renderer/render.py') and name == 'render_pdf'
            or filename.endswith('/renderer/canonical_pdf.py') and name == 'normalize_generated_pdf'
            or '/playwright/' in filename and filename.endswith('/_generated.py')
            and name in {'launch', 'new_context', 'route', 'new_page', 'set_content', 'pdf', 'close'}
        )
        if selected and event == 'call':
            active[id(frame)] = (name, time.monotonic())
            record['stages'].append({'stage': name, 'event': 'entered',
                                     'elapsed': time.monotonic()-started})
        if selected and event == 'return' and id(frame) in active:
            stage, entered = active.pop(id(frame))
            record['stages'].append({'stage': stage, 'event': 'returned',
                                     'duration': time.monotonic()-entered,
                                     'elapsed': time.monotonic()-started})
        if prior is not None:
            prior(frame, event, arg)
    sys.setprofile(profile)
    try:
        yield
    finally:
        sys.setprofile(prior)
        record['after'] = resource_snapshot()
        record['total_observed_seconds'] = time.monotonic()-started
        encoded = json.dumps(record, sort_keys=True)
        print('RENDERER_STAGE_DIAGNOSTIC ' + encoded)
        directory = Path('/qualification-evidence')
        if directory.is_dir():
            try:
                with (directory/'renderer-stage-diagnostics.jsonl').open('a', encoding='utf-8') as stream:
                    stream.write(encoded+'\n')
            except OSError as error:
                print('RENDERER_DIAGNOSTIC_RECEIPT_ERROR '+type(error).__name__)
