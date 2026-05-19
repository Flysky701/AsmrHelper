use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;
use tauri::{AppHandle, Emitter, Manager};

const HEALTH_TIMEOUT: Duration = Duration::from_secs(30);
const HEALTH_INTERVAL: Duration = Duration::from_millis(500);

pub struct SidecarState {
    pub child: Mutex<Option<Child>>,
}

impl SidecarState {
    pub fn new() -> Self {
        Self {
            child: Mutex::new(None),
        }
    }
}

/// Find a free TCP port on localhost.
fn find_free_port() -> Option<u16> {
    portpicker::pick_unused_port()
}

/// Locate the Python executable.
/// Priority: ASMR_PYTHON env var > project .venv > system python.
fn find_python(project_dir: &std::path::Path) -> String {
    if let Ok(custom) = std::env::var("ASMR_PYTHON") {
        return custom;
    }

    #[cfg(target_os = "windows")]
    let venv_python = project_dir.join(".venv").join("Scripts").join("python.exe");
    #[cfg(not(target_os = "windows"))]
    let venv_python = project_dir.join(".venv").join("bin").join("python");

    if venv_python.exists() {
        return venv_python.to_string_lossy().to_string();
    }

    "python".to_string()
}

/// Determine the backend project directory.
///
/// Priority:
/// 1. ASMR_PROJECT_DIR override
/// 2. repo root in debug builds
/// 3. bundled resource dir in release builds
fn resolve_project_dir(app: &AppHandle) -> std::path::PathBuf {
    if let Ok(custom) = std::env::var("ASMR_PROJECT_DIR") {
        return std::path::PathBuf::from(custom);
    }

    #[cfg(debug_assertions)]
    {
        let _ = app;
        let manifest_dir = env!("CARGO_MANIFEST_DIR");
        return std::path::Path::new(manifest_dir)
            .parent()
            .and_then(|p| p.parent())
            .unwrap_or(std::path::Path::new(manifest_dir))
            .to_path_buf();
    }
    #[cfg(not(debug_assertions))]
    {
        if let Ok(resource_dir) = app.path().resource_dir() {
            return resource_dir;
        }
        std::env::current_dir().unwrap_or_else(|_| std::path::PathBuf::from("."))
    }
}

/// Poll the /health endpoint until it responds or times out.
async fn wait_for_health(port: u16) -> bool {
    let url = format!("http://127.0.0.1:{}/health", port);
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .unwrap();

    let deadline = tokio::time::Instant::now() + HEALTH_TIMEOUT;
    loop {
        if tokio::time::Instant::now() >= deadline {
            return false;
        }
        match client.get(&url).send().await {
            Ok(resp) if resp.status().is_success() => return true,
            _ => {}
        }
        tokio::time::sleep(HEALTH_INTERVAL).await;
    }
}

/// Start the Python sidecar process and emit sidecar:ready when healthy.
pub async fn start_sidecar(app: AppHandle) {
    let project_dir = resolve_project_dir(&app);

    let port = match find_free_port() {
        Some(p) => p,
        None => {
            eprintln!("[sidecar] failed to find free port");
            return;
        }
    };

    let python = find_python(&project_dir);
    println!(
        "[sidecar] starting {} -m src.api.http on port {}",
        python, port
    );

    let child = Command::new(&python)
        .args(["-m", "src.api.http"])
        .current_dir(&project_dir)
        .env("ASMR_PORT", port.to_string())
        .env("PYTHONPATH", project_dir.to_string_lossy().to_string())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn();

    let child = match child {
        Ok(c) => c,
        Err(e) => {
            eprintln!("[sidecar] failed to spawn python: {}", e);
            app.emit("sidecar:error", format!("Failed to start Python: {}", e))
                .ok();
            return;
        }
    };

    let pid = child.id();
    println!("[sidecar] python process pid={}", pid);

    // Store the child handle for cleanup
    {
        let state = app.state::<SidecarState>();
        let mut guard = state.child.lock().unwrap();
        *guard = Some(child);
    }

    // Wait for the health endpoint
    if wait_for_health(port).await {
        println!("[sidecar] python sidecar healthy on port {}", port);
        app.emit("sidecar:ready", port).ok();
    } else {
        eprintln!("[sidecar] health check timed out");
        app.emit(
            "sidecar:error",
            "Python sidecar failed to start (health timeout)".to_string(),
        )
        .ok();

        // Kill the process
        let state = app.state::<SidecarState>();
        let mut guard = state.child.lock().unwrap();
        if let Some(ref mut c) = *guard {
            c.kill().ok();
        }
        *guard = None;
    }
}

/// Kill the sidecar process on app exit.
pub fn kill_sidecar(app: &AppHandle) {
    let state = app.state::<SidecarState>();
    let mut guard = state.child.lock().unwrap();
    if let Some(ref mut c) = *guard {
        println!("[sidecar] killing python process pid={}", c.id());
        c.kill().ok();
        c.wait().ok();
    }
    *guard = None;
}
