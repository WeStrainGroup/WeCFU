fn main() {
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "boot_status",
            "desktop_export_prepare",
            "desktop_export_arm",
            "desktop_export_cancel",
            "desktop_export_reveal",
            "desktop_choose_import_folder",
        ]),
    ))
    .expect("failed to build WeCFU desktop permissions");
}
