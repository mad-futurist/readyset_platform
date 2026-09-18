# Repository instructions

## Production isolation

`demo/` contains legacy demonstration material and `references/` contains external research material. Both trees are non-production inputs only.

Production code and packages under `apps/` and `packages/` must not import, copy, load, execute, serve, bundle, or otherwise depend on code, files, data, assets, configuration, or generated artifacts from `demo/` or `references/`. Production dependency manifests, build scripts, Docker images, tests, and runtime configuration must remain independent of both trees.

Ideas may be reimplemented in the production codebase, but no build-time or runtime link to either research tree may be introduced. Before completing packaging or dependency changes, verify source references, manifests, Docker copy rules, and built artifacts preserve this isolation.
