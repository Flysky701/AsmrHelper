import { useNavStore } from '@/stores/navStore'
import type { PageId } from '@/stores/navStore'
import type { ComponentType } from 'react'

import Workbench from '@/pages/Workbench'
import WorkflowPresets from '@/pages/WorkflowPresets'
import ReviewStudio from '@/pages/ReviewStudio'
import VoiceLab from '@/pages/voice-lab/VoiceLab'
import TaskCenter from '@/pages/TaskCenter'
import EnginesResources from '@/pages/EnginesResources'
import Settings from '@/pages/Settings'
import AudioTools from '@/pages/AudioTools'

const PAGES: Record<PageId, ComponentType> = {
  workbench: Workbench,
  'workflow-presets': WorkflowPresets,
  'subtitle-workshop': ReviewStudio,
  'voice-lab': VoiceLab,
  'audio-tools': AudioTools,
  'task-center': TaskCenter,
  engines: EnginesResources,
  settings: Settings,
}

export default function MainContent() {
  const activePage = useNavStore((s) => s.activePage)
  const Page = PAGES[activePage]

  return (
    <main className="app-main">
      <Page />
    </main>
  )
}
