import { useEffect, useId, useRef, useState, type DragEvent } from 'react'
import { draftsApi } from '@/api/drafts'
import type { DraftInspectResponse, DraftPrepareRequest } from '@/api/drafts'
import { settingsApi, type ConnectionProfile } from '@/api/settings'
import { speechApi } from '@/api/speech'
import type { SpeechRecipe } from '@/api/speech'
import type { GraphPresetDraft } from '@/api/types'
import { REMAKE_TIERS, studioWorkflow, type RemakeTier, type StudioScenario } from '@/domain/studioRemakeWorkflow'
import { fileName } from '@/domain/workbenchInput'
import type { GraphLanguage } from '@/domain/workflowGraph'
import { FILE_FILTERS, useFileSelector } from '@/hooks/useFileSelector'
import { format, t, useI18n } from '@/i18n'
import { useAudioPlayerStore } from '@/stores/audioPlayerStore'
import { useNavStore } from '@/stores/navStore'
import { displayPath } from '@/utils/displayPath'
import StudioDirectoryDetails from './StudioDirectoryDetails'
import './StudioQuickStart.css'

interface StudioQuickStartProps {
  onOpenBatchQueue: (draft: GraphPresetDraft, paths: string[], folder?: string) => Promise<void>
  onOpenGraphEditor: (draft: GraphPresetDraft) => Promise<void>
}

interface WorkspaceMediaItem {
  id: string
  path: string
  name: string
  kind: 'audio' | 'folder' | 'subtitle' | 'script'
}

type Inspection = { state: 'pending' } | { state: 'done'; result: DraftInspectResponse } | { state: 'failed'; message: string }

const SCENARIO_META: Record<StudioScenario, { label: string; hint: string }> = {
  binaural_dub: {
    label: '双耳重制',
    hint: '人声分离 → 识别翻译 → 双耳声像跟随配音混音',
  },
  subtitle: {
    label: '中文字幕',
    hint: '语音识别 → 口语翻译 → 导出双语 SRT / LRC',
  },
  script_dub: {
    label: '台本配音',
    hint: '导入 SRT / TXT / PDF 对齐原声时间轴并配音',
  },
}

export default function StudioQuickStart({
  onOpenBatchQueue,
  onOpenGraphEditor,
}: StudioQuickStartProps) {
  useI18n()
  const { selectFiles, selectFolder } = useFileSelector()
  const openReview = useNavStore((s) => s.openReview)
  const setPage = useNavStore((s) => s.setPage)
  const pendingDraftCount = useNavStore((s) => s.pendingDraftCount)
  const setPendingDraftCount = useNavStore((s) => s.setPendingDraftCount)
  const showAudio = useAudioPlayerStore((s) => s.show)

  const [scenario, setScenario] = useState<StudioScenario>('binaural_dub')
  const [tier, setTier] = useState<RemakeTier>('asmr')
  const [sourcePath, setSourcePath] = useState('')
  const [sourceKind, setSourceKind] = useState<'audio' | 'folder'>('audio')
  const [companionPath, setCompanionPath] = useState('')
  const [sourceLang, setSourceLang] = useState<GraphLanguage>('ja')
  const [targetLang, setTargetLang] = useState<GraphLanguage>('zh')
  const [reviewBeforeRun, setReviewBeforeRun] = useState(true)
  const [separationModel, setSeparationModel] = useState<'mel_band_roformer' | 'htdemucs'>('mel_band_roformer')
  const [sampleCueCount, setSampleCueCount] = useState(2)
  const [durationAware, setDurationAware] = useState(true)
  const [enableSeedVc, setEnableSeedVc] = useState(false)
  const [dragOver, setDragOver] = useState(false)

  const [recipes, setRecipes] = useState<SpeechRecipe[]>([])
  const [selectedRecipeId, setSelectedRecipeId] = useState('')
  const [translationConnection, setTranslationConnection] = useState<ConnectionProfile>()
  const [inspection, setInspection] = useState<Inspection | null>(null)
  const [directoryExpanded, setDirectoryExpanded] = useState(true)
  const inspectionRequest = useRef(0)
  const directoryDetailsId = useId()
  const inspectResult = inspection?.state === 'done' ? inspection.result : null
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  useEffect(() => {
    let alive = true
    void speechApi.rules(false)
      .then((res) => {
        if (!alive) return
        const activeRecipes = res.recipes.filter((r) => !r.archived)
        setRecipes(activeRecipes)
        if (activeRecipes[0] && !selectedRecipeId) {
          setSelectedRecipeId(activeRecipes[0].id)
        }
      })
      .catch(() => {})
    void settingsApi.get().then(({ settings }) => {
      if (!alive) return
      const { llm, active_llm } = settings.connection_profiles
      setTranslationConnection(llm.find(connection => connection.id === active_llm && !connection.removed))
    }).catch(() => {})
    return () => { alive = false }
  }, [])

  const inspectSource = async (path: string, kind: 'audio' | 'folder') => {
    const request = ++inspectionRequest.current
    setSourcePath(path)
    setSourceKind(kind)
    setError('')
    setNotice('')
    setDirectoryExpanded(true)
    setInspection({ state: 'pending' })
    try {
      const result = await draftsApi.inspect(path)
      if (request === inspectionRequest.current) setInspection({ state: 'done', result })
    } catch (err) {
      if (request === inspectionRequest.current) {
        setInspection({ state: 'failed', message: err instanceof Error ? err.message : String(err) })
      }
    }
  }

  const pickAudio = async () => {
    const files = await selectFiles({ multiple: false, filters: [FILE_FILTERS.audio] })
    if (files[0]) await inspectSource(files[0], 'audio')
  }

  const pickWorkDir = async () => {
    const folder = await selectFolder()
    if (folder) await inspectSource(folder, 'folder')
  }

  const pickCompanion = async () => {
    const files = await selectFiles({
      multiple: false,
      filters: [
        FILE_FILTERS.subtitle,
        { name: '台本文件', extensions: ['txt', 'pdf', 'md'] },
      ],
    })
    if (files[0]) setCompanionPath(files[0])
  }

  const handleDrop = async (event: DragEvent<HTMLElement>) => {
    event.preventDefault()
    setDragOver(false)
    const files = Array.from(event.dataTransfer.files)
    if (!files.length) return
    for (const file of files) {
      const p = (file as File & { path?: string }).path || file.name
      if (/\.(srt|vtt|lrc|txt|pdf|md)$/i.test(p)) {
        setCompanionPath(p)
      } else if (/\.(mp3|wav|flac|ogg|m4a|aac|wma)$/i.test(p)) {
        await inspectSource(p, 'audio')
      }
    }
  }

  const mediaRows: WorkspaceMediaItem[] = []
  if (sourcePath.trim()) {
    mediaRows.push({
      id: 'primary',
      path: sourcePath,
      name: fileName(sourcePath),
      kind: sourceKind,
    })
  }
  if (companionPath.trim()) {
    mediaRows.push({
      id: 'companion',
      path: companionPath,
      name: fileName(companionPath),
      kind: /\.(txt|pdf|md)$/i.test(companionPath) ? 'script' : 'subtitle',
    })
  }

  const isScript = /\.(txt|pdf|md)$/i.test(companionPath)
  const draft = studioWorkflow({
    scenario, tier, sourceLang, targetLang, separationModel, translationConnection, durationAware,
    subtitleInput: Boolean(companionPath.trim()), recipeId: selectedRecipeId, enableSeedVc,
  })

  const handleStart = async () => {
    if (!sourcePath.trim()) {
      setError('请先在左侧工作区导入音频或作品文件夹。')
      return
    }
    if (!reviewBeforeRun) {
      if (isScript) {
        setError('请先预审台本，或在字幕与台本中将台本转成带时间轴的字幕，再交给队列。')
        return
      }
      await onOpenBatchQueue(draft, [
        ...(sourceKind === 'audio' ? [sourcePath.trim()] : []),
        ...(companionPath.trim() ? [companionPath.trim()] : []),
      ], sourceKind === 'folder' ? sourcePath.trim() : undefined)
      return
    }
    setSubmitting(true)
    setError('')
    setNotice('')
    const isDubbing = scenario !== 'subtitle'
    const speech = draft.graph.nodes.find(node => node.kind === 'tts')
    const translation = draft.graph.nodes.find(node => node.kind === 'translate')
    const { speech_recipe_id: recipeId, ...speechOptions } = speech?.options ?? {}
    const voicePlan = speech ? { ...speechOptions, ...(recipeId ? { recipe_id: recipeId } : {}) } : undefined

    const payload: DraftPrepareRequest = {
      path_or_dir: sourcePath.trim(),
      ...(companionPath.trim()
        ? isScript
          ? { script_path: companionPath.trim() }
          : { subtitle_path: companionPath.trim() }
        : {}),
      source_lang: sourceLang,
      target_lang: targetLang,
      enable_translation: Boolean(translation),
      duration_aware: translation?.options.duration_aware === true,
      auto_detect_delivery: draft.graph.nodes.some(node => node.kind === 'delivery_detect'),
      prepare_stems: scenario === 'binaural_dub',
      separation_model: scenario === 'binaural_dub' ? separationModel : null,
      extract_voice_reference: isDubbing,
      synthesize_samples: isDubbing && sampleCueCount > 0,
      sample_cue_count: isDubbing ? sampleCueCount : 0,
      voice_plan: voicePlan,
    }

    try {
      const created = await draftsApi.prepare(payload)
      setNotice(`已创建待审草稿「${created.title || created.draft_id}」。`)
      try {
        const pending = await draftsApi.list({ state: 'awaiting_review', limit: 50 })
        setPendingDraftCount(pending.drafts.length)
      } catch {}
      await openReview('drafts')
    } catch (err) {
      setError(`启动失败：${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="wb-layout">
      {/* Center Media Workspace */}
      <section
        className={`wb-stage${dragOver ? ' is-drag-over' : ''}`}
        aria-label={t('素材工作区')}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragOver(false) }}
        onDrop={(e) => void handleDrop(e)}
      >
        <div className="wb-stage-toolbar">
          <div className="wb-stage-toolbar__left">
            <button type="button" className="wb-btn wb-btn--primary" onClick={() => void pickAudio()}>
              {t('＋ 导入音频')}
            </button>
            <button type="button" className="wb-btn" onClick={() => void pickWorkDir()}>
              {t('扫描作品目录')}
            </button>
            <button type="button" className="wb-btn" onClick={() => void pickCompanion()}>
              {t('附加字幕 / 台本')}
            </button>
          </div>
          <div className="wb-stage-toolbar__right">
            {pendingDraftCount > 0 && (
              <button type="button" className="wb-pending-chip" onClick={() => void openReview('drafts')}>
                {pendingDraftCount} {t('份待审草稿 ↗')}
              </button>
            )}
          </div>
        </div>

        {error && <div className="wb-banner is-error" role="alert">{t(error)}</div>}
        {notice && <div className="wb-banner" role="status">{t(notice)}</div>}

        <div className="wb-canvas">
          {mediaRows.length === 0 ? (
            <div className="wb-dropzone">
              <div className="wb-dropzone__icon" aria-hidden="true">
                <svg width="36" height="36" viewBox="0 0 36 36" fill="none" stroke="currentColor" strokeWidth="1.6">
                  <rect x="4" y="6" width="28" height="24" rx="4" />
                  <path d="M12 22v-6M18 24V12M24 20v-4" strokeLinecap="round" />
                </svg>
              </div>
              <h2>{t('拖入音声文件、作品文件夹或台本')}</h2>
              <p>{t('支持 WAV / FLAC / MP3 / M4A，指向作品目录时自动识别无损主轨、已有分轨与同名字幕。')}</p>
              <div className="wb-dropzone__actions">
                <button type="button" className="wb-btn wb-btn--primary" onClick={() => void pickAudio()}>
                  {t('选择音频文件')}
                </button>
                <button type="button" className="wb-btn" onClick={() => void pickWorkDir()}>
                  {t('选择作品目录（如 RJxxxxxx）')}
                </button>
              </div>
            </div>
          ) : (
            <div className="wb-media-panel">
              <div className="wb-media-header">
                <span>{t('当前素材')}</span>
                <span>{t('类型')}</span>
                <span>{t('路径')}</span>
                <span>{t('操作')}</span>
              </div>
              {mediaRows.map((row) => (
                <div className="wb-media-row" key={row.id}>
                  <strong className="wb-media-name" title={row.name}>{row.name}</strong>
                  <span className={`wb-type-badge is-${row.kind}`}>
                    {row.kind === 'audio' ? t('主音频') : row.kind === 'folder' ? t('作品目录') : row.kind === 'script' ? t('台本') : t('字幕')}
                  </span>
                  <span className="wb-media-path" title={row.path}>{displayPath(row.path)}</span>
                  <div className="wb-media-actions">
                    {row.kind === 'folder' && inspectResult && (
                      <button type="button" className="wb-mini-btn" aria-expanded={directoryExpanded}
                        aria-controls={directoryDetailsId} onClick={() => setDirectoryExpanded(open => !open)}>
                        {directoryExpanded ? t('收起详情') : t('展开详情')}
                      </button>
                    )}
                    {row.kind === 'audio' && (
                      <button
                        type="button"
                        className="wb-mini-btn"
                        onClick={() => showAudio(row.path, row.name)}
                      >
                        {t('试听')}
                      </button>
                    )}
                    <button
                      type="button"
                      className="wb-mini-btn is-danger"
                      onClick={() => {
                        if (row.id === 'primary') {
                          inspectionRequest.current += 1
                          setSourcePath('')
                          setInspection(null)
                        } else {
                          setCompanionPath('')
                        }
                      }}
                    >
                      {t('移除')}
                    </button>
                  </div>
                </div>
              ))}

              {inspection?.state === 'pending' && <div className="wb-inspect-bar" role="status">{t('正在检查素材…')}</div>}
              {inspection?.state === 'failed' && sourceKind === 'folder' && (
                <div className="wb-inspect-bar">
                  <span role="alert">{format('扫描失败：{0}', [inspection.message])}</span>
                  <button type="button" className="wb-mini-btn" onClick={() => void inspectSource(sourcePath, 'folder')}>
                    {t('重新扫描')}
                  </button>
                </div>
              )}
              {inspectResult && (
                <div className="wb-inspect-bar">
                  <strong>{t('目录探测完成')}</strong>
                  <span>{t('音频')} {inspectResult.audio_files.length}</span>
                  <span>{t('字幕')} {inspectResult.subtitles.length}</span>
                  <span>{t('台本')} {inspectResult.scripts.length}</span>
                  <span>{t('含分轨的音轨')} {inspectResult.stem_pairs.filter(pair => pair.vocals || pair.no_se || pair.se_only).length}</span>
                </div>
              )}
              {sourceKind === 'folder' && inspectResult && (
                <div id={directoryDetailsId} hidden={!directoryExpanded}>
                  {directoryExpanded && <StudioDirectoryDetails result={inspectResult} onListen={showAudio} />}
                </div>
              )}
            </div>
          )}
        </div>

        <div className="wb-stage-statusbar">
          <span>{t('流程：')}{t(SCENARIO_META[scenario].hint)}</span>
        </div>
      </section>

      {/* Right Fixed Inspector */}
      <aside className="wb-inspector" aria-label={t('制作配置')}>
        <div className="wb-inspector__head">
          <h2>{t('制作配置')}</h2>
          <button type="button" className="wb-text-link" onClick={() => void onOpenGraphEditor(draft)}>
            {t('查看当前流程 ↗')}
          </button>
        </div>

        <div className="wb-inspector__body">
          <div className="wb-prop">
            <span className="wb-prop__label">{t('处理模式')}</span>
            <div className="wb-segmented" role="group" aria-label={t('处理模式')}>
              {(['binaural_dub', 'subtitle', 'script_dub'] as StudioScenario[]).map((id) => (
                <button
                  key={id}
                  type="button"
                  aria-pressed={scenario === id}
                  onClick={() => setScenario(id)}
                >
                  {t(SCENARIO_META[id].label)}
                </button>
              ))}
            </div>
          </div>

          <div className="wb-prop">
            <span className="wb-prop__label">{t('语言转换')}</span>
            <div className="wb-lang-row">
              <select aria-label={t('源语言')} value={sourceLang} onChange={(e) => setSourceLang(e.target.value as GraphLanguage)}>
                <option value="ja">{t('日语')}</option>
                <option value="en">{t('英语')}</option>
                <option value="zh">{t('中文')}</option>
              </select>
              <span className="wb-arrow">→</span>
              <select aria-label={t('目标语言')} value={targetLang} onChange={(e) => setTargetLang(e.target.value as GraphLanguage)}>
                <option value="zh">{t('中文')}</option>
                <option value="en">{t('英语')}</option>
                <option value="ja">{t('日语')}</option>
              </select>
            </div>
          </div>

          {scenario !== 'subtitle' && (
            <>
              <div className="wb-prop">
                <span className="wb-prop__label">{t('重制质量档位')}</span>
                <div className="wb-segmented" role="group" aria-label={t('重制质量档位')}>
                  {(['fast', 'asmr', 'studio'] as RemakeTier[]).map((id) => (
                    <button
                      key={id}
                      type="button"
                      aria-pressed={tier === id}
                      onClick={() => setTier(id)}
                    >
                      {t(REMAKE_TIERS[id].label)}
                    </button>
                  ))}
                </div>
                <p className="wb-prop__hint">{t(REMAKE_TIERS[tier].summary)}</p>
              </div>

              <div className="wb-prop">
                <div className="wb-prop__head">
                  <span className="wb-prop__label">{t('配音音色')}</span>
                  <button type="button" className="wb-text-link" onClick={() => void setPage('voice-lab')}>
                    {t('音色库 ↗')}
                  </button>
                </div>
                <select value={selectedRecipeId} onChange={(e) => setSelectedRecipeId(e.target.value)}>
                  <option value="">{t('自动克隆原声（失败时用默认音色）')}</option>
                  {recipes.map((r) => (
                    <option key={r.id} value={r.id}>{r.name} · {r.provider_id}</option>
                  ))}
                </select>
              </div>
            </>
          )}

          <details className="wb-accordion">
            <summary>{t('高级选项')}</summary>
            <div className="wb-accordion__content">
              {scenario === 'binaural_dub' && (
                <label className="wb-prop">
                  <span className="wb-prop__label">{t('人声分离模型')}</span>
                  <select
                    value={separationModel}
                    onChange={(e) => setSeparationModel(e.target.value as 'mel_band_roformer' | 'htdemucs')}
                  >
                    <option value="mel_band_roformer">{t('Mel-Band Roformer（推荐）')}</option>
                    <option value="htdemucs">HTDemucs</option>
                  </select>
                </label>
              )}
              {reviewBeforeRun && scenario !== 'subtitle' && (
                <label className="wb-prop">
                  <span className="wb-prop__label">{t('草稿试听')}</span>
                  <select value={sampleCueCount} onChange={(e) => setSampleCueCount(Number(e.target.value))}>
                    <option value={2}>{t('2 句代表样音（推荐）')}</option>
                    <option value={1}>{t('1 句样音')}</option>
                    <option value={0}>{t('不生成样音')}</option>
                  </select>
                </label>
              )}
              <label className="wb-check">
                <input type="checkbox" checked={durationAware} onChange={(e) => setDurationAware(e.target.checked)} />
                <span>{t('翻译约束字数（防超速变速）')}</span>
              </label>
              {tier === 'studio' && scenario !== 'subtitle' && (
                <div className="wb-prop">
                  <label className="wb-check">
                    <input type="checkbox" checked={enableSeedVc} onChange={(e) => setEnableSeedVc(e.target.checked)} />
                    <span>{t('Seed-VC 音色转换')}</span>
                  </label>
                  <p className="wb-prop__hint">{t('让已合成的语音更接近参考录音的音色。需要远端 GPU Worker。')}</p>
                </div>
              )}
            </div>
          </details>
        </div>

        <footer className="wb-inspector__foot">
          <label className="wb-check wb-gate-check">
            <input type="checkbox" checked={reviewBeforeRun} onChange={(e) => setReviewBeforeRun(e.target.checked)} />
            <span>{scenario === 'subtitle' ? t('导出前核对字幕') : t('配音前核对台词')}</span>
          </label>
          <button
            type="button"
            className="wb-run-btn"
            disabled={submitting || !sourcePath.trim()}
            onClick={() => void handleStart()}
          >
            {submitting ? t('正在准备草稿…') : reviewBeforeRun ? t('生成草稿并核对') : t('打开批量队列')}
          </button>
        </footer>
      </aside>
    </div>
  )
}
