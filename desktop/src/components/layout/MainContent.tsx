import { useNavStore } from '@/stores/navStore'
import type { PageId } from '@/stores/navStore'
import type { ComponentType } from 'react'

import Workbench from '@/pages/Workbench'
import Tools from '@/pages/tools/Tools'
import VoiceLab from '@/pages/voice-lab/VoiceLab'
import Tasks from '@/pages/Tasks'
import Resources from '@/pages/Resources'
import Settings from '@/pages/Settings'

const PAGES: Record<PageId, ComponentType> = {
  workbench: Workbench,
  tools: Tools,
  'voice-lab': VoiceLab,
  tasks: Tasks,
  resources: Resources,
  settings: Settings,
}

export default function MainContent() {
  const activePage = useNavStore((s) => s.activePage)
  const Page = PAGES[activePage]

  return (
    <main
      style={{
        flex: 1,
        overflow: 'auto',
        padding: '20px',
        animation: 'fadeIn 200ms ease-out',
      }}
    >
      <Page />
      <style>{`
        @keyframes fadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }
      `}</style>
    </main>
  )
}
