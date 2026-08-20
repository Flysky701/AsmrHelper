#[cfg(windows)]
mod single_instance {
    use std::iter;
    use std::ptr;
    use windows_sys::Win32::Foundation::{CloseHandle, GetLastError, HANDLE};
    use windows_sys::Win32::System::Threading::CreateMutexW;

    pub struct InstanceMutex(HANDLE);

    impl InstanceMutex {
        pub fn acquire() -> Result<Self, u32> {
            let name: Vec<u16> = "Local\\ASMRHelper.Desktop.SingleInstance"
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
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
