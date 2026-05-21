import { useNavStore } from '@/stores/navStore'
import type { PageId } from '@/stores/navStore'
import type { ComponentType } from 'react'

import Workbench from '@/pages/Workbench'
import SubtitleWorkshop from '@/pages/SubtitleWorkshop'
import VoiceLab from '@/pages/voice-lab/VoiceLab'
import TaskCenter from '@/pages/TaskCenter'
import EnginesResources from '@/pages/EnginesResources'
import Settings from '@/pages/Settings'

const PAGES: Record<PageId, ComponentType> = {
  workbench: Workbench,
  'subtitle-workshop': SubtitleWorkshop,
  'voice-lab': VoiceLab,
  'task-center': TaskCenter,
  engines: EnginesResources,
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
