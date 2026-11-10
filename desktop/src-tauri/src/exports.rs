//! Native exports only accept an OS-selected destination and an opaque per-export ID.
//! The webview never supplies a filesystem path or receives a general filesystem API.
use serde::Serialize;
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::{Path, PathBuf},
    sync::{atomic::Ordering, Arc},
};

use crate::{protocol, Shared};

const MAX_RECEIPTS: usize = 32;

#[derive(Clone, Debug, Serialize)]
pub struct Prepared {
    id: String,
    path: String,
}

#[derive(Clone, Debug, Serialize)]
pub struct ExportEvent {
    pub id: String,
    pub status: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub path: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub message: Option<&'static str>,
}

#[derive(Debug, Clone, PartialEq)]
struct Existing {
    len: u64,
    modified: Option<std::time::SystemTime>,
    #[cfg(unix)]
    inode: (u64, u64),
}

fn existing(path: &Path) -> Result<Option<Existing>, String> {
    match fs::symlink_metadata(path) {
        Ok(meta) if meta.file_type().is_file() => {
            #[cfg(unix)]
            use std::os::unix::fs::MetadataExt;
            Ok(Some(Existing {
                len: meta.len(),
                modified: meta.modified().ok(),
                #[cfg(unix)]
                inode: (meta.dev(), meta.ino()),
            }))
        }
        Ok(_) => Err("invalid_destination".into()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(_) => Err("invalid_destination".into()),
    }
}

#[derive(Debug)]
struct Pending {
    id: String,
    target: PathBuf,
    display_path: String,
    original: Option<Existing>,
    stage_dir: Option<PathBuf>,
    stage: Option<PathBuf>,
    url: Option<String>,
    started: bool,
    cancelled: bool,
}

impl Pending {
    fn cleanup(&self) -> bool {
        // Only our exact random staging file and now-empty directory are removable.
        // Never recursively remove a user directory or the selected destination.
        let removed = |result: std::io::Result<()>| {
            result.is_ok() || result.is_err_and(|e| e.kind() == std::io::ErrorKind::NotFound)
        };
        if let Some(stage) = &self.stage {
            if !removed(fs::remove_file(stage)) {
                return false;
            }
        }
        if let Some(folder) = &self.stage_dir {
            if !removed(fs::remove_dir(folder)) {
                return false;
            }
        }
        true
    }
}

#[derive(Default)]
pub struct Book {
    choosing: bool,
    pending: Option<Pending>,
    cancelled: BTreeMap<String, Pending>,
    used_urls: BTreeSet<String>,
    completed: BTreeMap<String, PathBuf>,
    receipt_order: std::collections::VecDeque<String>,
}

impl Book {
    fn begin(&mut self) -> Result<(), String> {
        if self.choosing || self.pending.is_some() {
            return Err("export_busy".into());
        }
        self.choosing = true;
        Ok(())
    }

    fn selected(
        &mut self,
        path: Option<PathBuf>,
        extension: &str,
    ) -> Result<Option<Prepared>, String> {
        self.choosing = false;
        let Some(path) = path else { return Ok(None) };
        if !path.is_absolute()
            || path
                .extension()
                .and_then(|e| e.to_str())
                .map(str::to_ascii_lowercase)
                .as_deref()
                != Some(extension)
        {
            return Err("invalid_destination".into());
        }
        let parent = path
            .parent()
            .ok_or("invalid_destination")?
            .canonicalize()
            .map_err(|_| "invalid_destination")?;
        let filename = path.file_name().ok_or("invalid_destination")?;
        let target = parent.join(filename);
        let display_path = presentation_path(&target)?.to_string_lossy().into_owned();
        let original = existing(&target)?;
        let id = uuid::Uuid::new_v4().simple().to_string();
        self.pending = Some(Pending {
            id: id.clone(),
            target: target.clone(),
            display_path: display_path.clone(),
            original,
            stage_dir: None,
            stage: None,
            url: None,
            started: false,
            cancelled: false,
        });
        Ok(Some(Prepared {
            id,
            path: display_path,
        }))
    }

    fn arm(&mut self, id: &str, url: &url::Url, origin: &Option<String>) -> Result<(), String> {
        // Frontend exports are authenticated fetches turned into same-session blobs.
        // Reject arbitrary HTTP requests, file URLs and cross-origin blobs here.
        if url.as_str().len() > 2048
            || url.scheme() != "blob"
            || !protocol::downloadable(url, origin)
        {
            return Err("invalid_export_url".into());
        }
        if self.used_urls.contains(url.as_str()) {
            return Err("export_url_already_used".into());
        }
        let pending = self
            .pending
            .as_mut()
            .filter(|p| p.id == id)
            .ok_or("unknown_export")?;
        if pending.url.is_some() || pending.cancelled {
            return Err("export_already_armed".into());
        }
        let folder = pending
            .target
            .parent()
            .ok_or("invalid_destination")?
            .join(format!(".wecfu-export-{}", pending.id));
        let mut builder = fs::DirBuilder::new();
        #[cfg(unix)]
        {
            use std::os::unix::fs::DirBuilderExt;
            builder.mode(0o700);
        }
        builder.create(&folder).map_err(|_| "cannot_stage_export")?;
        let stage = folder.join("download.partial");
        pending.stage_dir = Some(folder);
        pending.stage = Some(stage);
        pending.url = Some(url.to_string());
        self.used_urls.insert(url.to_string());
        Ok(())
    }

    pub fn requested(&mut self, url: &url::Url, origin: &Option<String>) -> Option<PathBuf> {
        if !protocol::downloadable(url, origin) {
            return None;
        }
        let pending = self.pending.as_mut()?;
        if pending.url.as_deref() != Some(url.as_str()) || pending.started || pending.cancelled {
            return None;
        }
        pending.started = true;
        pending.stage.clone()
    }

    fn cancel(&mut self, id: &str) -> Result<(), String> {
        if self.completed.contains_key(id) {
            return Ok(());
        }
        if self.cancelled.values().any(|p| p.id == id) {
            return Ok(());
        }
        if !self.pending.as_ref().is_some_and(|p| p.id == id) {
            return Err("unknown_export".into());
        }
        let mut pending = self.pending.take().unwrap();
        pending.cancelled = true;
        if pending.started {
            // Retain ownership until Finished, but allow another Save As after a
            // frontend timeout. A delayed old event cannot target the new export.
            self.cancelled.insert(pending.url.clone().unwrap(), pending);
        } else if !pending.cleanup() {
            self.cancelled.insert(pending.id.clone(), pending);
        }
        Ok(())
    }

    pub fn finished(
        &mut self,
        url: &url::Url,
        path: Option<&Path>,
        success: bool,
    ) -> Option<ExportEvent> {
        let pending = if self
            .pending
            .as_ref()
            .is_some_and(|p| p.url.as_deref() == Some(url.as_str()))
        {
            self.pending.take()?
        } else {
            self.cancelled.remove(url.as_str())?
        };
        let outcome = (|| -> Result<(), String> {
            let stage = pending.stage.as_ref().ok_or("missing_stage")?;
            if !success
                || !pending.started
                || pending.cancelled
                || path.is_some_and(|p| !completion_path_matches(p, stage))
            {
                return Err("export_failed".into());
            }
            let meta = fs::symlink_metadata(stage).map_err(|_| "missing_stage")?;
            if !meta.file_type().is_file() || meta.len() == 0 {
                return Err("empty_export".into());
            }
            // An existing destination was approved in the OS overwrite prompt. Refuse
            // to replace a file that appeared or changed after that confirmation.
            if existing(&pending.target)? != pending.original {
                return Err("destination_changed".into());
            }
            fs::OpenOptions::new()
                .write(true)
                .open(stage)
                .and_then(|f| f.sync_all())
                .map_err(|_| "cannot_sync_export")?;
            promote(stage, &pending.target).map_err(|_| "cannot_save_export")?;
            Ok(())
        })();
        if !pending.cleanup() {
            // A platform may briefly retain its download handle after Finished.
            // Keep exact ownership so the shutdown retry does not lose this path.
            self.cancelled.insert(
                format!("cleanup-{}", pending.id),
                Pending {
                    id: pending.id.clone(),
                    target: pending.target.clone(),
                    display_path: pending.display_path.clone(),
                    original: pending.original.clone(),
                    stage_dir: pending.stage_dir.clone(),
                    stage: pending.stage.clone(),
                    url: pending.url.clone(),
                    started: false,
                    cancelled: true,
                },
            );
        }
        match outcome {
            Ok(()) => {
                self.completed
                    .insert(pending.id.clone(), pending.target.clone());
                self.receipt_order.push_back(pending.id.clone());
                while self.receipt_order.len() > MAX_RECEIPTS {
                    if let Some(old) = self.receipt_order.pop_front() {
                        self.completed.remove(&old);
                    }
                }
                Some(ExportEvent {
                    id: pending.id,
                    status: "saved",
                    path: Some(pending.display_path),
                    message: None,
                })
            }
            Err(_) => Some(ExportEvent {
                id: pending.id,
                status: "error",
                path: None,
                message: Some("export_failed"),
            }),
        }
    }

    fn reveal_path(&self, id: &str) -> Result<PathBuf, String> {
        let path = self.completed.get(id).ok_or("unknown_export")?;
        if existing(path)?.is_none() {
            return Err("missing_export".into());
        }
        Ok(path.clone())
    }

    pub fn cleanup(&mut self) -> bool {
        if let Some(mut pending) = self.pending.take() {
            pending.cancelled = true;
            // Keep in-flight ownership until the callback or final event-loop cleanup.
            if pending.started || !pending.cleanup() {
                self.cancelled.insert(
                    pending.url.clone().unwrap_or_else(|| pending.id.clone()),
                    pending,
                );
            }
        }
        self.cancelled.retain(|_, pending| !pending.cleanup());
        self.choosing = false;
        self.cancelled.is_empty()
    }
}

#[cfg(not(windows))]
fn presentation_path(path: &Path) -> Result<PathBuf, String> {
    Ok(path.to_owned())
}

#[cfg(windows)]
fn presentation_path(path: &Path) -> Result<PathBuf, String> {
    use std::path::Prefix;
    if !path.is_absolute() {
        return Err("invalid_destination".into());
    }
    let mut components = path.components();
    let Some(std::path::Component::Prefix(prefix)) = components.next() else {
        return Err("invalid_destination".into());
    };
    match prefix.kind() {
        // Match Wry's conservative simplification. Long paths, reserved names,
        // trailing dots/spaces and verbatim UNC retain their exact spelling.
        Prefix::VerbatimDisk(_) => Ok(dunce::simplified(path).to_owned()),
        Prefix::VerbatimUNC(_, _) | Prefix::Disk(_) | Prefix::UNC(_, _) => Ok(path.to_owned()),
        // Device and volume namespaces are not safe Explorer display names.
        _ => Err("invalid_destination".into()),
    }
}

#[cfg(windows)]
fn shell_path(path: &Path) -> Result<PathBuf, String> {
    use std::path::{Component, Prefix};
    let path = presentation_path(path)?;
    match path.components().next() {
        Some(Component::Prefix(prefix))
            if matches!(prefix.kind(), Prefix::Disk(_) | Prefix::UNC(_, _)) =>
        {
            Ok(path)
        }
        // Explorer must never reinterpret a path that needs verbatim semantics.
        _ => Err("cannot_reveal_export".into()),
    }
}

fn completion_path_matches(actual: &Path, expected: &Path) -> bool {
    #[cfg(windows)]
    {
        // Wry simplifies verbatim paths before passing them to WebView2, so the
        // completion callback can spell our owned stage differently. Resolve both
        // existing files; never accept a different destination or a missing file.
        matches!(
            (actual.canonicalize(), expected.canonicalize()),
            (Ok(actual), Ok(expected)) if actual == expected
        )
    }
    #[cfg(not(windows))]
    {
        actual == expected
    }
}

#[cfg(not(windows))]
fn promote(source: &Path, destination: &Path) -> std::io::Result<()> {
    fs::rename(source, destination)
}

#[cfg(windows)]
fn promote(source: &Path, destination: &Path) -> std::io::Result<()> {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Storage::FileSystem::{
        MoveFileExW, MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH,
    };
    let source: Vec<u16> = source.as_os_str().encode_wide().chain(Some(0)).collect();
    let destination: Vec<u16> = destination
        .as_os_str()
        .encode_wide()
        .chain(Some(0))
        .collect();
    if unsafe {
        MoveFileExW(
            source.as_ptr(),
            destination.as_ptr(),
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
        )
    } == 0
    {
        Err(std::io::Error::last_os_error())
    } else {
        Ok(())
    }
}

fn authorized(window: &tauri::WebviewWindow, shared: &Shared) -> Result<(), String> {
    if window.label() != "main"
        || shared.shutdown.load(Ordering::SeqCst)
        || !window
            .url()
            .is_ok_and(|url| protocol::same_origin(&url, &shared.origin.lock().unwrap()))
    {
        return Err("export_unavailable".into());
    }
    Ok(())
}

fn extension(file_name: &str) -> Result<&'static str, String> {
    if file_name.is_empty()
        || file_name.len() > 240
        || file_name
            .chars()
            .any(|c| c.is_control() || matches!(c, '/' | '\\' | ':'))
    {
        return Err("invalid_export_name".into());
    }
    match Path::new(file_name)
        .extension()
        .and_then(|s| s.to_str())
        .map(str::to_ascii_lowercase)
        .as_deref()
    {
        Some("csv") => Ok("csv"),
        Some("zip") => Ok("zip"),
        _ => Err("invalid_export_name".into()),
    }
}

fn dialog_title(locale: &str) -> &'static str {
    match locale.split(['-', '_']).next().unwrap_or_default() {
        "zh" => "保存导出文件",
        "fr" => "Enregistrer l’export",
        "ru" => "Сохранить экспорт",
        _ => "Save export",
    }
}

#[tauri::command]
pub async fn desktop_export_prepare(
    window: tauri::WebviewWindow,
    state: tauri::State<'_, Arc<Shared>>,
    file_name: String,
    locale: String,
) -> Result<Option<Prepared>, String> {
    authorized(&window, &state)?;
    let ext = extension(&file_name)?;
    state.exports.lock().unwrap().begin()?;
    let selected = rfd::AsyncFileDialog::new()
        .set_parent(&window)
        .set_title(dialog_title(&locale))
        .set_file_name(&file_name)
        .add_filter(ext.to_ascii_uppercase(), &[ext])
        .save_file()
        .await;
    if let Err(error) = authorized(&window, &state) {
        state.exports.lock().unwrap().choosing = false;
        return Err(error);
    }
    state
        .exports
        .lock()
        .unwrap()
        .selected(selected.map(|file| file.path().to_owned()), ext)
}

#[tauri::command]
pub fn desktop_export_arm(
    window: tauri::WebviewWindow,
    state: tauri::State<'_, Arc<Shared>>,
    id: String,
    url: String,
) -> Result<(), String> {
    authorized(&window, &state)?;
    let parsed = url::Url::parse(&url).map_err(|_| "invalid_export_url")?;
    let origin = state.origin.lock().unwrap().clone();
    state.exports.lock().unwrap().arm(&id, &parsed, &origin)
}

#[tauri::command]
pub fn desktop_export_cancel(
    window: tauri::WebviewWindow,
    state: tauri::State<'_, Arc<Shared>>,
    id: String,
) -> Result<(), String> {
    authorized(&window, &state)?;
    state.exports.lock().unwrap().cancel(&id)
}

#[tauri::command]
pub fn desktop_export_reveal(
    window: tauri::WebviewWindow,
    state: tauri::State<'_, Arc<Shared>>,
    id: String,
) -> Result<(), String> {
    authorized(&window, &state)?;
    let path = state.exports.lock().unwrap().reveal_path(&id)?;
    #[cfg(target_os = "macos")]
    let result = std::process::Command::new("/usr/bin/open")
        .arg("-R")
        .arg(&path)
        .status();
    #[cfg(windows)]
    return reveal_windows(&path);
    #[cfg(not(any(target_os = "macos", windows)))]
    let result = std::process::Command::new("xdg-open")
        .arg(path.parent().ok_or("missing_export")?)
        .status();
    #[cfg(not(windows))]
    result
        .map_err(|_| "cannot_reveal_export".to_string())
        .and_then(|status| {
            if status.success() {
                Ok(())
            } else {
                Err("cannot_reveal_export".into())
            }
        })
}

#[cfg(windows)]
fn reveal_windows(path: &Path) -> Result<(), String> {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::{
        System::Com::{CoInitializeEx, CoTaskMemFree, CoUninitialize, COINIT_APARTMENTTHREADED},
        UI::Shell::{SHOpenFolderAndSelectItems, SHParseDisplayName},
    };
    let path = shell_path(path).map_err(|_| "cannot_reveal_export".to_string())?;
    let wide: Vec<u16> = path.as_os_str().encode_wide().chain(Some(0)).collect();
    // This command is synchronous; balance COM initialization only when it succeeds.
    unsafe {
        let initialized = CoInitializeEx(std::ptr::null(), COINIT_APARTMENTTHREADED as u32);
        let mut item = std::ptr::null_mut();
        let parsed = SHParseDisplayName(
            wide.as_ptr(),
            std::ptr::null_mut(),
            &mut item,
            0,
            std::ptr::null_mut(),
        );
        let result = if parsed >= 0 && !item.is_null() {
            let result = SHOpenFolderAndSelectItems(item, 0, std::ptr::null(), 0);
            CoTaskMemFree(item.cast());
            result
        } else {
            parsed
        };
        if initialized >= 0 {
            CoUninitialize();
        }
        if result >= 0 {
            Ok(())
        } else {
            Err("cannot_reveal_export".into())
        }
    }
}

pub fn notify(webview: &tauri::Webview, event: &ExportEvent) {
    let detail = serde_json::to_string(event).unwrap();
    let _ = webview.eval(&format!(
        "window.dispatchEvent(new CustomEvent('wecfu:desktop-export',{{detail:{detail}}}));"
    ));
}

#[cfg(test)]
mod tests {
    use super::*;
    struct Temp(PathBuf);
    impl Temp {
        fn new() -> Self {
            let p =
                std::env::temp_dir().join(format!("wecfu-export-test-{}", uuid::Uuid::new_v4()));
            fs::create_dir(&p).unwrap();
            Self(p)
        }
    }
    impl Drop for Temp {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }
    fn origin() -> Option<String> {
        Some("http://127.0.0.1:54321".into())
    }
    fn blob() -> url::Url {
        "blob:http://127.0.0.1:54321/example".parse().unwrap()
    }
    fn prepare(book: &mut Book, path: PathBuf) -> Prepared {
        book.begin().unwrap();
        book.selected(Some(path), "csv").unwrap().unwrap()
    }
    #[test]
    fn cancelled_dialog_creates_no_file_or_reservation() {
        let temp = Temp::new();
        let mut book = Book::default();
        book.begin().unwrap();
        assert!(book.selected(None, "csv").unwrap().is_none());
        assert_eq!(fs::read_dir(&temp.0).unwrap().count(), 0);
        assert!(book.begin().is_ok());
    }
    #[test]
    fn path_and_name_inputs_are_bounded_and_csv_zip_only() {
        for bad in [
            "../x.csv",
            "a/b.csv",
            "a\\b.csv",
            "x.exe",
            "x.csv\n",
            "file:x.csv",
            "",
        ] {
            assert!(extension(bad).is_err());
        }
        assert_eq!(extension("计数结果.csv").unwrap(), "csv");
        assert_eq!(extension("results.zip").unwrap(), "zip");
        assert_eq!(extension("RESULTS.CSV").unwrap(), "csv");
        assert_eq!(extension("RESULTS.ZIP").unwrap(), "zip");
        let mut book = Book::default();
        book.begin().unwrap();
        assert!(book.selected(Some("relative.csv".into()), "csv").is_err());
    }
    #[test]
    fn arm_and_download_require_same_session_and_single_opaque_id() {
        let temp = Temp::new();
        let mut book = Book::default();
        let p = prepare(&mut book, temp.0.join("x.csv"));
        assert!(book.arm("wrong", &blob(), &origin()).is_err());
        for bad in [
            "http://127.0.0.1:54321/export",
            "file:///x.csv",
            "blob:http://127.0.0.1:54322/x",
        ] {
            assert!(book.arm(&p.id, &bad.parse().unwrap(), &origin()).is_err());
        }
        assert_eq!(fs::read_dir(&temp.0).unwrap().count(), 0);
        book.arm(&p.id, &blob(), &origin()).unwrap();
        assert!(book.arm(&p.id, &blob(), &origin()).is_err());
        assert!(book.reveal_path(&p.id).is_err());
        assert!(book
            .requested(&blob(), &Some("http://127.0.0.1:54322".into()))
            .is_none());
        assert!(book.requested(&blob(), &origin()).is_some());
        assert!(book.requested(&blob(), &origin()).is_none());
    }
    #[test]
    fn failed_or_cancelled_download_never_replaces_existing_file() {
        for cancel in [false, true] {
            let temp = Temp::new();
            let path = temp.0.join("结果.csv");
            fs::write(&path, b"original").unwrap();
            let mut book = Book::default();
            let p = prepare(&mut book, path.clone());
            book.arm(&p.id, &blob(), &origin()).unwrap();
            let stage = book.requested(&blob(), &origin()).unwrap();
            fs::write(&stage, b"partial").unwrap();
            if cancel {
                book.cancel(&p.id).unwrap();
            }
            let result = book.finished(&blob(), None, cancel).unwrap();
            assert_eq!(result.status, "error");
            assert_eq!(fs::read(path).unwrap(), b"original");
            assert!(!stage.exists());
            assert_eq!(fs::read_dir(&temp.0).unwrap().count(), 1);
        }
    }
    #[test]
    fn success_promotes_only_finished_download_then_reveal_is_permitted() {
        let temp = Temp::new();
        let path = temp.0.join("result.csv");
        fs::write(&path, b"old").unwrap();
        let mut book = Book::default();
        let p = prepare(&mut book, path.clone());
        book.arm(&p.id, &blob(), &origin()).unwrap();
        let stage = book.requested(&blob(), &origin()).unwrap();
        fs::write(&stage, b"new-csv").unwrap();
        assert_eq!(fs::read(&path).unwrap(), b"old");
        assert!(book.reveal_path(&p.id).is_err());
        let result = book.finished(&blob(), Some(&stage), true).unwrap();
        assert_eq!(result.status, "saved");
        assert_eq!(fs::read(&path).unwrap(), b"new-csv");
        assert_eq!(
            book.reveal_path(&p.id).unwrap(),
            path.canonicalize().unwrap()
        );
        assert_eq!(result.path.as_deref(), Some(p.path.as_str()));
        book.cancel(&p.id).unwrap();
        assert_eq!(fs::read(&path).unwrap(), b"new-csv");
    }
    #[test]
    fn changed_destination_and_wrong_completion_path_fail_closed() {
        for changed in [false, true] {
            let temp = Temp::new();
            let path = temp.0.join("result.csv");
            let mut book = Book::default();
            let p = prepare(&mut book, path.clone());
            book.arm(&p.id, &blob(), &origin()).unwrap();
            let stage = book.requested(&blob(), &origin()).unwrap();
            fs::write(&stage, b"new-csv").unwrap();
            if changed {
                fs::write(&path, b"concurrent-user-file").unwrap();
            }
            let result = book
                .finished(&blob(), if changed { None } else { Some(&path) }, true)
                .unwrap();
            assert_eq!(result.status, "error");
            assert!(book.reveal_path(&p.id).is_err());
            assert!(!stage.exists());
            if changed {
                assert_eq!(fs::read(&path).unwrap(), b"concurrent-user-file");
            } else {
                assert!(!path.exists());
            }
        }
    }
    #[test]
    fn cancel_before_download_cleans_only_own_stage() {
        let temp = Temp::new();
        let path = temp.0.join("result.csv");
        let mut book = Book::default();
        let p = prepare(&mut book, path);
        book.arm(&p.id, &blob(), &origin()).unwrap();
        assert_eq!(fs::read_dir(&temp.0).unwrap().count(), 1);
        book.cancel(&p.id).unwrap();
        assert_eq!(fs::read_dir(&temp.0).unwrap().count(), 0);
        assert!(book.requested(&blob(), &origin()).is_none());
        assert!(book.cancel(&p.id).is_err());
    }
    #[test]
    fn timed_out_download_cannot_block_or_overwrite_the_next_export() {
        let temp = Temp::new();
        let mut book = Book::default();
        let old = prepare(&mut book, temp.0.join("old.csv"));
        book.arm(&old.id, &blob(), &origin()).unwrap();
        let old_stage = book.requested(&blob(), &origin()).unwrap();
        fs::write(&old_stage, b"old-download").unwrap();
        book.cancel(&old.id).unwrap();
        let next = prepare(&mut book, temp.0.join("next.CSV"));
        assert!(book.arm(&next.id, &blob(), &origin()).is_err());
        let next_url: url::Url = "blob:http://127.0.0.1:54321/next".parse().unwrap();
        book.arm(&next.id, &next_url, &origin()).unwrap();
        assert_eq!(book.finished(&blob(), None, true).unwrap().status, "error");
        assert!(!temp.0.join("old.csv").exists());
        assert!(!old_stage.exists());
        let next_stage = book.requested(&next_url, &origin()).unwrap();
        fs::write(&next_stage, b"next-download").unwrap();
        assert_eq!(
            book.finished(&next_url, None, true).unwrap().status,
            "saved"
        );
        assert_eq!(fs::read(temp.0.join("next.CSV")).unwrap(), b"next-download");
    }

    #[cfg(windows)]
    #[test]
    fn windows_display_and_shell_paths_preserve_unicode_drive_and_unc_names() {
        for (internal, displayed) in [
            (r"\\?\C:\研究 数据\结果.csv", r"C:\研究 数据\结果.csv"),
            (
                r"\\?\UNC\server\shared data\Результат.zip",
                r"\\?\UNC\server\shared data\Результат.zip",
            ),
            (r"C:\研究 数据\结果.csv", r"C:\研究 数据\结果.csv"),
            (
                r"\\server\shared data\Результат.zip",
                r"\\server\shared data\Результат.zip",
            ),
        ] {
            assert_eq!(
                presentation_path(Path::new(internal)).unwrap(),
                Path::new(displayed)
            );
        }
        for unsupported in [
            r"\\?\GLOBALROOT\Device\HarddiskVolume1\result.csv",
            r"\\?\Volume{12345678-1234-1234-1234-123456789012}\result.csv",
            r"\\.\C:\result.csv",
            r"C:result.csv",
            r"result.csv",
        ] {
            assert!(presentation_path(Path::new(unsupported)).is_err());
        }
    }

    #[cfg(windows)]
    #[test]
    fn windows_extended_path_semantics_are_preserved_and_not_sent_to_explorer() {
        let long_path = format!(r"\\?\C:\{}\{}\result.csv", "a".repeat(150), "b".repeat(150));
        for original in [
            r"\\?\C:\results.\out.csv",
            r"\\?\C:\results \out.csv",
            r"\\?\C:\CON\out.csv",
            r"\\?\C:\AUX.txt\out.csv",
            r"\\?\C:\COM1\out.csv",
            r"\\?\UNC\server\share\out.csv",
            r"\\?\UNC\server\share\results.\out.csv",
            long_path.as_str(),
        ] {
            assert_eq!(
                presentation_path(Path::new(original)).unwrap(),
                Path::new(original)
            );
            assert!(shell_path(Path::new(original)).is_err());
        }
        assert_eq!(
            shell_path(Path::new(r"\\?\C:\研究 数据\结果.csv")).unwrap(),
            Path::new(r"C:\研究 数据\结果.csv")
        );
    }

    #[cfg(windows)]
    #[test]
    fn windows_webview_normalized_completion_promotes_owned_stage() {
        let temp = Temp::new();
        let path = temp.0.join("结果.csv");
        fs::write(&path, b"old").unwrap();
        let mut book = Book::default();
        let prepared = prepare(&mut book, path.clone());
        assert!(!prepared.path.starts_with(r"\\?\"));
        book.arm(&prepared.id, &blob(), &origin()).unwrap();
        let stage = book.requested(&blob(), &origin()).unwrap();
        assert!(stage.as_os_str().to_string_lossy().starts_with(r"\\?\"));
        fs::write(&stage, b"new-csv").unwrap();
        let callback_path = presentation_path(&stage).unwrap();
        assert_ne!(callback_path, stage);
        let event = book.finished(&blob(), Some(&callback_path), true).unwrap();
        assert_eq!(event.status, "saved");
        assert_eq!(event.path.as_deref(), Some(prepared.path.as_str()));
        assert_eq!(fs::read(&path).unwrap(), b"new-csv");
        assert_eq!(
            book.reveal_path(&prepared.id).unwrap(),
            path.canonicalize().unwrap()
        );
        assert!(!stage.exists());
    }

    #[cfg(windows)]
    #[test]
    fn windows_completion_rejects_other_and_missing_files() {
        let temp = Temp::new();
        let owned = temp.0.join("owned.csv");
        let other = temp.0.join("other.csv");
        fs::write(&owned, b"same").unwrap();
        fs::write(&other, b"same").unwrap();
        let canonical = owned.canonicalize().unwrap();
        assert!(completion_path_matches(&owned, &canonical));
        assert!(!completion_path_matches(&other, &canonical));
        assert!(!completion_path_matches(
            &temp.0.join("missing.csv"),
            &canonical
        ));
    }
}
