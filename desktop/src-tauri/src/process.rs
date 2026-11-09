//! The shell owns exactly one host and its descendants, never an existing server.
use crate::manifest::Resources;
use std::{
    ffi::OsString,
    io::{Read, Write},
    path::{Path, PathBuf},
};

struct Workspace {
    path: Option<PathBuf>,
}
impl Workspace {
    fn new() -> Result<Self, String> {
        let path = std::env::temp_dir().join(format!(
            "wecfu-desktop-session-{}",
            uuid::Uuid::new_v4().simple()
        ));
        let mut builder = std::fs::DirBuilder::new();
        #[cfg(unix)]
        {
            use std::os::unix::fs::DirBuilderExt;
            builder.mode(0o700);
        }
        builder
            .create(&path)
            .map_err(|_| "Cannot create the private local workspace.".to_string())?;
        Ok(Self { path: Some(path) })
    }
    fn path(&self) -> &Path {
        self.path.as_deref().expect("active workspace")
    }
    fn cleanup(&mut self) -> Result<(), String> {
        let Some(path) = self.path.as_ref() else {
            return Ok(());
        };
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(3);
        loop {
            match std::fs::remove_dir_all(path) {
                Ok(()) => break,
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => break,
                Err(_) if std::time::Instant::now() < deadline => {
                    std::thread::sleep(std::time::Duration::from_millis(25))
                }
                Err(_) => return Err("The local session files could not be removed.".into()),
            }
        }
        self.path = None;
        Ok(())
    }
    fn persist_if_processes_alive(&mut self) {
        self.path = None;
    }
}
impl Drop for Workspace {
    fn drop(&mut self) {
        let _ = self.cleanup();
    }
}

pub struct Spawned {
    pub process: Process,
    pub stdin: Box<dyn Write + Send>,
    pub stdout: Box<dyn Read + Send>,
    pub stderr: Box<dyn Read + Send>,
}

fn environment() -> Vec<(OsString, OsString)> {
    let mut values: Vec<_> = std::env::vars_os()
        .filter(|(key, _)| {
            let key = key.to_string_lossy().to_ascii_uppercase();
            !key.starts_with("WECFU_")
                && !matches!(
                    key.as_str(),
                    "PYTHONPATH" | "PYTHONHOME" | "PYTHONNOUSERSITE" | "PYTHONDONTWRITEBYTECODE"
                )
        })
        .collect();
    values.push(("PYTHONNOUSERSITE".into(), "1".into()));
    values.push(("PYTHONDONTWRITEBYTECODE".into(), "1".into()));
    values
}

fn arguments(resources: &Resources, session: &str, workspace: &Path) -> Vec<OsString> {
    vec![
        "-I".into(),
        "-B".into(),
        resources.entrypoint.as_os_str().to_owned(),
        "--resource-root".into(),
        resources.root.as_os_str().to_owned(),
        "--session-id".into(),
        session.into(),
        "--workspace-root".into(),
        workspace.as_os_str().to_owned(),
    ]
}

#[cfg(unix)]
pub use posix::spawn;
#[cfg(unix)]
pub use posix::Process;
#[cfg(windows)]
pub use windows::spawn;
#[cfg(windows)]
pub use windows::Process;

#[cfg(unix)]
mod posix {
    use super::*;
    use std::{
        os::unix::process::CommandExt,
        process::{Child, Command, Stdio},
        thread,
        time::{Duration, Instant},
    };

    pub struct Process {
        child: Child,
        group: i32,
        stopped: bool,
        workspace: Workspace,
    }

    pub fn spawn(resources: &Resources, session: &str) -> Result<Spawned, String> {
        let workspace = Workspace::new()?;
        let mut child = Command::new(&resources.python)
            .args(arguments(resources, session, workspace.path()))
            .current_dir(&resources.root)
            .env_clear()
            .envs(environment())
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .process_group(0)
            .spawn()
            .map_err(|e| format!("Cannot start the bundled Python runtime: {e}"))?;
        let stdin = Box::new(child.stdin.take().unwrap());
        let stdout = Box::new(child.stdout.take().unwrap());
        let stderr = Box::new(child.stderr.take().unwrap());
        let group = child.id() as i32;
        Ok(Spawned {
            process: Process {
                child,
                group,
                stopped: false,
                workspace,
            },
            stdin,
            stdout,
            stderr,
        })
    }

    impl Process {
        pub fn try_wait(&mut self) -> Result<Option<i32>, String> {
            self.child
                .try_wait()
                .map(|status| status.map(|s| s.code().unwrap_or(-1)))
                .map_err(|e| e.to_string())
        }

        pub fn force_stop(&mut self) -> Result<(), String> {
            if self.stopped {
                return self.workspace.cleanup();
            }
            // Desktop workers inherit this group; ordinary CLI worker groups are separate.
            let result = unsafe { libc::kill(-self.group, libc::SIGKILL) };
            if result != 0 && std::io::Error::last_os_error().raw_os_error() != Some(libc::ESRCH) {
                return Err("Could not stop the local service process group.".into());
            }
            let deadline = Instant::now() + Duration::from_secs(3);
            while Instant::now() < deadline {
                let parent_done = self.try_wait()?.is_some();
                let group_done = unsafe { libc::kill(-self.group, 0) } != 0
                    && std::io::Error::last_os_error().raw_os_error() == Some(libc::ESRCH);
                if parent_done && group_done {
                    self.stopped = true;
                    return self.workspace.cleanup();
                }
                thread::sleep(Duration::from_millis(25));
            }
            Err("The local service did not exit after termination.".into())
        }
    }

    impl Drop for Process {
        fn drop(&mut self) {
            if self.force_stop().is_err() && !self.stopped {
                // Never remove files while a process might still be writing them.
                self.workspace.persist_if_processes_alive();
            }
        }
    }

    #[cfg(test)]
    mod tests {
        use super::*;
        #[test]
        fn termination_reaps_owned_host_and_descendant_but_not_other_group() {
            let sentinel = Command::new("/bin/sleep")
                .arg("60")
                .process_group(0)
                .spawn()
                .unwrap();
            let mut sentinel = Process {
                group: sentinel.id() as i32,
                child: sentinel,
                stopped: false,
                workspace: Workspace::new().unwrap(),
            };
            let mut child = Command::new("/bin/sh")
                .args(["-c", "sleep 60 & echo ready; wait"])
                .process_group(0)
                .stdout(Stdio::piped())
                .spawn()
                .unwrap();
            let mut pipe = std::io::BufReader::new(child.stdout.take().unwrap());
            let mut line = String::new();
            std::io::BufRead::read_line(&mut pipe, &mut line).unwrap();
            assert_eq!(line.trim(), "ready");
            let mut owned = Process {
                group: child.id() as i32,
                child,
                stopped: false,
                workspace: Workspace::new().unwrap(),
            };
            let session_path = owned.workspace.path().to_owned();
            std::fs::write(
                session_path.join("synthetic-upload.png"),
                b"synthetic private bytes",
            )
            .unwrap();
            let (send, recv) = std::sync::mpsc::channel();
            thread::spawn(move || {
                let mut remainder = Vec::new();
                let _ = send.send(pipe.read_to_end(&mut remainder));
            });
            owned.force_stop().unwrap();
            assert!(owned.try_wait().unwrap().is_some());
            // sleep inherited stdout: EOF confirms it was retired along with the host.
            assert!(recv.recv_timeout(Duration::from_secs(3)).unwrap().is_ok());
            assert!(sentinel.try_wait().unwrap().is_none());
            assert!(!session_path.exists());
            assert!(sentinel.workspace.path().is_dir());
            owned.force_stop().unwrap();
        }
    }
}

#[cfg(windows)]
mod windows {
    use super::*;
    use std::{
        fs::File,
        mem::{size_of, zeroed},
        os::windows::{
            ffi::OsStrExt,
            io::{AsRawHandle, FromRawHandle, OwnedHandle},
        },
        ptr,
    };
    use windows_sys::Win32::{
        Foundation::{SetHandleInformation, HANDLE, HANDLE_FLAG_INHERIT},
        Security::SECURITY_ATTRIBUTES,
        System::{
            JobObjects::{
                AssignProcessToJobObject, CreateJobObjectW, JobObjectBasicAccountingInformation,
                JobObjectExtendedLimitInformation, QueryInformationJobObject,
                SetInformationJobObject, TerminateJobObject,
                JOBOBJECT_BASIC_ACCOUNTING_INFORMATION, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
                JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
            },
            Pipes::CreatePipe,
            Threading::{
                CreateProcessW, GetExitCodeProcess, ResumeThread, TerminateProcess,
                WaitForSingleObject, CREATE_NO_WINDOW, CREATE_SUSPENDED,
                CREATE_UNICODE_ENVIRONMENT, PROCESS_INFORMATION, STARTF_USESTDHANDLES,
                STARTUPINFOW,
            },
        },
    };

    pub struct Process {
        handle: OwnedHandle,
        job: OwnedHandle,
        stopped: bool,
        workspace: Workspace,
    }

    fn handle(value: &OwnedHandle) -> HANDLE {
        value.as_raw_handle() as HANDLE
    }
    fn last_error(label: &str) -> String {
        format!("{label}: {}", std::io::Error::last_os_error())
    }
    fn wide(value: &std::ffi::OsStr) -> Vec<u16> {
        value.encode_wide().chain(Some(0)).collect()
    }

    fn pipe(parent_reads: bool) -> Result<(OwnedHandle, OwnedHandle), String> {
        unsafe {
            let mut read = ptr::null_mut();
            let mut write = ptr::null_mut();
            let attributes = SECURITY_ATTRIBUTES {
                nLength: size_of::<SECURITY_ATTRIBUTES>() as u32,
                lpSecurityDescriptor: ptr::null_mut(),
                bInheritHandle: 1,
            };
            if CreatePipe(&mut read, &mut write, &attributes, 0) == 0 {
                return Err(last_error("Cannot create service pipe"));
            }
            let read = OwnedHandle::from_raw_handle(read);
            let write = OwnedHandle::from_raw_handle(write);
            let parent = if parent_reads { &read } else { &write };
            if SetHandleInformation(handle(parent), HANDLE_FLAG_INHERIT, 0) == 0 {
                return Err(last_error("Cannot secure service pipe"));
            }
            Ok((read, write))
        }
    }

    fn quoted(value: &std::ffi::OsStr) -> Vec<u16> {
        let mut out = vec![b'"' as u16];
        let mut slashes = 0;
        for unit in value.encode_wide() {
            if unit == b'\\' as u16 {
                slashes += 1;
                continue;
            }
            if unit == b'"' as u16 {
                out.extend(std::iter::repeat_n(b'\\' as u16, slashes * 2 + 1));
            } else {
                out.extend(std::iter::repeat_n(b'\\' as u16, slashes));
            }
            slashes = 0;
            out.push(unit);
        }
        out.extend(std::iter::repeat_n(b'\\' as u16, slashes * 2));
        out.push(b'"' as u16);
        out
    }

    pub fn spawn(resources: &Resources, session: &str) -> Result<Spawned, String> {
        let workspace = Workspace::new()?;
        unsafe {
            let job_raw = CreateJobObjectW(ptr::null(), ptr::null());
            if job_raw.is_null() {
                return Err(last_error("Cannot create service Job Object"));
            }
            let job = OwnedHandle::from_raw_handle(job_raw);
            let mut limits: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = zeroed();
            limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            if SetInformationJobObject(
                handle(&job),
                JobObjectExtendedLimitInformation,
                &limits as *const _ as *const _,
                size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
            ) == 0
            {
                return Err(last_error("Cannot configure service Job Object"));
            }
            let (stdin_child, stdin_parent) = pipe(false)?;
            let (stdout_parent, stdout_child) = pipe(true)?;
            let (stderr_parent, stderr_child) = pipe(true)?;
            let mut info: STARTUPINFOW = zeroed();
            info.cb = size_of::<STARTUPINFOW>() as u32;
            info.dwFlags = STARTF_USESTDHANDLES;
            info.hStdInput = handle(&stdin_child);
            info.hStdOutput = handle(&stdout_child);
            info.hStdError = handle(&stderr_child);
            let mut process: PROCESS_INFORMATION = zeroed();
            let application = wide(resources.python.as_os_str());
            let directory = wide(resources.root.as_os_str());
            let mut command = quoted(resources.python.as_os_str());
            for argument in arguments(resources, session, workspace.path()) {
                command.push(b' ' as u16);
                command.extend(quoted(&argument));
            }
            command.push(0);
            let mut variables = environment();
            variables.sort_by_key(|(key, _)| key.to_string_lossy().to_ascii_uppercase());
            let mut environment = Vec::<u16>::new();
            for (key, value) in variables {
                environment.extend(key.encode_wide());
                environment.push(b'=' as u16);
                environment.extend(value.encode_wide());
                environment.push(0);
            }
            environment.push(0);
            if CreateProcessW(
                application.as_ptr(),
                command.as_mut_ptr(),
                ptr::null(),
                ptr::null(),
                1,
                CREATE_SUSPENDED | CREATE_NO_WINDOW | CREATE_UNICODE_ENVIRONMENT,
                environment.as_ptr() as *const _,
                directory.as_ptr(),
                &info,
                &mut process,
            ) == 0
            {
                return Err(last_error("Cannot start the bundled Python runtime"));
            }
            let process_handle = OwnedHandle::from_raw_handle(process.hProcess);
            let thread = OwnedHandle::from_raw_handle(process.hThread);
            // No Python code executes before the entire tree belongs to this Job.
            if AssignProcessToJobObject(handle(&job), handle(&process_handle)) == 0 {
                let error = last_error("Cannot own the local service process tree");
                TerminateProcess(handle(&process_handle), 1);
                WaitForSingleObject(handle(&process_handle), 3000);
                return Err(error);
            }
            let mut process = Process {
                handle: process_handle,
                job,
                stopped: false,
                workspace,
            };
            if ResumeThread(handle(&thread)) == u32::MAX {
                let error = last_error("Cannot resume the local service");
                process.force_stop()?;
                return Err(error);
            }
            drop(thread);
            drop(stdin_child);
            drop(stdout_child);
            drop(stderr_child);
            Ok(Spawned {
                process,
                stdin: Box::new(File::from(stdin_parent)),
                stdout: Box::new(File::from(stdout_parent)),
                stderr: Box::new(File::from(stderr_parent)),
            })
        }
    }

    impl Process {
        fn active_processes(&self) -> Result<u32, String> {
            let mut accounting: JOBOBJECT_BASIC_ACCOUNTING_INFORMATION = unsafe { zeroed() };
            if unsafe {
                QueryInformationJobObject(
                    handle(&self.job),
                    JobObjectBasicAccountingInformation,
                    &mut accounting as *mut _ as *mut _,
                    size_of::<JOBOBJECT_BASIC_ACCOUNTING_INFORMATION>() as u32,
                    ptr::null_mut(),
                )
            } == 0
            {
                return Err(last_error("Cannot inspect local service processes"));
            }
            Ok(accounting.ActiveProcesses)
        }
        pub fn try_wait(&mut self) -> Result<Option<i32>, String> {
            let mut code = 0;
            if unsafe { GetExitCodeProcess(handle(&self.handle), &mut code) } == 0 {
                return Err(last_error("Cannot read service exit status"));
            }
            Ok(if code == 259 { None } else { Some(code as i32) })
        }

        pub fn force_stop(&mut self) -> Result<(), String> {
            if self.stopped {
                return self.workspace.cleanup();
            }
            unsafe {
                if TerminateJobObject(handle(&self.job), 1) == 0 {
                    return Err(last_error("Cannot stop local service processes"));
                }
                if WaitForSingleObject(handle(&self.handle), 3000) != 0 {
                    return Err("The local service did not exit after termination.".into());
                }
            }
            let deadline = std::time::Instant::now() + std::time::Duration::from_secs(3);
            while self.active_processes()? != 0 {
                if std::time::Instant::now() >= deadline {
                    return Err("Local service descendants did not exit after termination.".into());
                }
                std::thread::sleep(std::time::Duration::from_millis(10));
            }
            self.stopped = true;
            self.workspace.cleanup()
        }
    }

    impl Drop for Process {
        fn drop(&mut self) {
            if self.force_stop().is_err() && !self.stopped {
                self.workspace.persist_if_processes_alive();
            }
        }
    }

    #[cfg(test)]
    mod tests {
        use super::*;
        #[test]
        fn command_arguments_are_quoted_without_command_interpretation() {
            assert_eq!(
                String::from_utf16(&quoted(std::ffi::OsStr::new("C:\\test folder\\"))).unwrap(),
                "\"C:\\test folder\\\\\""
            );
            assert_eq!(
                String::from_utf16(&quoted(std::ffi::OsStr::new("a\"b"))).unwrap(),
                "\"a\\\"b\""
            );
        }
        #[test]
        fn native_job_owns_tree_before_execution_and_retires_only_its_session() {
            // CI provides a real Python path; this is an OS ownership/pipe test,
            // not a model or user-photo test.
            let python = std::env::var_os("WECFU_TEST_PYTHON")
                .expect("Set WECFU_TEST_PYTHON to Python for Windows native ownership tests");
            let root =
                std::env::temp_dir().join(format!("WeCFU native тест {}", uuid::Uuid::new_v4()));
            std::fs::create_dir_all(&root).unwrap();
            struct Cleanup(std::path::PathBuf);
            impl Drop for Cleanup {
                fn drop(&mut self) {
                    let _ = std::fs::remove_dir_all(&self.0);
                }
            }
            let _cleanup = Cleanup(root.clone());
            let entrypoint = root.join("entry with spaces.py");
            std::fs::write(&entrypoint, r#"import ctypes,json,subprocess,sys,time
from ctypes import wintypes
kernel=ctypes.WinDLL('kernel32', use_last_error=True)
kernel.GetCurrentProcess.restype=wintypes.HANDLE
kernel.IsProcessInJob.argtypes=[wintypes.HANDLE,wintypes.HANDLE,ctypes.POINTER(wintypes.BOOL)]
inside=wintypes.BOOL()
assert kernel.IsProcessInJob(kernel.GetCurrentProcess(),None,ctypes.byref(inside))
child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],stdout=sys.stdout,stderr=sys.stderr,stdin=subprocess.DEVNULL)
print(json.dumps({'inside_job':bool(inside.value),'argv':sys.argv[1:]}),flush=True)
line=sys.stdin.readline()
print(json.dumps({'control':json.loads(line) if line else None}),flush=True)
time.sleep(60)
"#).unwrap();
            let resources = Resources {
                root,
                entrypoint,
                python: python.into(),
                version: "test".into(),
            };
            let mut first = spawn(&resources, "session-one").unwrap();
            let mut second = spawn(&resources, "session-two").unwrap();
            let session_path = first.process.workspace.path().to_owned();
            std::fs::write(
                session_path.join("synthetic-upload.png"),
                b"synthetic private bytes",
            )
            .unwrap();
            fn read_ready(
                pipe: Box<dyn Read + Send>,
            ) -> (std::io::BufReader<Box<dyn Read + Send>>, serde_json::Value) {
                use std::io::BufRead;
                let mut pipe = std::io::BufReader::new(pipe);
                let mut line = String::new();
                pipe.read_line(&mut line).unwrap();
                (pipe, serde_json::from_str(&line).unwrap())
            }
            let (mut first_pipe, ready) = read_ready(first.stdout);
            let (_second_pipe, second_ready) = read_ready(second.stdout);
            assert_eq!(ready["inside_job"], true);
            assert_eq!(second_ready["inside_job"], true);
            assert_eq!(
                ready["argv"],
                serde_json::json!([
                    "--resource-root",
                    resources.root.to_str().unwrap(),
                    "--session-id",
                    "session-one",
                    "--workspace-root",
                    session_path.to_str().unwrap()
                ])
            );
            assert!(first.process.active_processes().unwrap() >= 2);
            writeln!(
                first.stdin,
                "{{\"command\":\"shutdown\",\"session_id\":\"session-one\"}}"
            )
            .unwrap();
            first.stdin.flush().unwrap();
            let mut echoed = String::new();
            std::io::BufRead::read_line(&mut first_pipe, &mut echoed).unwrap();
            assert_eq!(
                serde_json::from_str::<serde_json::Value>(&echoed).unwrap()["control"]
                    ["session_id"],
                "session-one"
            );
            let (send, recv) = std::sync::mpsc::channel();
            std::thread::spawn(move || {
                let mut bytes = Vec::new();
                let _ = send.send(first_pipe.read_to_end(&mut bytes));
            });
            first.process.force_stop().unwrap();
            assert_eq!(first.process.active_processes().unwrap(), 0);
            assert!(recv
                .recv_timeout(std::time::Duration::from_secs(3))
                .unwrap()
                .is_ok());
            assert!(second.process.try_wait().unwrap().is_none());
            assert!(!session_path.exists());
            assert!(second.process.workspace.path().is_dir());
            second.process.force_stop().unwrap();
            assert_eq!(second.process.active_processes().unwrap(), 0);
        }
    }
}
