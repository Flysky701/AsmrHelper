use tauri::Manager;
use tauri_plugin_dialog::DialogExt;
#[cfg(windows)]
mod backend;
#[cfg(windows)]
mod single_instance {
    use std::iter;
    use std::ptr;
    use windows_sys::Win32::Foundation::{CloseHandle, GetLastError, HANDLE};
    use windows_sys::Win32::System::Threading::CreateMutexW;

    pub struct InstanceMutex(HANDLE);

    impl InstanceMutex {
        pub fn acquire() -> Result<Self, u32> {
            let name: Vec<u16> = "Local\\ASMRHelper.Test.Desktop.SingleInstance"
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
            Ok(Self(handle))
        }
    }

    impl Drop for InstanceMutex {
        fn drop(&mut self) {
            // SAFETY: this handle is owned by the guard and closed once here.
            unsafe { CloseHandle(self.0) };
        }
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

    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            #[cfg(windows)]
            let backend = match backend::Backend::start(app) {
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
            .title("ASMR Helper Test 0.2.1-beta.2")
            .inner_size(1200.0, 800.0)
            .min_inner_size(900.0, 600.0)
            .center();
            #[cfg(windows)]
            {
                if let Some(ref service) = backend {
                    window = window.initialization_script(service.init_script());
                }
                app.manage(backend::BackendState::new(backend));
            }
            window.build()?;
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
