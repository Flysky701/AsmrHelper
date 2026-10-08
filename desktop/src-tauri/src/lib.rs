use tauri::Manager;
use tauri_plugin_dialog::DialogExt;
#[cfg(windows)]
mod backend;
#[cfg(windows)]
mod workspace;
#[cfg(windows)]
mod single_instance {
    use std::iter;
    use std::ptr;
    use windows_sys::Win32::Foundation::{CloseHandle, GetLastError};
    use std::sync::atomic::{AtomicIsize, Ordering};
    use windows_sys::Win32::System::Threading::CreateMutexW;

    static INSTANCE_HANDLE: AtomicIsize = AtomicIsize::new(0);
    pub struct InstanceMutex;

    impl InstanceMutex {
        pub fn acquire() -> Result<Self, u32> {
            let mutex_name = if std::env::var_os("ASMR_HELPER_SOURCE_ROOT").is_some() {
                "Local\\ASMRHelper.MainSource.Desktop.SingleInstance"
            } else {
                "Local\\ASMRHelper.Test.Desktop.SingleInstance"
            };
            let name: Vec<u16> = mutex_name
                .encode_utf16()
                .chain(iter::once(0))
                .collect();
            // SAFETY: the name is a stable, null-terminated UTF-16 buffer and
            // the returned handle is retained for the application's lifetime.
            let handle = unsafe { CreateMutexW(ptr::null(), 0, name.as_ptr()) };
            if handle.is_null() {
                // SAFETY: GetLastError has no preconditions.
                return Err(unsafe { GetLastError() });
            }
            // SAFETY: GetLastError immediately follows CreateMutexW.
            let last_error = unsafe { GetLastError() };
            if last_error == windows_sys::Win32::Foundation::ERROR_ALREADY_EXISTS {
                // SAFETY: handle was returned by CreateMutexW and is valid.
                unsafe { CloseHandle(handle) };
                return Err(last_error);
            }
            INSTANCE_HANDLE.store(handle as isize, Ordering::SeqCst);
            Ok(Self)
        }
    }

    pub fn release_for_restart() {
        let handle = INSTANCE_HANDLE.swap(0, Ordering::SeqCst);
        if handle != 0 {
            // Close only this process's owned mutex, after task admission is frozen.
            unsafe { CloseHandle(handle as _) };
        }
    }
    impl Drop for InstanceMutex {
        fn drop(&mut self) { release_for_restart(); }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    #[cfg(windows)]
    let _instance_mutex = match single_instance::InstanceMutex::acquire() {
        Ok(mutex) => Some(mutex),
        Err(code) if code == windows_sys::Win32::Foundation::ERROR_ALREADY_EXISTS => return,
        Err(code) => {
            eprintln!("single-instance guard unavailable (Windows error {code}); continuing");
            None
        }
    };

    let builder = tauri::Builder::default().plugin(tauri_plugin_dialog::init());
    #[cfg(windows)]
    let builder = builder.invoke_handler(tauri::generate_handler![workspace::workspace_info, workspace::workspace_choose, workspace::workspace_schedule_switch, workspace::workspace_restart]);
    builder.setup(|app| {
            let handle = app.handle().clone();
            tauri::async_runtime::spawn_blocking(move || {
                if let Err(error) = initialize_desktop(&handle) {
                    handle.dialog().message(error.to_string()).title("ASMR Helper Test - Startup failed")
                        .kind(tauri_plugin_dialog::MessageDialogKind::Error).blocking_show();
                    handle.exit(1);
                }
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            if window.label() == "main" {
                if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                    // Fail closed if the frontend close listener is unavailable.
                    // The confirmed path uses WebviewWindow::destroy(), which does
                    // not emit another CloseRequested event.
                    api.prevent_close();
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event {
                #[cfg(windows)]
                if let Some(state) = app.try_state::<backend::BackendState>() {
                    if let Ok(mut backend) = state.lock() {
                        backend.take();
                    }
                }
            }
        });
}

fn initialize_desktop(app: &tauri::AppHandle) -> Result<(), Box<dyn std::error::Error>> {
            #[cfg(windows)]
            let workspace = match workspace::WorkspaceState::initialize(app)? {
                Some(workspace) => workspace,
                None => { app.exit(0); return Ok(()); }
            };
            #[cfg(windows)]
            let backend = match backend::Backend::start(app, &workspace.active) {
                Ok(value) => value,
                Err(error) => {
                    app.dialog()
                        .message(error.to_string())
                        .title("ASMR Helper Test - Startup failed")
                        .kind(tauri_plugin_dialog::MessageDialogKind::Error)
                        .blocking_show();
                    return Err(error);
                }
            };
            let mut window = tauri::WebviewWindowBuilder::new(
                app,
                "main",
                tauri::WebviewUrl::App("index.html".into()),
            )
            .title(if std::env::var_os("ASMR_HELPER_SOURCE_ROOT").is_some() {
                "ASMR Helper · 主项目"
            } else { "ASMR Helper Test 0.2.1-beta.5" })
            .inner_size(1200.0, 800.0)
            .min_inner_size(900.0, 600.0)
            .center();
            #[cfg(windows)]
            {
                if let Some(ref service) = backend {
                    window = window.initialization_script(service.init_script());
                }
                std::env::set_var("WEBVIEW2_USER_DATA_FOLDER", workspace.active.join(".cache/webview2"));
                window = window.data_directory(workspace.active.join(".cache/webview2"));
                app.manage(workspace);
                app.manage(backend::BackendState::new(backend));
            }
            window.build()?;
    Ok(())
}
