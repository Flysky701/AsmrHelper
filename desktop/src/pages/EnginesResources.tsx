import { useEffect, useState } from 'react'
import { NeuCard, NeuButton, NeuTag } from '@/components/ui'
import { modelsApi } from '@/api/models'
import { resourcesApi } from '@/api/resources'
import { enginesApi } from '@/api/engines'
import type { ModelSummaryResponse, ModelStatusResponse, ResourceStatusResponse } from '@/api/types'
import type { EngineDescriptor, ProviderDescriptor } from '@/api/engines'

export default function EnginesResources() {
    const [resources, setResources] = useState<ResourceStatusResponse[]>([])
    const [models, setModels] = useState<ModelSummaryResponse[]>([])
    const [modelStatuses, setModelStatuses] = useState<ModelStatusResponse[]>([])
    const [ttsEngines, setTtsEngines] = useState<EngineDescriptor[]>([])
    const [asrEngines, setAsrEngines] = useState<EngineDescriptor[]>([])
    const [llmProviders, setLlmProviders] = useState<ProviderDescriptor[]>([])
    const [loading, setLoading] = useState(true)

    useEffect(() => {
        loadData()
    }, [])

    const loadData = async () => {
        setLoading(true)
        try {
            const [resData, modelData, statusData, ttsData, asrData, llmData] = await Promise.all([
                resourcesApi.getStatus().catch(() => ({ resources: [] })),
                modelsApi.list().catch(() => []),
                modelsApi.statuses().catch(() => []),
                enginesApi.ttsEngines().catch(() => ({ engines: [] })),
                enginesApi.asrEngines().catch(() => ({ engines: [] })),
                enginesApi.llmProviders().catch(() => ({ providers: [] })),
            ])
            setResources(resData.resources)
            setModels(modelData)
            setModelStatuses(statusData)
            setTtsEngines(ttsData.engines)
            setAsrEngines(asrData.engines)
            setLlmProviders(llmData.providers)
        } finally {
            setLoading(false)
        }
    }

    const handleInstall = async (modelId: string) => {
        await modelsApi.install(modelId).catch(() => { })
        loadData()
    }

    const handleUnload = async (modelId: string) => {
        await modelsApi.unload(modelId).catch(() => { })
        loadData()
    }

    const handleRemove = async (modelId: string) => {
        await modelsApi.remove(modelId).catch(() => { })
        loadData()
    }

    if (loading) {
        return (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '200px', color: 'var(--text-secondary)' }}>
                加载中...
            </div>
        )
    }

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            {/* System Status */}
            <section>
                <h2 style={{ fontSize: '1.125rem', fontWeight: 600, marginBottom: '12px', color: 'var(--text-primary)' }}>
                    系统状态
                </h2>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '12px' }}>
                    {resources.map((res) => (
                        <NeuCard key={res.name}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <span style={{ fontWeight: 500, fontSize: '0.875rem' }}>{res.name}</span>
                                <NeuTag variant={res.available ? 'success' : 'error'}>
                                    {res.available ? '可用' : '不可用'}
                                </NeuTag>
                            </div>
                            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '4px' }}>
                                {res.detail}
                            </div>
                        </NeuCard>
                    ))}
                    {resources.length === 0 && (
                        <div style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
                            未检测到资源信息
                        </div>
                    )}
                </div>
            </section>

            {/* Engine Capabilities */}
            <section>
                <h2 style={{ fontSize: '1.125rem', fontWeight: 600, marginBottom: '12px', color: 'var(--text-primary)' }}>
                    引擎能力
                </h2>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '12px' }}>
                    {/* TTS Engines */}
                    <NeuCard>
                        <div style={{ fontWeight: 600, fontSize: '0.875rem', marginBottom: '8px' }}>TTS 引擎</div>
                        {ttsEngines.length > 0 ? ttsEngines.map((e) => (
                            <div key={e.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 0' }}>
                                <span style={{ fontSize: '0.8125rem' }}>{e.name || e.id}</span>
                                <NeuTag variant="success">{e.status || '可用'}</NeuTag>
                            </div>
                        )) : (
                            <div style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>未检测到引擎</div>
                        )}
                    </NeuCard>

                    {/* ASR Engines */}
                    <NeuCard>
                        <div style={{ fontWeight: 600, fontSize: '0.875rem', marginBottom: '8px' }}>ASR 引擎</div>
                        {asrEngines.length > 0 ? asrEngines.map((e) => (
                            <div key={e.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 0' }}>
                                <span style={{ fontSize: '0.8125rem' }}>{e.name || e.id}</span>
                                <NeuTag variant="success">{e.status || '可用'}</NeuTag>
                            </div>
                        )) : (
                            <div style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>未检测到引擎</div>
                        )}
                    </NeuCard>

                    {/* LLM Providers */}
                    <NeuCard>
                        <div style={{ fontWeight: 600, fontSize: '0.875rem', marginBottom: '8px' }}>LLM 提供商</div>
                        {llmProviders.length > 0 ? llmProviders.map((p) => (
                            <div key={p.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 0' }}>
                                <span style={{ fontSize: '0.8125rem' }}>{p.name || p.id}</span>
                                <NeuTag variant="success">{p.status || '可用'}</NeuTag>
                            </div>
                        )) : (
                            <div style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>未检测到提供商</div>
                        )}
                    </NeuCard>
                </div>
            </section>

            {/* Model Management */}
            <section>
                <h2 style={{ fontSize: '1.125rem', fontWeight: 600, marginBottom: '12px', color: 'var(--text-primary)' }}>
                    模型管理
                </h2>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {models.map((model) => {
                        const status = modelStatuses.find((s) => s.model_id === model.model_id)
                        return (
                            <NeuCard key={model.model_id}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                    <div>
                                        <span style={{ fontWeight: 500, fontSize: '0.875rem' }}>{model.display_name}</span>
                                        <div style={{ display: 'flex', gap: '6px', marginTop: '4px' }}>
                                            <NeuTag>{model.kind}</NeuTag>
                                            <NeuTag>{model.category}</NeuTag>
                                            {status && (
                                                <NeuTag variant={status.status === 'ready' || status.status === 'installed' ? 'success' : 'default'}>
                                                    {status.status}
                                                </NeuTag>
                                            )}
                                        </div>
                                    </div>
                                    <div style={{ display: 'flex', gap: '8px' }}>
                                        <NeuButton size="sm" onClick={() => handleInstall(model.model_id)}>
                                            安装
                                        </NeuButton>
                                        <NeuButton size="sm" onClick={() => handleUnload(model.model_id)}>
                                            卸载
                                        </NeuButton>
                                        <NeuButton size="sm" variant="danger" onClick={() => handleRemove(model.model_id)}>
                                            删除
                                        </NeuButton>
                                    </div>
                                </div>
                            </NeuCard>
                        )
                    })}
                    {models.length === 0 && (
                        <div style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
                            未发现可用模型
                        </div>
                    )}
                </div>
            </section>
        </div>
    )
}
