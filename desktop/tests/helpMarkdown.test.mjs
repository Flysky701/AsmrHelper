import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import ts from 'typescript'
const require = createRequire(import.meta.url)
const source = readFileSync(new URL('../src/components/HelpMarkdown.tsx', import.meta.url), 'utf8')
const module = { exports: {} }
new Function('require', 'module', 'exports', ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText)(require, module, module.exports)
const { default: HelpMarkdown, safeHelpUrl } = module.exports
const render = text => renderToStaticMarkup(React.createElement(HelpMarkdown, { source: text }))

test('raw HTML, scripts and unsafe links never execute', () => {
  const html = render('<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>\n\n[bad](javascript:alert(1)) [bad](data:text/html,hello) [bad](file:///secret)')
  assert.doesNotMatch(html, /<script|<img|href="(?:javascript|data|file):/)
  assert.match(html, /&lt;script&gt;/)
  for (const url of ['javascript:alert(1)', 'data:text/html,x', 'file:///x', 'https://user:pass@example.com', 'https://example.com\n/x', 'javascript&#58;alert(1)']) assert.equal(safeHelpUrl(url), null)
  assert.equal(safeHelpUrl('https://example.com/x'), 'https://example.com/x')
})
