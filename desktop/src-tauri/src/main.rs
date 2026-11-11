#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod exports;
mod imports;
mod manifest;
mod process;
mod protocol;

use serde::Serialize;
use std::{
    collections::VecDeque,
    io::{BufRead, BufReader, Read, Write},
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, Ordering},
        mpsc, Arc, Mutex,
    },
    thread,
    time::{Duration, Instant},
};
use tauri::webview::{DownloadEvent, NewWindowResponse};
use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder, WindowEvent};

#[derive(Clone, Serialize)]
struct BootStatus {
    phase: String,
    title: String,
    message: String,
    detail: String,
}

struct Shared {
    status: Mutex<BootStatus>,
    origin: Mutex<Option<String>>,
    exports: Mutex<exports::Book>,
    import_chooser: imports::Chooser,
    shutdown: AtomicBool,
    host_done: AtomicBool,
}

impl Shared {
    fn new() -> Self {
        Self {
            status: Mutex::new(BootStatus {
                phase: "starting".into(),
                title: "Starting WeCFU".into(),
                message: "Checking the bundled runtime.".into(),
                detail: String::new(),
            }),
            origin: Mutex::new(None),
            exports: Mutex::new(exports::Book::default()),
            import_chooser: imports::Chooser::default(),
            shutdown: AtomicBool::new(false),
            host_done: AtomicBool::new(false),
        }
    }
    fn status(&self, phase: &str, title: &str, message: &str, detail: String) {
        *self.status.lock().unwrap() = BootStatus {
            phase: phase.into(),
            title: title.into(),
            message: message.into(),
            detail,
        };
    }
}

#[tauri::command]
fn boot_status(state: tauri::State<'_, Arc<Shared>>) -> BootStatus {
    state.status.lock().unwrap().clone()
}

fn asset_url() -> url::Url {
    if cfg!(windows) {
        "http://tauri.localhost/index.html"
    } else {
        "tauri://localhost/index.html"
    }
    .parse()
    .unwrap()
}

fn owned_asset(url: &url::Url) -> bool {
    let base = asset_url();
    url.scheme() == base.scheme()
        && url.host_str() == base.host_str()
        && url.port() == base.port()
        && url.path() == "/index.html"
}

fn external(url: &url::Url) {
    if protocol::external_url(url) {
        let target = url.as_str().to_owned();
        thread::spawn(move || {
            let _ = open::that_detached(target);
        });
    }
}

fn request_shutdown(app: &tauri::AppHandle, shared: &Arc<Shared>) {
    shared.shutdown.store(true, Ordering::SeqCst);
    shared.exports.lock().unwrap().cleanup();
    shared.status(
        "stopping",
        "Closing WeCFU",
        "Finishing the local session.",
        String::new(),
    );
    if shared.host_done.load(Ordering::SeqCst) {
        app.exit(0);
    }
}

fn drain_stderr(mut source: Box<dyn Read + Send>, tail: Arc<Mutex<VecDeque<u8>>>) {
    let mut buffer = [0u8; 2048];
    while let Ok(n) = source.read(&mut buffer) {
        if n == 0 {
            break;
        }
        let mut tail = tail.lock().unwrap();
        tail.extend(&buffer[..n]);
        while tail.len() > 16 * 1024 {
            tail.pop_front();
        }
    }
}

fn read_protocol(
    source: Box<dyn Read + Send>,
    tx: mpsc::SyncSender<Result<protocol::HostEvent, String>>,
) {
    let mut input = BufReader::new(source);
    loop {
        let mut line = Vec::new();
        let count =
            Read::take(&mut input, (protocol::MAX_LINE + 1) as u64).read_until(b'\n', &mut line);
        match count {
            Ok(0) => break,
            Ok(n) if n <= protocol::MAX_LINE && line.last() == Some(&b'\n') => {
                let parsed = serde_json::from_slice(&line)
                    .map_err(|_| "The local service returned an invalid startup message.".into());
                if tx.send(parsed).is_err() {
                    break;
                }
            }
            _ => {
                let _ = tx.send(Err(
                    "The local service startup message was incomplete or too large.".into(),
                ));
                break;
            }
        }
    }
}

fn run_host(
    app: &tauri::AppHandle,
    shared: &Arc<Shared>,
    root: PathBuf,
    session: &str,
) -> Result<(), String> {
    let resources = manifest::verify(&root, || shared.shutdown.load(Ordering::SeqCst))?;
    if shared.shutdown.load(Ordering::SeqCst) {
        return Ok(());
    }
    shared.status(
        "starting",
        "Starting WeCFU",
        "Starting the local workspace.",
        String::new(),
    );
    let process::Spawned {
        mut process,
        mut stdin,
        stdout,
        stderr,
    } = process::spawn(&resources, session)?;
    let tail = Arc::new(Mutex::new(VecDeque::new()));
    let stderr_tail = tail.clone();
    thread::spawn(move || drain_stderr(stderr, stderr_tail));
    let (tx, rx) = mpsc::sync_channel(2);
    thread::spawn(move || read_protocol(stdout, tx));
    let started = Instant::now();
    let mut ready = false;
    let outcome = loop {
        if shared.shutdown.load(Ordering::SeqCst) {
            let shutdown = serde_json::json!({"command":"shutdown", "session_id":session});
            let _ = writeln!(stdin, "{shutdown}");
            let _ = stdin.flush();
            drop(stdin); // EOF is also a shutdown request; never leave a control pipe open.
            let deadline = Instant::now() + Duration::from_secs(10);
            while Instant::now() < deadline {
                if process.try_wait()?.is_some() {
                    break;
                }
                thread::sleep(Duration::from_millis(50));
            }
            break Ok(());
        }
        if let Some(code) = process.try_wait()? {
            let bytes: Vec<_> = tail.lock().unwrap().iter().copied().collect();
            let detail = String::from_utf8_lossy(&bytes).replace(session, "[session]");
            break Err(format!(
                "The local service stopped (exit {code}).\n{}",
                detail
                    .chars()
                    .rev()
                    .take(2000)
                    .collect::<String>()
                    .chars()
                    .rev()
                    .collect::<String>()
            ));
        }
        if !ready && started.elapsed() > Duration::from_secs(120) {
            break Err("The bundled service did not become ready within two minutes. Close WeCFU and retry.".into());
        }
        match rx.recv_timeout(Duration::from_millis(100)) {
            Ok(event) if !ready => {
                let url = protocol::ready_url(event?, session, &resources.version)?;
                let origin = url.origin().ascii_serialization();
                app.add_capability(
                    tauri::ipc::CapabilityBuilder::new("native-export")
                        .local(false)
                        .window("main")
                        .remote(format!("{origin}/*"))
                        .permission("allow-desktop-export-prepare")
                        .permission("allow-desktop-export-arm")
                        .permission("allow-desktop-export-cancel")
                        .permission("allow-desktop-export-reveal")
                        .permission("allow-desktop-choose-import-folder"),
                )
                .map_err(|_| "Cannot authorize native application controls.".to_string())?;
                *shared.origin.lock().unwrap() = Some(origin);
                let window = app
                    .get_webview_window("main")
                    .ok_or("The application window was closed.")?;
                window
                    .navigate(url)
                    .map_err(|_| "Cannot open the local application window.".to_string())?;
                shared.status("ready", "WeCFU", "Ready", String::new());
                ready = true;
            }
            Ok(Err(error)) => break Err(error),
            Ok(Ok(_)) => {
                break Err("The local service sent an unexpected duplicate startup message.".into())
            }
            Err(mpsc::RecvTimeoutError::Timeout) => (),
            Err(mpsc::RecvTimeoutError::Disconnected) => {
                // Give the process one bounded scheduling interval to expose its exit status.
                thread::sleep(Duration::from_millis(50));
                break Err("The local service closed its control stream.".into());
            }
        }
    };
    // Also retire descendants after an orderly parent exit. This only owns this invocation.
    process.force_stop()?;
    outcome
}

#[derive(Debug, PartialEq)]
enum Completion {
    Exit,
    ShowError,
    None,
}

fn record_completion(shared: &Shared, session: &str, result: Result<(), String>) -> Completion {
    shared.host_done.store(true, Ordering::SeqCst);
    let closing = shared.shutdown.load(Ordering::SeqCst);
    if closing && result.is_ok() {
        return Completion::Exit;
    }
    if let Err(detail) = result {
        shared.shutdown.store(false, Ordering::SeqCst);
        shared.status("error",
            if closing { "Unable to finish the local session" } else { "Unable to start WeCFU" },
            if closing { "Some local processes or session files could not be cleared. Review the details before closing this window." }
            else { "Close this window and reopen the app. If a bundled file is missing, reinstall the complete application." },
            detail.replace(session, "[session]"));
        *shared.origin.lock().unwrap() = None;
        return Completion::ShowError;
    }
    Completion::None
}

fn supervise(app: tauri::AppHandle, shared: Arc<Shared>, root: PathBuf) {
    // A per-launch capability. It stays in the child pipe/webview, never in logs or saved UI state.
    let session = uuid::Uuid::new_v4().simple().to_string();
    let result = run_host(&app, &shared, root, &session);
    match record_completion(&shared, &session, result) {
        Completion::Exit => app.exit(0),
        Completion::ShowError => {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.navigate(asset_url());
            }
        }
        Completion::None => (),
    }
}

#[cfg(test)]
mod lifecycle_tests {
    use super::*;
    #[test]
    fn cleanup_failure_remains_visible_instead_of_successful_exit() {
        let shared = Shared::new();
        shared.shutdown.store(true, Ordering::SeqCst);
        *shared.origin.lock().unwrap() = Some("http://127.0.0.1:12345".into());
        assert_eq!(
            record_completion(&shared, "secret", Err("cleanup failed for secret".into())),
            Completion::ShowError
        );
        assert!(!shared.shutdown.load(Ordering::SeqCst));
        assert!(shared.host_done.load(Ordering::SeqCst));
        assert!(shared.origin.lock().unwrap().is_none());
        let status = shared.status.lock().unwrap();
        assert_eq!(status.phase, "error");
        assert!(status.title.contains("finish"));
        assert_eq!(status.detail, "cleanup failed for [session]");
    }
    #[test]
    fn orderly_shutdown_exits_and_unsolicited_failure_does_not() {
        let shared = Shared::new();
        shared.shutdown.store(true, Ordering::SeqCst);
        assert_eq!(
            record_completion(&shared, "secret", Ok(())),
            Completion::Exit
        );
        let shared = Shared::new();
        assert_eq!(
            record_completion(&shared, "secret", Err("host stopped".into())),
            Completion::ShowError
        );
    }
}

fn main() {
    let shared = Arc::new(Shared::new());
    let setup_state = shared.clone();
    let app = tauri::Builder::default()
        .manage(shared.clone())
        .invoke_handler(tauri::generate_handler![
            boot_status,
            exports::desktop_export_prepare,
            exports::desktop_export_arm,
            exports::desktop_export_cancel,
            exports::desktop_export_reveal,
            imports::desktop_choose_import_folder
        ])
        .setup(move |app| {
            let navigation = setup_state.clone();
            let downloads = setup_state.clone();
            let window =
                WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                    .title("WeCFU")
                    .inner_size(1320.0, 880.0)
                    .min_inner_size(960.0, 640.0)
                    .incognito(true)
                    .initialization_script(format!(
                "window.__WECFU_DESKTOP_EXPORT__=true;window.__WECFU_DESKTOP_IMPORT__=true;window.__WECFU_DESKTOP_PLATFORM__={};",
                serde_json::to_string(if cfg!(target_os = "macos") {
                    "macos"
                } else if cfg!(windows) {
                    "windows"
                } else {
                    "linux"
                })
                .unwrap()
            ))
                    .disable_drag_drop_handler()
                    .on_navigation(move |url| {
                        if owned_asset(url)
                            || protocol::same_origin(url, &navigation.origin.lock().unwrap())
                        {
                            true
                        } else {
                            external(url);
                            false
                        }
                    })
                    .on_new_window(|url, _| {
                        external(&url);
                        NewWindowResponse::Deny
                    })
                    .on_download(move |webview, event| {
                        match event {
                            DownloadEvent::Requested { url, destination } => {
                                let origin = downloads.origin.lock().unwrap().clone();
                                let owned = webview
                                    .url()
                                    .is_ok_and(|current| protocol::same_origin(&current, &origin));
                                if !owned || downloads.shutdown.load(Ordering::SeqCst) {
                                    return false;
                                }
                                let Some(target) =
                                    downloads.exports.lock().unwrap().requested(&url, &origin)
                                else {
                                    return false;
                                };
                                *destination = target;
                            }
                            DownloadEvent::Finished { url, path, success } => {
                                let result = downloads.exports.lock().unwrap().finished(
                                    &url,
                                    path.as_deref(),
                                    success,
                                );
                                if let Some(event) = result {
                                    exports::notify(&webview, &event);
                                }
                            }
                            _ => (),
                        }
                        true
                    })
                    .build()?;
            let close_app = app.handle().clone();
            let closing = setup_state.clone();
            window.on_window_event(move |event| {
                if let WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    request_shutdown(&close_app, &closing);
                }
            });
            let resources = app.path().resource_dir()?.join("bundle");
            #[cfg(debug_assertions)]
            let resources = std::env::var_os("WECFU_DESKTOP_RESOURCE_ROOT")
                .map(PathBuf::from)
                .unwrap_or(resources);
            let handle = app.handle().clone();
            let state = setup_state.clone();
            thread::spawn(move || supervise(handle, state, resources));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("Unable to construct the WeCFU desktop window");
    let after_exit = shared.clone();
    let code = app.run_return(move |handle, event| {
        if let RunEvent::ExitRequested { api, .. } = event {
            if !shared.host_done.load(Ordering::SeqCst) {
                api.prevent_exit();
                request_shutdown(handle, &shared);
            }
        }
    });
    // run_return consumes the runtime. Retry only our exact staging paths after
    // the event loop returns; a failed cleanup must not turn into a successful save.
    let deadline = Instant::now() + Duration::from_secs(2);
    let clean = loop {
        if after_exit.exports.lock().unwrap().cleanup() {
            break true;
        }
        if Instant::now() >= deadline {
            break false;
        }
        thread::sleep(Duration::from_millis(50));
    };
    if !clean {
        eprintln!("An incomplete export could not be removed.");
    }
    std::process::exit(if clean { code } else { 1 });
}
