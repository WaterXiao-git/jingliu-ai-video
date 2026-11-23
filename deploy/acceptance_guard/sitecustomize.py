"""Opt-in network audit for reproducible domestic installation acceptance runs.

Add this directory to PYTHONPATH and set JINGLIU_ACCEPTANCE_AUDIT to a log
directory. The installer also enables it for its Python dependency installation
children. Normal application launches do not load this module.
"""
import ipaddress
import json
import os
from pathlib import Path
import socket
import sys


audit_directory = os.environ.get('JINGLIU_ACCEPTANCE_AUDIT')
if audit_directory:
    directory = Path(audit_directory)
    directory.mkdir(parents=True, exist_ok=True)
    log = directory / f'{os.getpid()}.jsonl'
    spec = json.loads((Path(__file__).resolve().parents[1] / 'deploy-spec.yaml').read_text(encoding='utf-8'))
    allowed_hosts = spec['download_hosts']
    approved_addresses = set()
    original_getaddrinfo = socket.getaddrinfo

    def write_event(event, **fields):
        with log.open('a', encoding='utf-8') as file:
            file.write(json.dumps({'event': event, 'pid': os.getpid(), **fields}) + '\n')

    def loopback(host):
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return str(host).lower() in ('localhost', socket.gethostname().lower())

    def guarded_getaddrinfo(host, port, *args, **kwargs):
        name = host.decode() if isinstance(host, bytes) else str(host or '')
        allowed = loopback(name) or any(name.lower() == domain or name.lower().endswith('.' + domain) for domain in allowed_hosts)
        write_event('dns', host=name, port=port, allowed=allowed)
        if not allowed:
            raise OSError(f'Domestic acceptance blocked DNS request: {name}')
        addresses = original_getaddrinfo(host, port, *args, **kwargs)
        approved_addresses.update(entry[4][0] for entry in addresses)
        return addresses

    def connection_audit(event, arguments):
        if event != 'socket.connect':
            return
        address = arguments[1]
        if not isinstance(address, tuple):
            return
        host, port = address[:2]
        allowed = loopback(host) or (host in approved_addresses and port == 443)
        write_event('connect', address=str(host), port=port, allowed=allowed)
        if not allowed:
            raise OSError(f'Domestic acceptance blocked connection: {host}:{port}')

    socket.getaddrinfo = guarded_getaddrinfo
    sys.addaudithook(connection_audit)
    sys._jingliu_acceptance_guard = True
    write_event('guard-start')
