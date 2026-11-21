import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import ts from 'typescript'

const source = readFileSync(new URL('../src/domain/modelDownloads.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } })
const drama = { model_id: 'fish_drama3', display_name: 'Fish Audio Drama 3', estimated_size_mb: 41503 }

function fixture(confirmed) {
  const confirmations = []
  const module = { exports: {} }
  const imports = {
    '@/i18n': { t: value => value, format: (template, args) => template.replace(/\{(\d+)\}/g, (_, index) => args[index]) },
    '@/utils/confirmAction': { confirmAction: async message => { confirmations.push(message); return confirmed } },
  }
  new Function('require', 'module', 'exports', outputText)(name => imports[name], module, module.exports)
  return { prepare: module.exports.prepareModelDownload, confirmations }
}

test('cancelling full Drama 3 download produces no request', async () => {
  const { prepare, confirmations } = fixture(false)
  assert.equal(await prepare(drama), undefined)
  assert.equal(confirmations.length, 1)
  assert.match(confirmations[0], /41\.50 GB/)
  assert.match(confirmations[0], /Linux 或 WSL2/)
  assert.match(confirmations[0], /37 GB 显存/)
})

test('only an approved large download sends the explicit backend consent', async () => {
  const { prepare, confirmations } = fixture(true)
  assert.deepEqual(await prepare({ model_id: 'qwen3', default_install_mode: 'single' }), { install_mode: 'single' })
  assert.equal(confirmations.length, 0)
  assert.deepEqual(await prepare({ ...drama, download_warning: 'Backend download and hardware details.' }), {
    install_mode: 'single', confirm_large_download: true,
  })
  assert.match(confirmations[0], /Backend download and hardware details/)
})
