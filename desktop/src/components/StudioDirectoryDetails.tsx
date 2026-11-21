import type { DraftInspectResponse } from '@/api/drafts'
import { fileName } from '@/domain/workbenchInput'
import { format, t } from '@/i18n'
import { displayPath } from '@/utils/displayPath'

const STEM_LABELS = [
  ['vocals', '人声干轨'],
  ['no_se', '无音效分轨'],
  ['se_only', '纯音效分轨'],
] as const

export default function StudioDirectoryDetails({ result, onListen }: {
  result: DraftInspectResponse
  onListen: (path: string, name: string) => void
}) {
  const root = displayPath(result.work_dir).replace(/\\/g, '/').replace(/\/$/, '') + '/'
  const pathLabel = (path: string) => {
    const displayed = displayPath(path)
    return displayed.replace(/\\/g, '/').startsWith(root) ? displayed.slice(root.length) : displayed
  }

  const displayedAudio = new Set<string>()
  const tracks = result.tracks.map(track => {
    const stems = STEM_LABELS.flatMap(([role, label]) => {
      const path = track.paired_stems?.[role]
      return path ? [{ path, label }] : []
    })
    const alternates = (track.paired_stems?.alternates ?? []).map(path => ({ path, label: '备用音频' }))
    const files = [...stems, ...alternates]
    displayedAudio.add(track.path)
    files.forEach(file => displayedAudio.add(file.path))
    return { track, files }
  })
  const otherAudio = result.audio_files.filter(file => !displayedAudio.has(file.path))
  const audioRow = (path: string, label?: string) => (
    <div className="wb-directory-file">
      <span className="wb-directory-path" title={displayPath(path)}>{pathLabel(path)}</span>
      {label && <span className="wb-directory-role">{t(label)}</span>}
      <button type="button" className="wb-mini-btn" aria-label={format('试听 {0}', [fileName(path)])}
        onClick={() => onListen(path, fileName(path))}>
        {t('试听')}
      </button>
    </div>
  )

  return (
    <section className="wb-directory-details" aria-label={t('目录详情')}>
      {(tracks.length > 0 || otherAudio.length > 0) && (
        <div>
          <h3>{t('音频与分轨')}</h3>
          <ul className="wb-directory-list">
            {tracks.map(({ track, files }) => (
              <li key={track.track_id}>
                {audioRow(track.path, '主音频')}
                {files.length > 0 && (
                  <ul className="wb-directory-list wb-directory-stems">
                    {files.map(file => <li key={file.path}>{audioRow(file.path, file.label)}</li>)}
                  </ul>
                )}
              </li>
            ))}
            {otherAudio.map(file => <li key={file.path}>{audioRow(file.path)}</li>)}
          </ul>
        </div>
      )}
      {([{ label: '字幕', files: result.subtitles }, { label: '台本', files: result.scripts }]).map(({ label, files }) => files.length > 0 && (
        <div key={label}>
          <h3>{t(label)}</h3>
          <ul className="wb-directory-list">
            {files.map(file => (
              <li className="wb-directory-file" key={file.path}>
                <span className="wb-directory-path" title={displayPath(file.path)}>{pathLabel(file.path)}</span>
                {'valid' in file && file.valid === false && <span className="wb-directory-role">{t('无法解析')}</span>}
              </li>
            ))}
          </ul>
        </div>
      ))}
      {!result.audio_files.length && !tracks.length && !result.subtitles.length && !result.scripts.length && (
        <p>{t('目录里没有识别到可用素材。')}</p>
      )}
    </section>
  )
}
