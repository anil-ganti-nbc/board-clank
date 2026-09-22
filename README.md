# Board Clank

Operational Clank for single-board computers, compute modules, and closely related board computers.

Foundation 0 only. This repository is the durable architecture: contracts, schemas, identity, source registry, event taxonomy, CLI, fixtures and tests. Future collectors plug into these contracts.

> A new SKU is not necessarily a new board; a new board revision is not necessarily a new product name.
>
> First-seen is observation time, not market novelty.

## Status

- Channel: `foundation-0`
- Live collection: disabled
- Source promotion: none
- Discord / webhooks: not present
- Jetson / NVIDIA: out of scope pending a later decision

## Install

Python 3.12+.

```bash
python -m pip install -e ".[dev]"
board-clank version
board-clank identity
board-clank sources --assert-foundation
board-clank migrate
board-clank health
```

## CLI

| Command | Purpose |
| --- | --- |
| `board-clank version` | Package / channel / schema identity |
| `board-clank identity` | Foundational identity laws |
| `board-clank health` | Read-only health. Never migrates. |
| `board-clank status` | Store census |
| `board-clank sources` | Registry dump |
| `board-clank events` | Event log |
| `board-clank notifications` | Outbox only |
| `board-clank report` | Board / variant summary |
| `board-clank check-state` | Compatibility inspection |
| `board-clank migrate` | Explicit schema admission |
| `board-clank baseline-status` | Per-source silent baselines |
| `board-clank collect --fixture A` | Inert fixture run |
| `board-clank collect --live` | Refused in Foundation 0 |

## Hierarchy

Vendor → Family → Board → Board revision → Commercial variant / SKU

RAM, storage, wireless, region, bundle and SKU never create a new board identity.

## Tests

```bash
pytest
```

No live network is required. CI forces a black-hole proxy.

## Container

```bash
docker build --build-arg GIT_REVISION=$(git rev-parse HEAD) -t board-clank:foundation-0 .
docker run --rm --user 10001 board-clank:foundation-0 health
```

Persistent state: `/app/data`.

## Docs

- [docs/FOUNDATION_0.md](docs/FOUNDATION_0.md)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/IDENTITY_MODEL.md](docs/IDENTITY_MODEL.md)
- [docs/EVENT_MODEL.md](docs/EVENT_MODEL.md)
- [docs/SOURCE_PLANES.md](docs/SOURCE_PLANES.md)
- [docs/NOVELTY_MODEL.md](docs/NOVELTY_MODEL.md)
