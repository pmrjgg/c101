# Config loader refactor: complete programs and transcripts

Dependencies used (versions current in October 2026):

```toml
[dependencies]
anyhow = "1"          # 1.0.104
thiserror = "2"       # 2.0.21
serde = { version = "1", features = ["derive"] }
toml = "1"            # 1.1.x; toml::de::Error is 88 bytes, hence the Box
```

## Before

```rust
use serde::Deserialize;
#[derive(Deserialize)]
struct Config { listen: String, workers: usize }
fn load(path: &str) -> Config {
    let text = std::fs::read_to_string(path).unwrap();
    let cfg: Config = toml::from_str(&text).unwrap();
    if cfg.workers == 0 { panic!("bad config"); }
    cfg
}
fn main() {
    let path = std::env::args().nth(1).unwrap_or_else(|| "app.toml".into());
    let cfg = load(&path);
    println!("{} {}", cfg.listen, cfg.workers);
}
```

```text
$ app                                     # app.toml missing, exit code 101
thread 'main' (11) panicked at src/main.rs:5:46:
called `Result::unwrap()` on an `Err` value: Os { code: 2, kind: NotFound, message: "No such file or directory" }
note: run with `RUST_BACKTRACE=1` environment variable to display a backtrace

$ app /tmp/bad.toml                       # workers = "four"
thread 'main' (11) panicked at src/main.rs:6:45:
called `Result::unwrap()` on an `Err` value: Error { message: "invalid type: string \"four\", expected usize", input: Some("listen = \"0.0.0.0:8080\"\nworkers = \"four\"\n"), keys: ["workers"], span: Some(34..40) }
```

Problems: no file name, the parser's internal struct (with the whole input, which may hold
secrets) in user output, `panic!("bad config")` says nothing about which value, exit code 101 looks
like a crash to supervisors.

## After

```rust
use std::{io, path::{Path, PathBuf}};
use anyhow::Context;

#[derive(Debug, serde::Deserialize)]
pub struct Config { pub listen: String, pub workers: usize }

#[derive(Debug, thiserror::Error)]
#[non_exhaustive]
pub enum LoadError {
    #[error("reading {path}")]                       // context only; PathBuf fields render via .display()
    Read { path: PathBuf, #[source] source: io::Error },
    #[error("parsing {path}")]
    Parse { path: PathBuf, #[source] source: Box<toml::de::Error> },   // boxed: 88-byte error
    #[error("invalid value for `{field}`: {reason}")]
    Invalid { field: &'static str, reason: String },
    #[error(transparent)]                            // forwards Display and source() unchanged
    Other(#[from] anyhow::Error),
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[non_exhaustive]
pub enum LoadErrorKind { NotFound, PermissionDenied, Io, Syntax, Invalid }

impl LoadError {
    pub fn kind(&self) -> LoadErrorKind {
        match self {
            LoadError::Read { source, .. } => match source.kind() {
                io::ErrorKind::NotFound => LoadErrorKind::NotFound,
                io::ErrorKind::PermissionDenied => LoadErrorKind::PermissionDenied,
                _ => LoadErrorKind::Io,
            },
            LoadError::Parse { .. } => LoadErrorKind::Syntax,
            LoadError::Invalid { .. } | LoadError::Other(_) => LoadErrorKind::Invalid,
        }
    }
}
pub fn load(path: &Path) -> Result<Config, LoadError> {
    let text = std::fs::read_to_string(path)
        .map_err(|source| LoadError::Read { path: path.to_owned(), source })?;
    let cfg: Config = toml::from_str(&text)
        .map_err(|e| LoadError::Parse { path: path.to_owned(), source: Box::new(e) })?;
    if cfg.workers == 0 {
        return Err(LoadError::Invalid { field: "workers", reason: "must be at least 1".into() });
    }
    Ok(cfg)
}
fn main() -> anyhow::Result<()> {
    let path = std::env::args().nth(1).unwrap_or_else(|| "app.toml".into());
    let cfg = load(Path::new(&path)).with_context(|| format!("loading config from {path}"))?;
    println!("{} {}", cfg.listen, cfg.workers);
    Ok(())
}
```

Transcripts (rustc 1.99.1, exit code 1 in every failing case):

```text
$ app
Error: loading config from app.toml

Caused by:
    0: reading app.toml
    1: No such file or directory (os error 2)

$ app /tmp/bad.toml
Error: loading config from /tmp/bad.toml

Caused by:
    0: parsing /tmp/bad.toml
    1: TOML parse error at line 2, column 11
         |
       2 | workers = "four"
         |           ^^^^^^
       invalid type: string "four", expected usize

$ app /tmp/zero.toml
Error: loading config from /tmp/zero.toml

Caused by:
    invalid value for `workers`: must be at least 1
```

Other renderings of the same errors:

| Form | Missing file | Bad type | Zero workers |
|---|---|---|---|
| `{e}` | `loading config from app.toml` | `loading config from /tmp/bad.toml` | `loading config from /tmp/zero.toml` |
| `{e:#}` | `loading config from app.toml: reading app.toml: No such file or directory (os error 2)` | `loading config from /tmp/bad.toml: parsing /tmp/bad.toml: TOML parse error at line 2, column 11 ...` (multi-line snippet follows) | ``loading config from /tmp/zero.toml: invalid value for `workers`: must be at least 1`` |
| `e.downcast_ref::<LoadError>().map(LoadError::kind)` | `Some(NotFound)` | `Some(Syntax)` | `Some(Invalid)` |
| `source()` chain length | 3 | 3 | 2 |

Sizes measured on x86_64: `LoadError` 40 bytes (with `Box<toml::de::Error>`), 112 bytes unboxed;
`anyhow::Error` 8 bytes.

## Tests for the new behaviour

```rust
#[test]
fn zero_workers_is_rejected() {
    std::fs::write("target/zero.toml", "listen = \"x\"\nworkers = 0\n").unwrap();
    let err = load(Path::new("target/zero.toml")).unwrap_err();
    assert!(matches!(err, LoadError::Invalid { field: "workers", .. }));
    assert_eq!(err.kind(), LoadErrorKind::Invalid);
}

#[test]
fn missing_file_is_not_found() {
    let err = load(Path::new("does/not/exist.toml")).unwrap_err();
    assert_eq!(err.kind(), LoadErrorKind::NotFound);   // portable: no OS message text
}
```
