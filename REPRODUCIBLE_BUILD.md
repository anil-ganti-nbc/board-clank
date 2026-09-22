# Reproducible build

- Python 3.12
- `requirements.lock` pins runtime versions
- Container label `org.opencontainers.image.revision` is the build-arg `GIT_REVISION`
- Runtime env `BOARD_CLANK_SOURCE_REVISION` carries the same SHA
- GitHub HEAD is not treated as the deployed SHA
- Image user is uid 10001
- Health is `board-clank health` (read-only)
- No webhook secret is baked into the image
