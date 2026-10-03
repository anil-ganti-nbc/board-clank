"""Bounded redirects that retain each collector's first-party plane boundary."""
from urllib.request import HTTPRedirectHandler
from urllib.parse import urlparse

from .base import CollectorError


def document_url_validator(requested_url, validate, classify_role, *, normalize_path=lambda path: path.rstrip('/')):
    """Keep required document roles and selected discovery/change coverage."""
    requested = urlparse(requested_url)
    expected_role = classify_role(requested_url)
    def route_key(parsed):
        return (parsed.scheme, parsed.netloc, normalize_path(parsed.path),
                parsed.params, parsed.query, parsed.fragment)

    route = route_key(requested)

    def linked_validate(url):
        validate(url)
        parsed = urlparse(url)
        if classify_role(url) != expected_role:
            raise CollectorError(f"required document role changed: {requested_url} -> {url}")
        if expected_role in {'index', 'pcn'} and route_key(parsed) != route:
            raise CollectorError(f"required discovery/change route changed: {requested_url} -> {url}")
        return url

    return linked_validate


def require_document_role(drafts, info, role):
    """A selected required document must provide the expected evidence role."""
    status = info.get('status')
    roles = info.get('evidence_roles') or []
    if (role == 'index' and status == 'lead-index' and not drafts
            and 'DISCOVERY' in roles and info.get('lead_hrefs')):
        return
    if (role == 'pcn' and status == 'pip-pcn' and not drafts
            and 'CHANGE_EVIDENCE' in roles and info.get('pcns')):
        return
    if role == 'detail':
        if status in {'resolved', 'resolved-identity', 'identity-conflict', 'insufficient-evidence'} and drafts:
            return
        if (status == 'ignored-non-computer' and not drafts
                and info.get('scope') == 'NON_BOARD_CATALOGUE_ITEM'
                and info.get('reason')
                and info.get('heading') not in {None, '', 'UNKNOWN'}):
            return
    raise CollectorError(f"unexpected required {role} document status: {status}")


class ValidatedRedirect(HTTPRedirectHandler):
    max_redirections = 5
    max_repeats = 2

    def __init__(self, validate):
        super().__init__()
        self.validate = validate

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.validate(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)
