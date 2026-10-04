use serde_json::{json, Value};
use std::{fs, io::Write, path::{Path, PathBuf}, sync::Mutex};
use tauri::Manager;
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use windows_sys::Win32::Storage::FileSystem::{GetDiskFreeSpaceExW, MoveFileExW, MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH};

const MARKER: &str = ".asmr-helper-workspace.json";
const APP_ID: &str = "ASMRHelperTestWorkspace";
pub struct WorkspaceState {
    pub active: PathBuf,
    locator: PathBuf,
    bundle: PathBuf,
    fixed_by_environment: bool,
    pending: Mutex<Option<PathBuf>>,
}
fn wide(path: &Path) -> Vec<u16> {
    use std::os::windows::ffi::OsStrExt;
    path.as_os_str().encode_wide().chain(std::iter::once(0)).collect()
}
fn display(path: &Path) -> String { path.to_string_lossy().strip_prefix(r"\\?\").unwrap_or(&path.to_string_lossy()).to_string() }
fn free_bytes(path: &Path) -> Result<u64, String> {
    let mut free = 0;
    if unsafe { GetDiskFreeSpaceExW(wide(path).as_ptr(), &mut free, std::ptr::null_mut(), std::ptr::null_mut()) } == 0 {
        return Err("无法读取可用空间，请检查目录和磁盘。".into());
    }
    Ok(free)
}
fn has_marker(path: &Path) -> bool {
    let marker = path.join(MARKER);
    if !marker.is_file() || fs::metadata(&marker).map(|m| m.len() > 1024).unwrap_or(true) { return false; }
    fs::read(&marker).ok().and_then(|b| serde_json::from_slice::<Value>(&b).ok())
        .is_some_and(|v| v["application"] == APP_ID && v["schema"] == 1)
}
fn legacy_workspace(path: &Path) -> bool {
    path.join("config/config.json").is_file() && path.join("state.sqlite3").is_file()
        && fs::read_dir(path.join("runtimes")).ok().is_some_and(|entries| entries.flatten().any(|p| p.path().join(".asmr-ready").is_file()))
}
fn validate(path: &Path, bundle: &Path, allow_legacy: bool) -> Result<PathBuf, String> {
    if !path.is_absolute() || path.parent().is_none() { return Err("请选择完整的工作目录，不能使用磁盘根目录。".into()); }
    let root = path.canonicalize().map_err(|_| "目录不存在或无法访问，请先在选择框中新建一个文件夹。".to_string())?;
    if !root.is_dir() || root.parent().is_none() { return Err("请选择文件夹，不能使用文件或磁盘根目录。".into()); }
    let bundle = bundle.canonicalize().map_err(|_| "无法确认程序资源目录。".to_string())?;
    if root.starts_with(&bundle) || bundle.starts_with(&root) { return Err("不能把程序或后端资源目录用作工作目录；可选择独立的 workspace 子目录。".into()); }
    for variable in ["WINDIR", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "ProgramFiles", "ProgramFiles(x86)"] {
        if let Some(value) = std::env::var_os(variable) {
            if let Ok(protected) = PathBuf::from(value).canonicalize() {
                if root == protected || (variable == "WINDIR" && root.starts_with(&protected)) {
                    return Err("不能使用系统目录或用户目录本身，请选择专用子目录。".into());
                }
            }
        }
    }
    let mut entries = fs::read_dir(&root).map_err(|_| "无法读取目录，请检查权限。".to_string())?;
    if entries.next().is_some() && !has_marker(&root) && !(allow_legacy && legacy_workspace(&root)) {
        return Err("此目录非空且没有 ASMR Helper 工作目录标记。请选择空目录，或已由本应用创建的工作目录；不会合并或覆盖其他文件。".into());
    }
    let probe = root.join(format!(".asmr-write-check-{}", uuid::Uuid::new_v4().simple()));
    fs::OpenOptions::new().write(true).create_new(true).open(&probe)
        .and_then(|mut f| f.write_all(b"workspace write check"))
        .map_err(|_| "此目录不可写，请选择有写入权限的位置。".to_string())?;
    fs::remove_file(probe).map_err(|_| "无法清理写入检查文件，请选择其他目录。".to_string())?;
    free_bytes(&root)?;
    Ok(root)
}
fn mark(path: &Path) -> Result<(), String> {
    if has_marker(path) { return Ok(()); }
    let bytes = serde_json::to_vec(&json!({"application": APP_ID, "schema": 1})).unwrap();
    let mut file = fs::OpenOptions::new().write(true).create_new(true).open(path.join(MARKER)).map_err(|e| e.to_string())?;
    file.write_all(&bytes).map_err(|e| e.to_string())
}
fn persist(locator: &Path, root: &Path) -> Result<(), String> {
    fs::create_dir_all(locator.parent().unwrap()).map_err(|e| e.to_string())?;
    let temporary = locator.with_extension(format!("{}.tmp", uuid::Uuid::new_v4().simple()));
    fs::write(&temporary, serde_json::to_vec(&json!({"schema":1,"workspace":root})).unwrap()).map_err(|e| e.to_string())?;
    if unsafe { MoveFileExW(wide(&temporary).as_ptr(), wide(locator).as_ptr(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH) } == 0 {
        let error = std::io::Error::last_os_error().to_string();
        let _ = fs::remove_file(temporary);
        return Err(format!("无法保存工作目录位置：{error}"));
    }
    Ok(())
}
fn choose(app: &tauri::AppHandle, bundle: &Path) -> Result<Option<PathBuf>, String> {
    let Some(folder) = app.dialog().file().set_title("选择空文件夹或已有 ASMR Helper 工作目录（可新建文件夹）").blocking_pick_folder() else { return Ok(None); };
    let path = folder.into_path().map_err(|_| "请选择本机文件夹。".to_string())?;
    validate(&path, bundle, false).map(Some)
}
impl WorkspaceState {
    pub fn initialize(app: &tauri::AppHandle) -> Result<Option<Self>, Box<dyn std::error::Error>> {
        let bundle = app.path().resource_dir()?.join("backend");
        let local = app.path().local_data_dir()?;
        let locator = std::env::var_os("ASMR_HELPER_LOCATOR_DIR").map(PathBuf::from)
            .unwrap_or_else(|| local.join("ASMRHelperTest")).join("workspace.json");
        let override_root = std::env::var_os("ASMR_HELPER_DATA_DIR").map(PathBuf::from);
        let fixed_by_environment = override_root.is_some();
        let saved = if locator.is_file() {
            fs::read(&locator).ok().and_then(|b| serde_json::from_slice::<Value>(&b).ok())
                .and_then(|v| v["workspace"].as_str().map(PathBuf::from))
        } else { None };
        let legacy = std::env::var_os("ASMR_HELPER_LEGACY_DATA_DIR").map(PathBuf::from).unwrap_or_else(|| local.join("ASMRHelperTestData"));
        let legacy = if legacy_workspace(&legacy) { Some(legacy) } else { None };
        let candidate = override_root.clone().or(saved).or(legacy);
        if let Some(candidate) = candidate {
            match validate(&candidate, &bundle, true) {
                Ok(root) => {
                    mark(&root)?;
                    if !fixed_by_environment { persist(&locator, &root)?; }
                    return Ok(Some(Self { active: root, locator, bundle, fixed_by_environment, pending: Mutex::new(None) }));
                }
                Err(message) => {
                    app.dialog().message(format!("原工作目录不可用：{}\n{message}\n不会自动改用 C 盘。请重新选择。", display(&candidate))).kind(MessageDialogKind::Error).blocking_show();
                    if fixed_by_environment { return Err(message.into()); }
                }
            }
        }
        loop {
            let proceed = app.dialog().message("先选择工作目录，再准备运行环境。\n模型、Python 依赖、下载缓存及临时文件默认存放于此，可能占用数 GB。\n可选择任意可写磁盘上的专用空文件夹；旧文件不会搬移或删除。")
                .title("ASMR Helper · 选择工作目录")
                .buttons(MessageDialogButtons::OkCancelCustom("选择目录".into(), "退出".into())).blocking_show();
            if !proceed { return Ok(None); }
            match choose(app, &bundle) {
                Ok(Some(root)) => {
                    let free = free_bytes(&root)? as f64 / 1073741824.0;
                    let accepted = app.dialog().message(format!("工作目录：{}\n可用空间：{free:.1} GB\n\n确认后开始准备运行环境；不会迁移其他目录的数据。", display(&root)))
                        .title("确认工作目录").buttons(MessageDialogButtons::OkCancelCustom("使用此目录".into(), "重新选择".into())).blocking_show();
                    if !accepted { continue; }
                    mark(&root)?;
                    persist(&locator, &root)?;
                    return Ok(Some(Self { active: root, locator, bundle, fixed_by_environment: false, pending: Mutex::new(None) }));
                }
                Ok(None) => continue,
                Err(error) => { app.dialog().message(error).kind(MessageDialogKind::Error).blocking_show(); }
            }
        }
    }
    fn info(&self) -> Value {
        json!({"active":display(&self.active),"pending":self.pending.lock().ok().and_then(|p|p.as_ref().map(|p|display(p))),
            "free_bytes":free_bytes(&self.active).ok(),"fixed_by_environment":self.fixed_by_environment})
    }
}
#[tauri::command]
pub fn workspace_info(state: tauri::State<'_, WorkspaceState>) -> Value { state.info() }
#[tauri::command]
pub async fn workspace_choose(app: tauri::AppHandle) -> Result<Option<Value>, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let state = app.state::<WorkspaceState>();
        if state.fixed_by_environment { return Err("启动环境已固定工作目录，请先调整 ASMR_HELPER_DATA_DIR 后重新启动。".into()); }
        choose(&app, &state.bundle).map(|path| path.map(|p|json!({"path":display(&p),"free_bytes":free_bytes(&p).ok(),"existing":has_marker(&p)})))
    }).await.map_err(|e| e.to_string())?
}
#[tauri::command]
pub fn workspace_schedule_switch(path: String, state: tauri::State<'_, WorkspaceState>, backend: tauri::State<'_, crate::backend::BackendState>) -> Result<Value, String> {
    if state.fixed_by_environment { return Err("启动环境已固定工作目录，不能在设置中切换。".into()); }
    let service = backend.lock().map_err(|_| "后端忙，请稍后重试。")?;
    service.as_ref().ok_or("后端不可用，无法确认任务状态。")?.workspace_switch_ready(false)?;
    let root = validate(Path::new(&path), &state.bundle, false)?;
    mark(&root)?;
    persist(&state.locator, &root)?;
    *state.pending.lock().map_err(|_| "工作目录状态不可用。")? = Some(root);
    Ok(state.info())
}
#[tauri::command]
pub fn workspace_restart(app: tauri::AppHandle, state: tauri::State<'_, WorkspaceState>, backend: tauri::State<'_, crate::backend::BackendState>) -> Result<(), String> {
    if state.pending.lock().map_err(|_| "工作目录状态不可用。")?.is_none() { return Err("尚未选择下次启动的工作目录。".into()); }
    {
        let mut service = backend.lock().map_err(|_| "后端忙，请稍后重试。")?;
        service.as_ref().ok_or("后端不可用，无法确认任务状态。")?.workspace_switch_ready(true)?;
        service.take();
    }
    // The successor must be able to acquire the single-instance mutex.
    crate::single_instance::release_for_restart();
    app.restart()
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_foreign_directory_and_preserves_files() {
        let root = std::env::temp_dir().join(format!("asmr-workspace-test-{}",uuid::Uuid::new_v4()));
        let bundle=root.join("bundle");let chosen=root.join("中文 workspace");
        fs::create_dir_all(&bundle).unwrap();fs::create_dir_all(&chosen).unwrap();
        fs::write(chosen.join("keep.txt"),b"keep").unwrap();
        assert!(validate(&chosen,&bundle,false).is_err());
        assert_eq!(fs::read(chosen.join("keep.txt")).unwrap(),b"keep");
        fs::remove_file(chosen.join("keep.txt")).unwrap();
        assert!(validate(&chosen,&bundle,false).is_ok());
        mark(&chosen).unwrap();fs::write(chosen.join("keep.txt"),b"keep").unwrap();
        assert!(validate(&chosen,&bundle,false).is_ok());
        assert!(validate(&bundle,&bundle,false).is_err());
        let locator=root.join("locator/workspace.json");persist(&locator,&chosen).unwrap();persist(&locator,&chosen).unwrap();
        assert!(locator.is_file());
        fs::remove_dir_all(root).unwrap();
    }
}
