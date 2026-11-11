//! Keep the host supervisor alive until its owned processes and files are retired.
use std::{
    sync::Mutex,
    thread::{self, JoinHandle},
};

#[derive(Default)]
pub struct Supervisor {
    worker: Mutex<Option<JoinHandle<Result<(), String>>>>,
    outcome: Mutex<Option<Result<(), String>>>,
}

impl Supervisor {
    pub fn start(&self, work: impl FnOnce() -> Result<(), String> + Send + 'static) {
        let mut worker = self.worker.lock().unwrap();
        assert!(worker.is_none(), "the host supervisor starts only once");
        *worker = Some(thread::spawn(work));
    }

    /// Call only when the event loop is ending, after signalling host shutdown.
    /// The worker must not wait for UI callbacks. No mutex is held while joining.
    pub fn finish(&self) -> Result<(), String> {
        let worker = self.worker.lock().unwrap().take();
        if let Some(worker) = worker {
            let outcome = worker.join().unwrap_or_else(|_| {
                Err("The local service supervisor stopped unexpectedly.".into())
            });
            *self.outcome.lock().unwrap() = Some(outcome);
        }
        self.outcome.lock().unwrap().clone().unwrap_or(Ok(()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        sync::{mpsc, Arc},
        time::Duration,
    };

    #[test]
    fn exit_waits_for_worker_cleanup_without_running_queued_ui() {
        let supervisor = Arc::new(Supervisor::default());
        let (clean_tx, clean_rx) = mpsc::channel();
        let (ui_tx, ui_rx) = mpsc::channel();
        let (done_tx, done_rx) = mpsc::channel();
        supervisor.start(move || {
            clean_rx.recv().unwrap();
            // Production queues UI work but never waits for it to run.
            ui_tx.send("queued notification").unwrap();
            Ok(())
        });
        let waiter = supervisor.clone();
        let join = thread::spawn(move || done_tx.send(waiter.finish()).unwrap());
        assert!(done_rx.recv_timeout(Duration::from_millis(50)).is_err());
        clean_tx.send(()).unwrap();
        assert_eq!(
            done_rx.recv_timeout(Duration::from_secs(2)).unwrap(),
            Ok(())
        );
        assert_eq!(ui_rx.try_recv().unwrap(), "queued notification");
        join.join().unwrap();
        assert_eq!(supervisor.finish(), Ok(()));
    }

    #[test]
    fn cleanup_failure_is_retained_on_repeated_exit() {
        let supervisor = Supervisor::default();
        supervisor.start(|| Err("session cleanup failed".into()));
        assert_eq!(supervisor.finish(), Err("session cleanup failed".into()));
        assert_eq!(supervisor.finish(), Err("session cleanup failed".into()));
    }

    #[test]
    fn panic_is_not_reported_as_a_clean_exit() {
        let supervisor = Supervisor::default();
        supervisor.start(|| panic!("synthetic supervisor failure"));
        assert!(supervisor.finish().unwrap_err().contains("unexpectedly"));
    }
}
