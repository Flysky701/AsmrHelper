use std::os::windows::{io::AsRawHandle, process::CommandExt};
use std::{
    fs,
    io::{Read, Write},
    net::{SocketAddr, TcpListener, TcpStream},
    path::PathBuf,
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

    pub fn start(app: &tauri::App) -> Result<Option<Self>, Box<dyn std::error::Error>> {
        let bundle = app.path().resource_dir()?.join("backend");
        if !bundle.join("app/desktop_backend.py").is_file() {
            if cfg!(debug_assertions) {
                return Ok(None);
            }
            return Err("Bundled backend is missing. Please reinstall ASMR Helper Test.".into());
        }
        let data: PathBuf = std::env::var_os("ASMR_HELPER_DATA_DIR")
            .map(PathBuf::from)
            .unwrap_or(app.path().local_data_dir()?.join("ASMRHelperTestData"));
        fs::create_dir_all(data.join("logs"))?;
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
        let mut child = Command::new(bundle.join("python/python.exe"))
            .args(["-I", "-B"])
            .arg(bundle.join("app/desktop_backend.py"))
            .arg("--data-dir")
            .arg(&data)
            .arg("--port")
            .arg(port.to_string())
            .env("ASMR_HELPER_DESKTOP_TOKEN", &token)
            .env("ASMR_HELPER_START_GATE", "1")
            .env("PYTHONUTF8", "1")
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
