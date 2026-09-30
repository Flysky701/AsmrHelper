import { createRoot } from 'react-dom/client'
import SpeechConnections from '../../src/components/SpeechConnections'
import '../../src/index.css'

createRoot(document.getElementById('root')!).render(<main style={{ maxWidth: 880, margin: '24px auto', padding: 20 }}>
  <SpeechConnections />
</main>)
