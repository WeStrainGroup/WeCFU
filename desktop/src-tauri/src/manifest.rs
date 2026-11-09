use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    io::Read,
    path::{Path, PathBuf},
};

#[derive(Deserialize)]
pub struct Manifest {
    pub schema_version: u32,
    pub app_version: String,
    pub platform: String,
    pub python: String,
    pub entrypoint: String,
    pub files: BTreeMap<String, String>,
}

pub struct Resources {
    pub root: PathBuf,
    pub python: PathBuf,
    pub entrypoint: PathBuf,
    pub version: String,
}

pub fn platform() -> &'static str {
    if cfg!(all(target_os = "macos", target_arch = "aarch64")) {
        "darwin-arm64"
    } else if cfg!(all(target_os = "windows", target_arch = "x86_64")) {
        "win32-x64"
    } else {
        "unsupported"
    }
}

fn relative(name: &str) -> bool {
    !name.is_empty()
        // Payload filenames are portable ASCII; installation paths may be Unicode.
        && name.is_ascii()
        && !name.bytes().any(|c| c < 32 || c == 127)
        && !name.contains(['\\', ':', '<', '>', '"', '|', '?', '*'])
        && name.split('/').all(|part| {
            let base = part.split('.').next().unwrap_or("").to_ascii_uppercase();
            !matches!(part, "" | "." | "..") && !part.ends_with([' ', '.'])
                && !matches!(base.as_str(), "CON" | "PRN" | "AUX" | "NUL")
                && !(base.len() == 4 && (base.starts_with("COM") || base.starts_with("LPT"))
                    && matches!(base.as_bytes()[3], b'1'..=b'9'))
        })
}

fn inventory(root: &Path, cancelled: &impl Fn() -> bool) -> Result<BTreeSet<String>, String> {
    let mut directories = vec![root.to_owned()];
    let mut files = BTreeSet::new();
    let mut entries = 0;
    while let Some(directory) = directories.pop() {
        for entry in fs::read_dir(directory).map_err(|_| "Cannot inspect bundled resources.")? {
            if cancelled() {
                return Err("Startup was cancelled.".into());
            }
            entries += 1;
            if entries > 200_000 {
                return Err("The resource tree is too large.".into());
            }
            let entry = entry.map_err(|_| "Cannot inspect bundled resources.")?;
            let kind = entry
                .file_type()
                .map_err(|_| "Cannot inspect bundled resources.")?;
            let path = entry.path();
            let name = path
                .strip_prefix(root)
                .map_err(|_| "Invalid bundled resource path.")?
                .to_str()
                .ok_or("Invalid bundled resource filename.")?
                .replace('\\', "/");
            if !relative(&name) || kind.is_symlink() || (!kind.is_dir() && !kind.is_file()) {
                return Err(format!("Invalid bundled resource: {name}"));
            }
            if kind.is_dir() {
                directories.push(path);
            } else if name != "bundle-manifest.json" {
                files.insert(name);
            }
        }
    }
    Ok(files)
}

fn resolve(root: &Path, name: &str) -> Result<PathBuf, String> {
    if !relative(name) {
        return Err("The resource manifest contains an invalid file path.".into());
    }
    let path = root
        .join(name)
        .canonicalize()
        .map_err(|_| format!("Missing bundled resource: {name}"))?;
    if !path.starts_with(root) || !path.is_file() {
        return Err(format!("Invalid bundled resource: {name}"));
    }
    Ok(path)
}

pub fn verify(root: &Path, cancelled: impl Fn() -> bool) -> Result<Resources, String> {
    let root = root
        .canonicalize()
        .map_err(|_| "The application resource folder is missing.".to_string())?;
    let manifest_path = resolve(&root, "bundle-manifest.json")?;
    if fs::metadata(&manifest_path)
        .map_err(|e| e.to_string())?
        .len()
        > 64 * 1024 * 1024
    {
        return Err("The bundled resource manifest is too large.".into());
    }
    let manifest: Manifest =
        serde_json::from_slice(&fs::read(manifest_path).map_err(|e| e.to_string())?)
            .map_err(|_| "The bundled resource manifest is invalid.".to_string())?;
    if manifest.schema_version != 1 || manifest.app_version != env!("CARGO_PKG_VERSION") {
        return Err("The application and bundled resources have different versions. Reinstall the complete application.".into());
    }
    let expected_python = if platform() == "win32-x64" {
        "runtime/python.exe"
    } else {
        "runtime/bin/python3"
    };
    if platform() == "unsupported"
        || manifest.platform != platform()
        || manifest.python != expected_python
        || manifest.entrypoint != "app/desktop_entry.py"
    {
        return Err("These bundled resources are not for this computer.".into());
    }
    if manifest.files.is_empty()
        || manifest.files.len() > 100_000
        || !manifest.files.contains_key(&manifest.python)
        || !manifest.files.contains_key(&manifest.entrypoint)
    {
        return Err(
            "The runtime or application entry point is missing from the resource manifest.".into(),
        );
    }
    let mut folded = BTreeSet::new();
    for name in manifest.files.keys() {
        if !relative(name) || !folded.insert(name.to_ascii_lowercase()) {
            return Err("The resource manifest contains an invalid or ambiguous filename.".into());
        }
    }
    let actual = inventory(&root, &cancelled)?;
    let recorded: BTreeSet<_> = manifest.files.keys().cloned().collect();
    if actual != recorded {
        let detail = actual
            .symmetric_difference(&recorded)
            .next()
            .cloned()
            .unwrap_or_default();
        return Err(format!(
            "Bundled resource inventory differs from its manifest: {detail}"
        ));
    }
    for (name, expected) in &manifest.files {
        if cancelled() {
            return Err("Startup was cancelled.".into());
        }
        if expected.len() != 64 || !expected.bytes().all(|b| b.is_ascii_hexdigit()) {
            return Err(format!("Invalid resource checksum: {name}"));
        }
        let path = resolve(&root, name)?;
        let mut input =
            fs::File::open(path).map_err(|_| format!("Cannot read bundled resource: {name}"))?;
        let mut hash = Sha256::new();
        let mut block = [0u8; 128 * 1024];
        loop {
            if cancelled() {
                return Err("Startup was cancelled.".into());
            }
            let n = input
                .read(&mut block)
                .map_err(|_| format!("Cannot read bundled resource: {name}"))?;
            if n == 0 {
                break;
            }
            hash.update(&block[..n]);
        }
        if format!("{:x}", hash.finalize()) != expected.to_ascii_lowercase() {
            return Err(format!("Bundled resource changed or is incomplete: {name}. Reinstall the complete application."));
        }
    }
    Ok(Resources {
        python: resolve(&root, &manifest.python)?,
        entrypoint: resolve(&root, &manifest.entrypoint)?,
        root,
        version: manifest.app_version,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    struct Fixture(PathBuf);
    impl Fixture {
        fn new() -> Self {
            let root =
                std::env::temp_dir().join(format!("wecfu-resource-test-{}", uuid::Uuid::new_v4()));
            fs::create_dir_all(root.join("runtime/bin")).unwrap();
            fs::create_dir_all(root.join("app")).unwrap();
            let python = if platform() == "win32-x64" {
                "runtime/python.exe"
            } else {
                "runtime/bin/python3"
            };
            let contents = b"synthetic resource, never executed";
            fs::write(root.join(python), contents).unwrap();
            fs::write(root.join("app/desktop_entry.py"), contents).unwrap();
            let digest = format!("{:x}", Sha256::digest(contents));
            let mut files = BTreeMap::new();
            files.insert(python, &digest);
            files.insert("app/desktop_entry.py", &digest);
            fs::write(root.join("bundle-manifest.json"), serde_json::to_vec(&serde_json::json!({
                "schema_version":1,"app_version":env!("CARGO_PKG_VERSION"),"platform":platform(),
                "python":python,"entrypoint":"app/desktop_entry.py","files":files
            })).unwrap()).unwrap();
            Self(root)
        }
        fn change(&self, edit: impl FnOnce(&mut serde_json::Value)) {
            let path = self.0.join("bundle-manifest.json");
            let mut value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
            edit(&mut value);
            fs::write(path, serde_json::to_vec(&value).unwrap()).unwrap();
        }
    }
    impl Drop for Fixture {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }
    #[test]
    fn only_bundle_relative_paths() {
        for bad in [
            "",
            "/tmp/python",
            "../escape",
            "runtime/../escape",
            "C:/python.exe",
            "runtime\\python.exe",
            "a\0b",
            "a//b",
            "a/./b",
            "a/",
            "app/CON.py",
            "app/com1.txt",
            "app/x.",
            "app/x ",
            "a\u{7f}b",
            "app/a?b",
        ] {
            assert!(!relative(bad), "{bad:?}");
        }
        assert!(relative("runtime/bin/python3"));
        assert!(relative("app/wecfu/server/static/index.html"));
    }
    #[test]
    fn verified_bundle_detects_changed_and_missing_files() {
        let fixture = Fixture::new();
        assert!(verify(&fixture.0, || false).is_ok());
        fs::write(fixture.0.join("app/desktop_entry.py"), "changed").unwrap();
        assert!(verify(&fixture.0, || false)
            .err()
            .unwrap()
            .contains("changed or is incomplete"));
        fs::remove_file(fixture.0.join("app/desktop_entry.py")).unwrap();
        assert!(verify(&fixture.0, || false)
            .err()
            .unwrap()
            .contains("inventory differs"));
    }
    #[test]
    fn added_code_and_case_aliases_are_rejected() {
        let fixture = Fixture::new();
        fs::write(fixture.0.join("app/injected.py"), "unrecorded").unwrap();
        assert!(verify(&fixture.0, || false)
            .err()
            .unwrap()
            .contains("inventory differs"));
        let fixture = Fixture::new();
        fixture.change(|m| {
            m["files"]["APP/desktop_entry.py"] = m["files"]["app/desktop_entry.py"].clone();
        });
        assert!(verify(&fixture.0, || false)
            .err()
            .unwrap()
            .contains("ambiguous"));
    }
    #[test]
    fn wrong_platform_version_unlisted_entry_and_cancel_are_rejected() {
        for field in ["platform", "app_version"] {
            let fixture = Fixture::new();
            fixture.change(|m| m[field] = "incorrect".into());
            assert!(verify(&fixture.0, || false).is_err());
        }
        let fixture = Fixture::new();
        fixture.change(|m| {
            m["files"]
                .as_object_mut()
                .unwrap()
                .remove("app/desktop_entry.py");
        });
        assert!(verify(&fixture.0, || false).is_err());
        let fixture = Fixture::new();
        assert!(verify(&fixture.0, || true)
            .err()
            .unwrap()
            .contains("cancelled"));
    }
    #[cfg(unix)]
    #[test]
    fn symlink_may_not_escape_the_bundle() {
        let fixture = Fixture::new();
        let other = Fixture::new();
        let entry = fixture.0.join("app/desktop_entry.py");
        fs::remove_file(&entry).unwrap();
        std::os::unix::fs::symlink(other.0.join("app/desktop_entry.py"), entry).unwrap();
        assert!(verify(&fixture.0, || false)
            .err()
            .unwrap()
            .contains("Invalid bundled resource"));
    }
}
