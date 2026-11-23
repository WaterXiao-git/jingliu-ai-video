"""Direct HTTPS downloads restricted to the distribution hosts in the manifest."""
import json
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


def validate_url(url, hosts):
    parsed = urlsplit(url)
    host = (parsed.hostname or '').lower()
    if parsed.scheme != 'https' or not any(host == allowed or host.endswith('.' + allowed) for allowed in hosts):
        raise URLError(f'下载地址不在国内分发清单中: {host or url}')
    return parsed


def record(audit, url, event):
    if audit is None:
        return
    parsed = urlsplit(url)
    with Path(audit).open('a', encoding='utf-8') as file:
        file.write(json.dumps({'event': event, 'host': parsed.hostname, 'path': parsed.path}) + '\n')


class DistributionRedirect(HTTPRedirectHandler):
    def __init__(self, hosts, audit):
        super().__init__()
        self.hosts = hosts
        self.audit = audit

    def redirect_request(self, request, response, code, message, headers, new_url):
        validate_url(new_url, self.hosts)
        record(self.audit, new_url, 'redirect')
        return super().redirect_request(request, response, code, message, headers, new_url)


def open_resource(request, *, hosts, timeout=60, audit=None):
    if isinstance(request, str):
        request = Request(request)
    validate_url(request.full_url, hosts)
    record(audit, request.full_url, 'request')
    opener = build_opener(ProxyHandler({}), DistributionRedirect(hosts, audit))
    response = opener.open(request, timeout=timeout)
    validate_url(response.url, hosts)
    record(audit, response.url, 'response')
    return response
