use std::os::windows::{io::AsRawHandle, process::CommandExt};
use std::{
    fs,
    io::{Read, Write},
    net::{SocketAddr, TcpListener, TcpStream},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::Mutex,
    time::{Duration, Instant},
};
use tauri::Manager;
use windows_sys::Win32::{
    Foundation::CloseHandle,
    System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
        SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    },
};

struct Job(isize);
impl Drop for Job {
    fn drop(&mut self) {
        unsafe {
            CloseHandle(self.0 as _);
        }
    }
}

pub struct Backend {
    child: Child,
    _job: Job,
    port: u16,
    token: String,
}

impl Backend {
    fn request(&self, method: &str, route: &str) -> std::io::Result<String> {
        let addr: SocketAddr = format!("127.0.0.1:{}", self.port).parse().unwrap();
        let mut stream = TcpStream::connect_timeout(&addr, Duration::from_millis(300))?;
        stream.set_read_timeout(Some(Duration::from_secs(1)))?;
        stream.set_write_timeout(Some(Duration::from_secs(1)))?;
        write!(stream, "{method} {route} HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer {}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n", self.token)?;
        let mut response = String::new();
        stream.read_to_string(&mut response)?;
        Ok(response)
    }

    pub fn start(app: &tauri::AppHandle, data: &Path) -> Result<Option<Self>, Box<dyn std::error::Error>> {
        let bundle = app.path().resource_dir()?.join("backend");
        let source = std::env::var_os("ASMR_HELPER_SOURCE_ROOT").map(PathBuf::from);
        let (python, script) = if let Some(ref root) = source {
            (root.join(".venv/Scripts/python.exe"), root.join("scripts/desktop_backend.py"))
        } else {
            (bundle.join("python/python.exe"), bundle.join("app/desktop_backend.py"))
        };
        if !script.is_file() || !python.is_file() {
            if source.is_some() {
                return Err("Main project Python or desktop backend script is missing; no environment was installed.".into());
            }
            if cfg!(debug_assertions) {
                return Ok(None);
            }
            return Err("Bundled backend is missing. Please reinstall ASMR Helper Test.".into());
        }
        fs::create_dir_all(data.join("logs"))?;
        fs::create_dir_all(data.join("debug/runtime"))?;
        let log = fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(data.join("logs/launcher.log"))?;
        let listener = TcpListener::bind("127.0.0.1:0")?;
        let port = listener.local_addr()?.port();
        let token = format!(
            "{}{}",
            uuid::Uuid::new_v4().simple(),
            uuid::Uuid::new_v4().simple()
        );
        let handle = unsafe { CreateJobObjectW(std::ptr::null(), std::ptr::null()) };
        if handle.is_null() {
            return Err(std::io::Error::last_os_error().into());
        }
        let job = Job(handle as isize);
        let mut limits: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = unsafe { std::mem::zeroed() };
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        if unsafe {
            SetInformationJobObject(
                handle,
                JobObjectExtendedLimitInformation,
                &limits as *const _ as _,
                std::mem::size_of_val(&limits) as u32,
            )
        } == 0
        {
            return Err(std::io::Error::last_os_error().into());
        }
        drop(listener);
        let mut command = Command::new(python);
        command.args(["-I", "-B"]).arg(script);
        if let Some(ref root) = source {
            command.arg("--source-root").arg(root);
        }
        let mut child = command
            .arg("--data-dir")
            .arg(&data)
            .arg("--port")
            .arg(port.to_string())
            .env("ASMR_HELPER_DESKTOP_TOKEN", &token)
            .env("ASMR_HELPER_START_GATE", "1")
            .env("PYTHONUTF8", "1")
            .env("TEMP", data.join("debug/runtime"))
            .env("TMP", data.join("debug/runtime"))
            .env("TMPDIR", data.join("debug/runtime"))
            .env_remove("ASMR_HELPER_MODEL_ROOT")
            .env_remove("ASMR_HELPER_TEMP_ROOT")
            .current_dir(&data)
            .stdin(Stdio::piped())
            .stdout(Stdio::from(log.try_clone()?))
            .stderr(Stdio::from(log))
            .creation_flags(0x08000000)
            .spawn()?;
        if unsafe { AssignProcessToJobObject(handle, child.as_raw_handle() as _) } == 0 {
            let err = std::io::Error::last_os_error();
            let _ = child.kill();
            let _ = child.wait();
            return Err(err.into());
        }
        if let Some(mut stdin) = child.stdin.take() {
            stdin.write_all(b"start\n")?;
        }
        let mut backend = Self {
            child,
            _job: job,
            port,
            token,
        };
        let deadline = Instant::now() + Duration::from_secs(150);
        while Instant::now() < deadline {
            if backend.child.try_wait()?.is_some() {
                return Err(format!(
                    "Backend stopped during startup. See {}",
                    data.join("logs/launcher.log").display()
                )
                .into());
            }
            if backend
                .request("GET", "/__desktop/health")
                .is_ok_and(|r| r.starts_with("HTTP/1.1 200"))
            {
                return Ok(Some(backend));
            }
            std::thread::sleep(Duration::from_millis(200));
        }
        Err(format!(
            "Backend startup timed out. See {}",
            data.join("logs/launcher.log").display()
        )
        .into())
    }

    pub fn workspace_switch_ready(&self, reserve: bool) -> Result<(), String> {
        let response = self.request(if reserve { "POST" } else { "GET" }, "/__desktop/workspace-switch-ready")
            .map_err(|_| "无法确认任务状态，请稍后重试。".to_string())?;
        let value: serde_json::Value = serde_json::from_str(response.split_once("\r\n\r\n").map(|(_, body)| body).unwrap_or(""))
            .map_err(|_| "任务状态响应不可用，未切换目录。".to_string())?;
        if value["ready"] != true { return Err("仍有排队或运行中的任务，请完成或取消任务后再切换工作目录。".into()); }
        Ok(())
    }

    pub fn init_script(&self) -> String {
        format!(
            "window.__ASMR_BACKEND__ = Object.freeze({});",
            serde_json::json!({"base": format!("http://127.0.0.1:{}/api/v1",self.port), "token":self.token})
        )
    }
}

impl Drop for Backend {
    fn drop(&mut self) {
        let _ = self.request("POST", "/__desktop/shutdown");
        let deadline = Instant::now() + Duration::from_secs(4);
        while Instant::now() < deadline {
            if self.child.try_wait().ok().flatten().is_some() {
                return;
            }
            std::thread::sleep(Duration::from_millis(100));
        }
        let _ = self.child.kill();
        let _ = self.child.wait();
        // Job's drop also terminates remaining runtime/model descendants.
    }
}

pub type BackendState = Mutex<Option<Backend>>;
