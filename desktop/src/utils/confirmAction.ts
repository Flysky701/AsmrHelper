import { isTauri } from '@tauri-apps/api/core'
import { confirm } from '@tauri-apps/plugin-dialog'

let pending = false

// Tauri dialogs return promises, unlike the browser's synchronous confirm.
// Reject duplicate requests and failures so a draft is never discarded by default.
export async function confirmAction(message: string): Promise<boolean> {
  if (pending) return false
  pending = true
  try { return isTauri() ? await confirm(message) : await window.confirm(message) }
  catch (error) { console.error('无法显示确认对话框', error); return false }
  finally { pending = false }
}
