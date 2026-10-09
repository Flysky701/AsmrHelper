# ASMR Helper 品牌素材

## 当前采用：角色方案

用户确认的 Q 版耳机头像和无耳机安装插画已接入源码。源图及版式位于 `character/`；下方原始耳机符号方案仅作历史设计预览，未被应用引用。

- `character/icon-source.png`：已修复两处背景瑕疵的最终 Q 版图标。
- `character/installer-art.png`：浅金长发角色安装侧图，无耳机。
- `character/installer-sidebar.svg`：164 × 314 侧图模板，`ART_DATA` 由导出脚本替换为内嵌原图。
- `character/installer-header.svg`：150 × 57 纯文字页眉。
- `../src-tauri/icons/character/`：Windows 多尺寸 ICO、512px PNG、24 位 BMP。
- `../public/brand/`：导航栏 PNG 与多尺寸 favicon，均来自同一张确认图。

重新导出：`.\.venv\Scripts\python.exe scripts/export_character_brand.py`。需要现有 Pillow 和 desktop npm 依赖，不增加应用运行时依赖。安装模板以四倍尺寸渲染后缩小，以改善插画线条和文字抗锯齿。

Tauri/NSIS 配置已引用此方案。前端已接入导航栏和 favicon。实际 Windows 可执行文件和安装包仍需重新构建才会更新；生成与前端构建不等于原生安装验收。

原图使用内置 imagegen 生成/编辑。图标提示方向：保留浅金发、蓝灰眼和双呆毛，只留 Q 版脸部与耳机，粗轮廓、深蓝圆角底，修复背景黑斑。安装侧图提示方向：保持长发、白衣、格纹领和原角色面部，移除耳机，深蓝背景，顶部留品牌排版空间，底部淡入背景；不在插画中生成文字或控件。

## 早期耳机符号方案（未采用）

项目定位是支持节点流水线、字幕、配音、音色与混音的 Windows 音频制作工作台。图标采用耳机外轮廓与三段圆头声波，延续界面的青蓝色和深色导航；不在小图标中放字母或复杂节点。

- 主色：深青 `#152F3B` / `#28515C`，浅青 `#75D5DE`，近白 `#E8FAF9`。
- 应用源稿：`asmr-helper.svg`，512 × 512，外围透明，圆角底板自带安全边距。
- 安装向导源稿：`installer-sidebar.svg`（164 × 314）和 `installer-header.svg`（150 × 57）。
- 候选导出素材：`exports/`，包含 RGBA PNG、多尺寸 ICO、24 位 RGB BMP。
- 预览：`brand-preview.png`。安装向导部分是布局示意，不是实际安装截图；文案和原生控件仍由 NSIS 提供，未引入自定义安装模板。

当前仅供设计预览，未接入应用导航、网页 favicon、Tauri bundle 或 NSIS 配置。品牌素材不含版本号，正式版和测试版可复用。

在仓库根目录重新导出（需要项目 Python 的 Pillow、Node 和已安装的 desktop npm 依赖）：

```powershell
.\.venv\Scripts\python.exe scripts/generate_brand_assets.py
```

SVG 由 Tauri 自带渲染器导出；Pillow 负责 ICO/BMP 编码与移除矩形素材渲染时的空白补边。没有新增运行时依赖。

设计检查覆盖渲染预览、素材尺寸、透明通道和 ICO 子图。未构建安装包；实际安装向导、高 DPI 缩放及 Windows 图标缓存效果尚未核验。
