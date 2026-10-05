"""Fault-inject the isolated qualification cleanup, without real deletions."""
import json
from pathlib import Path
from types import SimpleNamespace
from qualification_cleanup import cleanup_targets

calls = []
network_present = True
def broken_docker(*args, **kwargs):
    global network_present
    calls.append(args)
    if args[:2] == ('rm', '-f') and args[2] == 'first':
        raise RuntimeError('Injected deletion failure')
    if args[:2] == ('network', 'rm'):
        network_present = False
    if args[:3] == ('network', 'ls', '-q'):
        return SimpleNamespace(stdout='a'*64 if network_present else '')
    present = args[:3] == ('container', 'ls', '-aq') and 'name=^/first$' in args
    return SimpleNamespace(stdout='fake-id' if present else '')

result = cleanup_targets(broken_docker, ['first', 'second', 'third'], 'isolated-network')
assert not result['cleanup_passed']
assert 'container-operation:first' in result['failed_targets']
assert 'container-remains:first' in result['failed_targets']
assert all(any('name=^/' + name + '$' in call for call in calls) for name in ['second', 'third'])
assert ('network', 'rm', 'isolated-network') in calls
assert any('name=^isolated-network$' in call for call in calls)
calls.clear()
network_present = True
ambiguous = cleanup_targets(broken_docker, [], 'isolated-network')
assert ambiguous['cleanup_passed']
assert ('network', 'rm', 'isolated-network') in calls
calls.clear()
network_present = True
def foreign_docker(*args, **kwargs):
    if args[:2] == ('network', 'inspect'):
        calls.append(args)
        return SimpleNamespace(stdout=json.dumps({'Name':'isolated-network','Id':'a'*64,
            'Labels':{'stewardence.qualification-run':'another-run'}}))
    return broken_docker(*args, **kwargs)
foreign = cleanup_targets(foreign_docker, [], 'isolated-network', network_owner='this-run')
assert not foreign['cleanup_passed']
assert network_present
assert not any(call[:2] == ('network', 'rm') for call in calls)
receipt = {'qualification_passed': True, 'injected_first_target_failure': True,
           'later_targets_and_network_attempted': True, 'cleanup_success_withheld': True,
           'real_targets_deleted': False, 'result': result}
receipt['ambiguous_network_creation_cleanup'] = ambiguous
receipt['foreign_network_preserved'] = foreign
destination = Path(__file__).resolve().parents[1] / 'evidence/cleanup-failure-qualification.json'
destination.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
print(json.dumps(receipt))
