import { Component, type ErrorInfo, type ReactNode } from 'react'
import { isTauri } from '@tauri-apps/api/core'
import { getCurrentWindow } from '@tauri-apps/api/window'

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  override state: State = { error: null }
  private unlistenClose?: () => void

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  override componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Desktop UI boundary caught an error:', error, info)
    if (isTauri() && !this.unlistenClose) {
      const win = getCurrentWindow()
      void win.onCloseRequested(() => {
        void win.destroy()
      }).then((stop) => {
        this.unlistenClose = stop
      })
    }
  }

  override componentWillUnmount() {
    this.unlistenClose?.()
  }

  private handleReload = () => {
    window.location.reload()
  }

  private handleClose = async () => {
    if (isTauri()) {
      try {
        await getCurrentWindow().destroy()
        return
      } catch (err) {
        console.error('Failed to destroy window:', err)
      }
    }
    window.close()
  }

  override render() {
    if (!this.state.error) {
      return this.props.children
    }
    return (
      <main
        role="alert"
        style={{
          minHeight: '100vh',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '32px',
          gap: '14px',
          background: 'var(--bg, #f8fafc)',
          color: 'var(--fg, #1e293b)',
        }}
      >
        <h1 style={{ fontSize: '20px', fontWeight: 600, margin: 0 }}>
          界面遇到异常 / Unexpected UI Error
        </h1>
        <p style={{ fontSize: '13px', color: 'var(--muted, #64748b)', maxWidth: '520px', textAlign: 'center', margin: 0 }}>
          {this.state.error.message || '页面渲染中断，后台任务不受界面重载影响。'}
        </p>
        <div style={{ display: 'flex', gap: '10px', marginTop: '6px' }}>
          <button type="button" className="btn btn-primary" onClick={this.handleReload}>
            重新加载界面 / Reload
          </button>
          {isTauri() && (
            <button type="button" className="btn" onClick={() => void this.handleClose()}>
              关闭窗口 / Close
            </button>
          )}
        </div>
      </main>
    )
  }
}
