# Contributing

Issues and pull requests are welcome, especially reports from other countries' LiDAR data and other Unreal versions.

## Developer Certificate of Origin

Every commit must be signed off, which certifies the [Developer Certificate of Origin 1.1](https://developercertificate.org/):
that you wrote the change or otherwise have the right to submit it under this project's licence (Apache-2.0).

    git commit -s -m "your message"

This adds `Signed-off-by: Your Name <you@example.com>`. There is no contributor licence agreement: your contribution
stays yours, licensed to everyone under Apache-2.0, the same as the rest of the code.

## Before you open a pull request

- `uv run pytest` passes.
- New behaviour comes with a test, ideally on synthetic data with a known answer (see `tests/`).
- Never commit downloaded data (GeoTIFF, LAZ, OSM dumps) or real coordinates of a private place.
