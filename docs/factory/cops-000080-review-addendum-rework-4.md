# COPS-000080 review addendum (rework 4)

Review-driven clarifications for candidate SHA after `00ff59c4`. The frozen contract v1 remains byte-identical. The SPEC body is not re-frozen.

## Reason codes

- `robots_unavailable` is a stored lead `reason_code` when OEM verification cannot proceed because that host's `robots.txt` was not HTTP 200. Fetch provenance still records the robots row.
- OEM fetch timeout, TLS, DNS, and HTTP 4xx/5xx (other than access-control) still store `fetch_failed`. Access-control remains `http_blocked`. Robots Disallow remains `robots_disallow`.

## HTTP

- Timeout 15s is a monotonic wall-clock deadline across connect, TLS, headers, and body reads, not only a per-socket-operation timeout.
- An HTTPS-to-HTTP redirect is rejected with fetch error `https_downgrade`. The HTTP hop is not requested.

## Runtime data

- `src/cnx_seeder/data/*` ships as package data. Console script `cnx-oem-seeder` is declared.
- The vendored PSL digest is verified at load after CRLF normalisation.

## Classification

- Closed SoC policy includes `nxp` / `nxp.com`. NXP evaluation boards do not qualify as a newly discovered board OEM.
- `{Name} Board` catalogue evidence ignores SoC names and tokens containing digits. Outbound links to closed SoC domains are not other-manufacturer evidence.

## URL storage

- `runs.listing_url` and `runs.article_urls_json` (and therefore `report.json`) drop `utm_*`, `token`, `key`, and `sig` query keys, matching fetch/lead/candidate URL storage.
