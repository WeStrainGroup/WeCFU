//! The native picker returns only the folder the user selected. Importing its
//! contents remains the responsibility of the existing authenticated backend.
use serde::Deserialize;
use std::{
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
};

use crate::{protocol, Shared};

#[derive(Clone, Copy, Debug, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Locale {
    En,
    #[serde(rename = "zh-CN")]
    Zh,
    Fr,
    Ru,
}

impl Locale {
    fn title(self) -> &'static str {
        match self {
            Self::En => "Choose a photo folder",
            Self::Zh => "选择照片文件夹",
            Self::Fr => "Choisir un dossier de photos",
            Self::Ru => "Выбрать папку с фотографиями",
        }
    }
}

#[derive(Default)]
pub struct Chooser(AtomicBool);

struct Choosing<'a>(&'a AtomicBool);

impl Chooser {
    fn begin(&self) -> Result<Choosing<'_>, String> {
        self.0
            .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
            .map_err(|_| "import_busy".to_string())?;
        Ok(Choosing(&self.0))
    }
}

impl Drop for Choosing<'_> {
    fn drop(&mut self) {
        self.0.store(false, Ordering::SeqCst);
    }
}

fn caller_allowed(
    label: &str,
    current: Option<&url::Url>,
    origin: &Option<String>,
    closing: bool,
) -> bool {
    label == "main" && !closing && current.is_some_and(|url| protocol::same_origin(url, origin))
}

fn authorized(window: &tauri::WebviewWindow, shared: &Shared) -> Result<String, String> {
    let origin = shared.origin.lock().unwrap().clone();
    if !caller_allowed(
        window.label(),
        window.url().ok().as_ref(),
        &origin,
        shared.shutdown.load(Ordering::SeqCst),
    ) {
        return Err("import_unavailable".into());
    }
    origin.ok_or_else(|| "import_unavailable".into())
}

fn selected_folder(path: Option<PathBuf>) -> Result<Option<String>, String> {
    let Some(path) = path else { return Ok(None) };
    if !path.is_absolute() {
        return Err("invalid_import_folder".into());
    }
    #[cfg(windows)]
    {
        use std::path::{Component, Prefix};
        // Preserve UNC and extended paths exactly. Device namespaces are not
        // folders for the import API, and must not be reinterpreted as one.
        if !matches!(
            path.components().next(),
            Some(Component::Prefix(prefix)) if matches!(prefix.kind(),
                Prefix::Disk(_) | Prefix::UNC(_, _) | Prefix::VerbatimDisk(_) | Prefix::VerbatimUNC(_, _))
        ) {
            return Err("invalid_import_folder".into());
        }
    }
    let text = path.to_str().ok_or("invalid_import_folder")?;
    if text.contains('\0') {
        return Err("invalid_import_folder".into());
    }
    // No lossy Unicode conversion, canonicalization, traversal or file reads.
    Ok(Some(text.to_owned()))
}

#[tauri::command]
pub async fn desktop_choose_import_folder(
    window: tauri::WebviewWindow,
    state: tauri::State<'_, Arc<Shared>>,
    locale: Locale,
) -> Result<Option<String>, String> {
    let origin = authorized(&window, &state)?;
    let _choosing = state.import_chooser.begin()?;
    let selected = rfd::AsyncFileDialog::new()
        .set_parent(&window)
        .set_title(locale.title())
        .set_can_create_directories(false)
        .pick_folder()
        .await;
    // The picker can outlive a session shutdown or a navigation. Never return
    // its selection to a page whose ownership changed while the dialog was open.
    if authorized(&window, &state)? != origin {
        return Err("import_unavailable".into());
    }
    selected_folder(selected.map(|folder| folder.path().to_owned()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_current_main_session_can_choose() {
        let origin = Some("http://127.0.0.1:54321".to_string());
        let current = url::Url::parse("http://127.0.0.1:54321/").unwrap();
        assert!(caller_allowed("main", Some(&current), &origin, false));
        assert!(!caller_allowed("other", Some(&current), &origin, false));
        assert!(!caller_allowed("main", Some(&current), &origin, true));
        assert!(!caller_allowed("main", Some(&current), &None, false));
        assert!(!caller_allowed("main", None, &origin, false));
        for address in [
            "http://127.0.0.1:54322/",
            "http://localhost:54321/",
            "https://127.0.0.1:54321/",
            "http://user@127.0.0.1:54321/",
            "file:///tmp/page.html",
            "tauri://localhost/index.html",
        ] {
            let other = url::Url::parse(address).unwrap();
            assert!(!caller_allowed("main", Some(&other), &origin, false));
        }
    }

    #[test]
    fn repeated_requests_are_rejected_and_cancel_releases_slot() {
        let chooser = Chooser::default();
        let pending = chooser.begin().unwrap();
        assert!(matches!(chooser.begin(), Err(error) if error == "import_busy"));
        assert_eq!(selected_folder(None).unwrap(), None);
        drop(pending);
        assert!(chooser.begin().is_ok());
    }

    #[test]
    fn slot_is_released_after_a_failed_selection() {
        let chooser = Chooser::default();
        {
            let _pending = chooser.begin().unwrap();
            assert!(selected_folder(Some(PathBuf::from("relative/folder"))).is_err());
        }
        assert!(chooser.begin().is_ok());
    }

    #[test]
    fn locale_only_selects_a_fixed_supported_title() {
        for language in ["en", "zh-CN", "fr", "ru"] {
            let locale: Locale = serde_json::from_value(serde_json::json!(language)).unwrap();
            assert!(!locale.title().is_empty());
        }
        for invalid in ["es", "ja", "zh", "Arbitrary dialog title", ""] {
            assert!(serde_json::from_value::<Locale>(serde_json::json!(invalid)).is_err());
        }
    }

    #[cfg(unix)]
    #[test]
    fn unicode_and_spaces_are_returned_without_reading_or_normalizing() {
        let path = "/not-created/照片 with spaces/папка";
        assert_eq!(
            selected_folder(Some(PathBuf::from(path))).unwrap(),
            Some(path.into())
        );
    }

    #[cfg(unix)]
    #[test]
    fn unrepresentable_paths_are_not_lossily_changed() {
        use std::os::unix::ffi::OsStringExt;
        let path = PathBuf::from(std::ffi::OsString::from_vec(b"/folder/\xff".to_vec()));
        assert!(selected_folder(Some(path)).is_err());
        assert!(selected_folder(Some(PathBuf::from("/folder/\0"))).is_err());
    }

    #[cfg(windows)]
    #[test]
    fn windows_unicode_unc_and_extended_paths_keep_exact_spelling() {
        for path in [
            r"C:\照片 with spaces\папка",
            r"\\server\share\照片 with spaces",
            r"\\?\C:\results.\照片",
            r"\\?\UNC\server\share\照片",
        ] {
            assert_eq!(
                selected_folder(Some(PathBuf::from(path))).unwrap(),
                Some(path.into())
            );
        }
    }

    #[cfg(windows)]
    #[test]
    fn windows_relative_device_and_unrepresentable_paths_are_rejected() {
        use std::os::windows::ffi::OsStringExt;
        for path in [
            r"C:relative",
            r"\rooted",
            r"\\.\COM1",
            r"\\?\GLOBALROOT\Device\HarddiskVolume1",
        ] {
            assert!(selected_folder(Some(PathBuf::from(path))).is_err());
        }
        let path = PathBuf::from(std::ffi::OsString::from_wide(&[67, 58, 92, 0xD800]));
        assert!(selected_folder(Some(path)).is_err());
    }
}
