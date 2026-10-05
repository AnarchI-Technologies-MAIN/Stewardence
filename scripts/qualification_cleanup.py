"""Attempt every isolated target; successful deletion alone is not proof."""
import json
import re

def cleanup_targets(docker, containers, network=None, network_owner=None):
    verified, failures = [], []
    for name in containers:
        try:
            present = docker('container', 'ls', '-aq', '--filter', 'name=^/' + name + '$', capture_output=True, text=True).stdout.strip()
            if present:
                docker('rm', '-f', name, capture_output=True, timeout=30)
        except Exception:
            failures.append('container-operation:' + name)
        try:
            remaining = docker('container', 'ls', '-aq', '--filter', 'name=^/' + name + '$', capture_output=True, text=True).stdout.strip()
            if remaining:
                failures.append('container-remains:' + name)
            else:
                verified.append({'target': name, 'absence_verified': True})
        except Exception:
            failures.append('container-verification:' + name)
    if network:
        try:
            present = docker('network', 'ls', '-q', '--no-trunc', '--filter', 'name=^' + network + '$', capture_output=True, text=True).stdout.strip()
            if present:
                removal_target = network
                if network_owner is not None:
                    if not re.fullmatch('[0-9a-f]{64}', present):
                        raise RuntimeError('Network identity is missing or ambiguous')
                    raw = docker('network', 'inspect', '--format', '{{json .}}', present, capture_output=True, text=True).stdout
                    record = json.loads(raw)
                    identity = record.get('Id')
                    if record.get('Name') != network or (record.get('Labels') or {}).get('stewardence.qualification-run') != network_owner or identity != present:
                        raise RuntimeError('Network ownership does not match this qualification')
                    removal_target = identity
                docker('network', 'rm', removal_target, capture_output=True, timeout=30)
        except Exception:
            failures.append('network-operation:' + network)
        try:
            if docker('network', 'ls', '-q', '--filter', 'name=^' + network + '$', capture_output=True, text=True).stdout.strip():
                failures.append('network-remains:' + network)
            else:
                verified.append({'target': network, 'absence_verified': True})
        except Exception:
            failures.append('network-verification:' + network)
    return {'cleanup_passed': not failures, 'verified': verified, 'failed_targets': failures}
