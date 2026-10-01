# Local/CI object storage

The former official MinIO registry image is no longer anonymously pullable. This development/CI image builds the official [security release](https://github.com/minio/minio/releases/tag/RELEASE.2025-10-15T17-29-55Z) at commit `9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a`, with a SHA256-verified source archive and upstream `go.sum`; `-mod=readonly` prevents dependency drift. It runs as UID/GID 10001 and includes the upstream AGPL-3.0 license. Corresponding source is available at the pinned URL in the Dockerfile; no MinIO code is vendored into ReadySet packages.

Build: `docker build -t readyset-minio:local infra/minio`. Compose and CI build it directly. This does not designate archived MinIO as a production provider: production must select and maintain its private S3-compatible service and review its licensing/security lifecycle. No demo/references inputs are used.

For development networks with a trusted enterprise TLS proxy, pass the public CA PEM using `docker build --secret id=build_ca,src=/path/to/trusted-ca.pem -t readyset-minio:local infra/minio`. The optional secret only augments build-time module-download trust; it is absent from the runtime image. TLS verification and upstream module checksum verification remain enabled. Do not add private keys or CA files to the repository.
