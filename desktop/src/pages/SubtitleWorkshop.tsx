import { useState } from 'react'
import { NeuCard, NeuButton, NeuInput, NeuSelect } from '@/components/ui'
import { subtitlesApi } from '@/api/subtitles'
import { useFileSelector } from '@/hooks/useFileSelector'
import type { SubtitleSegmentModel, ScriptToVttRequest } from '@/api/types'

export default function SubtitleWorkshop() {
    const [segments, setSegments] = useState<SubtitleSegmentModel[]>([])
    const [translations, setTranslations] = useState<string[]>([])
    const [filePath, setFilePath] = useState('')
    const [scriptPath, setScriptPath] = useState('')
    const [exportFormat, setExportFormat] = useState('srt')
    const [exportPath, setExportPath] = useState('')
    const [provider, setProvider] = useState('deepseek')
    const [loading, setLoading] = useState('')
    const [message, setMessage] = useState('')
    const { selectFiles } = useFileSelector()

    const handleLoadSubtitle = async () => {
        if (!filePath) return
        setLoading('load')
        setMessage('')
        try {
            const res = await subtitlesApi.load({ file_path: filePath })
            setSegments(res.segments)
            setTranslations([])
            setMessage(`已加载 ${res.segments.length} 条字幕`)
        } catch (err) {
            setMessage(`加载失败: ${err}`)
        } finally {
            setLoading('')
        }
    }

    const handleTranslate = async () => {
        if (segments.length === 0) return
        setLoading('translate')
        setMessage('')
        try {
            const res = await subtitlesApi.translate({
                segments,
                provider,
                source_lang: 'ja',
                target_lang: 'zh',
            })
            if (res.segments) {
                setTranslations(res.segments.map((s: SubtitleSegmentModel) => s.text))
            }
            setMessage('翻译完成')
        } catch (err) {
            setMessage(`翻译失败: ${err}`)
        } finally {
            setLoading('')
        }
    }

    const handleExport = async () => {
        if (segments.length === 0 || !exportPath) return
        setLoading('export')
        setMessage('')
        try {
            await subtitlesApi.export({
                segments,
                output_path: exportPath,
            })
            setMessage(`已导出到: ${exportPath}`)
        } catch (err) {
            setMessage(`导出失败: ${err}`)
        } finally {
            setLoading('')
        }
    }

    const handleScriptToSubtitle = async () => {
        if (!scriptPath) return
        setLoading('script')
        setMessage('')
        try {
            const req: ScriptToVttRequest = {
                script_path: scriptPath,
                fmt: exportFormat,
                use_llm_clean: true,
            }
            const res = await subtitlesApi.scriptToVtt(req)
            setMessage(`台本转字幕完成: ${res.line_count} 行 (${res.mode})`)
        } catch (err) {
            setMessage(`台本转字幕失败: ${err}`)
        } finally {
            setLoading('')
        }
    }

    const handleSelectFile = async (setter: (v: string) => void) => {
        const files = await selectFiles()
        if (files.length > 0) setter(files[0]!)
    }

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', maxWidth: '900px' }}>
            {/* Status Message */}
            {message && (
                <div style={{
                    padding: '8px 12px',
                    borderRadius: '8px',
                    background: message.includes('失败') ? 'rgba(239,68,68,0.1)' : 'rgba(34,197,94,0.1)',
                    color: message.includes('失败') ? '#ef4444' : '#22c55e',
                    fontSize: '0.875rem',
                }}>
                    {message}
                </div>
            )}

            {/* Load Subtitle */}
            <NeuCard>
                <div style={{ fontWeight: 600, marginBottom: '12px', color: 'var(--text-primary)' }}>
                    加载字幕
                </div>
                <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-end' }}>
                    <NeuButton onClick={() => handleSelectFile(setFilePath)}>选择文件</NeuButton>
                    <div style={{ flex: 1 }}>
                        <NeuInput
                            label="字幕文件路径"
                            value={filePath}
                            onChange={(e) => setFilePath(e.target.value)}
                            placeholder="SRT / VTT / LRC 文件..."
                        />
                    </div>
                    <NeuButton
                        variant="primary"
                        disabled={!filePath || loading === 'load'}
                        onClick={handleLoadSubtitle}
                    >
                        {loading === 'load' ? '加载中...' : '加载'}
                    </NeuButton>
                </div>
            </NeuCard>

            {/* Segment Display */}
            {segments.length > 0 && (
                <NeuCard>
                    <div style={{ fontWeight: 600, marginBottom: '12px', color: 'var(--text-primary)' }}>
                        字幕内容 ({segments.length} 条)
                    </div>
                    <div style={{
                        maxHeight: '300px',
                        overflowY: 'auto',
                        borderRadius: '8px',
                        background: 'var(--bg-base)',
                        boxShadow: 'var(--shadow-pressed)',
                        padding: '8px',
                    }}>
                        {segments.map((seg, i) => (
                            <div key={i} style={{
                                display: 'grid',
                                gridTemplateColumns: '80px 1fr 1fr',
                                gap: '8px',
                                padding: '6px 8px',
                                borderBottom: '1px solid rgba(0,0,0,0.05)',
                                fontSize: '0.8125rem',
                            }}>
                                <span style={{ color: 'var(--text-secondary)', fontFamily: 'monospace' }}>
                                    {seg.start.toFixed(1)}s
                                </span>
                                <span style={{ color: 'var(--text-primary)' }}>{seg.text}</span>
                                <span style={{ color: 'var(--accent-text)' }}>
                                    {translations[i] || ''}
                                </span>
                            </div>
                        ))}
                    </div>
                </NeuCard>
            )}

            {/* Translate */}
            {segments.length > 0 && (
                <NeuCard>
                    <div style={{ fontWeight: 600, marginBottom: '12px', color: 'var(--text-primary)' }}>
                        翻译
                    </div>
                    <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-end' }}>
                        <NeuSelect
                            label="翻译提供商"
                            value={provider}
                            onChange={(e) => setProvider(e.target.value)}
                            options={[
                                { value: 'deepseek', label: 'DeepSeek' },
                                { value: 'openai', label: 'OpenAI' },
                            ]}
                        />
                        <NeuButton
                            variant="primary"
                            disabled={loading === 'translate'}
                            onClick={handleTranslate}
                        >
                            {loading === 'translate' ? '翻译中...' : '翻译'}
                        </NeuButton>
                    </div>
                </NeuCard>
            )}

            {/* Export */}
            {segments.length > 0 && (
                <NeuCard>
                    <div style={{ fontWeight: 600, marginBottom: '12px', color: 'var(--text-primary)' }}>
                        导出
                    </div>
                    <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-end' }}>
                        <NeuSelect
                            label="格式"
                            value={exportFormat}
                            onChange={(e) => setExportFormat(e.target.value)}
                            options={[
                                { value: 'srt', label: 'SRT' },
                                { value: 'vtt', label: 'VTT' },
                                { value: 'lrc', label: 'LRC' },
                            ]}
                        />
                        <div style={{ flex: 1 }}>
                            <NeuInput
                                label="输出路径"
                                value={exportPath}
                                onChange={(e) => setExportPath(e.target.value)}
                                placeholder="输出文件路径..."
                            />
                        </div>
                        <NeuButton
                            variant="primary"
                            disabled={!exportPath || loading === 'export'}
                            onClick={handleExport}
                        >
                            {loading === 'export' ? '导出中...' : '导出'}
                        </NeuButton>
                    </div>
                </NeuCard>
            )}

            {/* Script to Subtitle */}
            <NeuCard>
                <div style={{ fontWeight: 600, marginBottom: '12px', color: 'var(--text-primary)' }}>
                    台本转字幕
                </div>
                <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-end' }}>
                    <NeuButton onClick={() => handleSelectFile(setScriptPath)}>选择台本</NeuButton>
                    <div style={{ flex: 1 }}>
                        <NeuInput
                            label="台本文件路径"
                            value={scriptPath}
                            onChange={(e) => setScriptPath(e.target.value)}
                            placeholder="PDF / TXT 台本文件..."
                        />
                    </div>
                    <NeuButton
                        variant="primary"
                        disabled={!scriptPath || loading === 'script'}
                        onClick={handleScriptToSubtitle}
                    >
                        {loading === 'script' ? '处理中...' : '转换'}
                    </NeuButton>
                </div>
            </NeuCard>
        </div>
    )
}
