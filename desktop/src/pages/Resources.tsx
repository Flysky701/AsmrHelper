import { useEffect, useState } from 'react'
import { NeuCard, NeuButton, NeuInput, NeuTag } from '@/components/ui'
import { modelsApi } from '@/api/models'
import { resourcesApi } from '@/api/resources'
import type { ModelSummaryResponse, ModelStatusResponse, ResourceStatusResponse } from '@/api/types'

export default function Resources() {
  const [resources, setResources] = useState<ResourceStatusResponse[]>([])
  const [models, setModels] = useState<ModelSummaryResponse[]>([])
  const [modelStatuses, setModelStatuses] = useState<ModelStatusResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [apiKey, setApiKey] = useState('')
  const [apiProvider, setApiProvider] = useState('deepseek')

  useEffect(() => {
    loadData()
  }, [])

  const loadData = async () => {
    setLoading(true)
    try {
      const [resData, modelData, statusData] = await Promise.all([
        resourcesApi.getStatus().catch(() => ({ resources: [] })),
        modelsApi.list().catch(() => []),
        modelsApi.statuses().catch(() => []),
      ])
      setResources(resData.resources)
      setModels(modelData)
      setModelStatuses(statusData)
    } finally {
      setLoading(false)
    }
  }

  const handleInstall = async (modelId: string) => {
    await modelsApi.install(modelId).catch(() => {})
    loadData()
  }

  const handleRemove = async (modelId: string) => {
    await modelsApi.remove(modelId).catch(() => {})
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
      <div>
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
      </div>

      {/* Model Management */}
      <div>
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
                        <NeuTag variant={status.status === 'ready' ? 'success' : 'default'}>
                          {status.status}
                        </NeuTag>
                      )}
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <NeuButton size="sm" onClick={() => handleInstall(model.model_id)}>
                      安装
                    </NeuButton>
                    <NeuButton size="sm" variant="danger" onClick={() => handleRemove(model.model_id)}>
                      卸载
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
      </div>

      {/* LLM API Config */}
      <div>
        <h2 style={{ fontSize: '1.125rem', fontWeight: 600, marginBottom: '12px', color: 'var(--text-primary)' }}>
          LLM API 配置
        </h2>
        <NeuCard>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', maxWidth: '400px' }}>
            <div style={{ display: 'flex', gap: '8px' }}>
              <NeuButton
                size="sm"
                variant={apiProvider === 'deepseek' ? 'primary' : 'secondary'}
                onClick={() => setApiProvider('deepseek')}
              >
                DeepSeek
              </NeuButton>
              <NeuButton
                size="sm"
                variant={apiProvider === 'openai' ? 'primary' : 'secondary'}
                onClick={() => setApiProvider('openai')}
              >
                OpenAI
              </NeuButton>
            </div>
            <NeuInput
              label={`${apiProvider} API Key`}
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="输入 API Key..."
            />
            <NeuButton variant="primary" disabled={!apiKey}>
              测试连接
            </NeuButton>
          </div>
        </NeuCard>
      </div>
    </div>
  )
}
