import { useState } from 'react'
import { NeuButton } from '@/components/ui'
import VoiceList from './VoiceList'
import VoiceDesign from './VoiceDesign'
import VoiceClone from './VoiceClone'

type Tab = 'list' | 'design' | 'clone'

const TABS: { id: Tab; label: string }[] = [
  { id: 'list', label: '音色列表' },
  { id: 'design', label: '设计音色' },
  { id: 'clone', label: '克隆音色' },
]

export default function VoiceLab() {
  const [activeTab, setActiveTab] = useState<Tab>('list')

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div style={{ display: 'flex', gap: '8px' }}>
        {TABS.map((tab) => (
          <NeuButton
            key={tab.id}
            variant={activeTab === tab.id ? 'primary' : 'secondary'}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </NeuButton>
        ))}
      </div>
      {activeTab === 'list' && <VoiceList />}
      {activeTab === 'design' && <VoiceDesign />}
      {activeTab === 'clone' && <VoiceClone />}
    </div>
  )
}
