# Rust launcher preview

`god-kit-preview` is an opt-in Cargo package for testing how a future God of Code Kit executable would run in WSL. It forwards commands to the `god` launcher from the checkout you select. The Python worker still handles coding, tests, and inference through the [WSL setup](../../WSL.md).

## Build in WSL

From the kit root:

```bash
cargo build --offline --locked --release --manifest-path rust/god-kit-preview/Cargo.toml
rust/god-kit-preview/target/release/god-kit-preview --version
```

From a project's WSL terminal, point the preview at the checkout you use for coding:

```bash
GOD_KIT_DIR=/absolute/path/to/kit-checkout /absolute/path/to/god-kit-preview doctor
```

Use the path to the release executable you built above. The launcher passes the current directory, environment, arguments and exit status through to `god`.

Before a standalone release, the executable needs its own supervisor and relay. Verify task and review behavior, the offline Docker sandbox, request redaction and signing, and patch application before switching the default launcher.
