# Gemini 本地图像生成工具

## Android 手机版本

新增独立 Android 客户端：手机直接调用图像 API，支持多张参考图、连续生成、模型选择、提示词历史、保存相册和原图分享，无需开启电脑。

安装和构建说明见 [android/README.md](android/README.md)。安卓代码位于 `android/`，原有 Windows / macOS 版不受影响。

一个本地运行的 Gemini 图像生成工具，使用 `Gradio + google-genai` 实现，目标是替代 Google AI Studio 网页版的常用出图流程。

## 功能概览

- 本地 Web UI，默认地址 `http://127.0.0.1:7860`
- 顶部设置区内填写 API Key，不依赖 `.env`
- 支持 Google AI Studio 官方 Key，也支持 APIYI 这类 Gemini 原生中转
- 支持可选代理设置，适合国内网络环境
- 支持 `Grounding with Google Search` 和 `Image Search`
- 支持单张拖入 / 上传 / 粘贴参考图，也支持批量拖入多张参考图
- 支持参考图预览、放大确认与顺序调整，方便按“图1 / 图2 / 图3”描述
- 支持独立 Prompt 历史保存与复用，不恢复会话记录
- 支持按日期保存输出，并自动写入单独的备份目录
- 出图储存位置和备份目录都支持“直接填写路径”或“点击选择...”调用系统原生目录选择框
- 支持单张下载与 ZIP 打包下载

## 环境要求

- Python 3.10+
- Windows 或 macOS
- Chrome / Edge / Safari 等现代浏览器

## 获取 API Key

Google AI Studio API Key 申请地址：

- [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey)

## 快速启动

### Windows

直接启动：

```text
Start.bat
```

可选：创建桌面快捷方式：

```text
Install_Shortcut.bat
```

启动后会自动打开浏览器；如果没有自动打开，手动访问：

```text
http://127.0.0.1:7860
```

### 手动命令行启动

```powershell
python app.py
```

启动后浏览器访问：

- [http://127.0.0.1:7860](http://127.0.0.1:7860)

## 使用说明

1. 在顶部“设置”区域填写 API Key。
2. 如果是 Google 官方 Gemini API，`Gemini Base URL` 留空即可。
3. 如果是 APIYI 这类 Gemini 原生中转，在 `Gemini Base URL` 填根域名，例如 `https://api.apiyi.com`。
4. 如需代理，在“代理”中填写本机 `HTTP` 或 `SOCKS5` 地址。
5. 在“出图储存位置”中填写主输出目录。
6. 在“备份目录”中填写你希望保存备份的目录。
7. 如需像安装软件那样点选目录，可点击输入框旁边的“选择...”按钮，调用系统原生目录选择框。
8. 点击“保存设置”写入本地 `data/config.json`。
9. 点击“测试连接”确认 API Key 可用。
10. 参考图支持三种入口：上方“新增参考图”可单张拖入 / 上传 / 粘贴，下方“批量添加参考图”可一次拖入多张。
11. 参考图加入后可在预览区放大确认，并通过“左移 / 右移”调整顺序。
12. 如需联网增强，可开启 `Grounding with Google Search`，需要图片检索时再勾上 `Image Search`。
13. 选择模型、宽高比、分辨率、生成数量和种子策略。
14. 如需复用旧提示词，可在“Prompt 历史”中选择并填回输入框。
15. 点击“开始生成”。

## 输出目录规则

程序会把图片按日期保存，同时自动备份：

```text
<主输出目录>/
  YYYY-MM-DD/
    *.png
    *_all.zip
    batches/
      <批量任务文件夹>/
        ...
<备份目录>/
  YYYY-MM-DD/
    *.png
    *_all.zip
    batches/
      <批量任务文件夹>/
        ...
```

说明：

- 主输出目录和备份目录可以分别设置
- 普通出图直接进入当天日期文件夹
- 批量生图进入当天日期文件夹下的 `batches/`
- 每次生成的图片和 ZIP 都会在备份目录保留一份

## 参考图上传

- “新增参考图”支持单张拖入、点击上传和 `Ctrl + V` 粘贴
- “批量添加参考图”支持一次拖入多张或一次多选上传多张
- 图片加入后会显示在预览区，可点击放大确认
- 可通过“左移 / 右移 / 移除选中 / 清空参考图”管理顺序

## 已实现的关键行为

- API Key 修改后立即生效，不需要重启
- `data/config.json` 不存在或 Key 为空时，生成按钮自动禁用
- 所有 Gemini 请求统一设置为 5 分钟超时
- 对超时、配额不足、权限不足、Key 无效、内容被拒等错误做了友好提示
- 生成完成后会展示 grounding 查询词和来源摘要（若接口返回）

## 模型说明

### 1. Nano Banana 2

- `gemini-3.1-flash-image-preview`

支持：

- `512 / 1K / 2K / 4K`
- `1:1 / 4:3 / 3:4 / 16:9 / 9:16 / 4:1 / 1:4`
- `Grounding with Google Search`
- `Image Search`

### 2. Nano Banana Pro

- `gemini-3-pro-image-preview`

支持：

- `1K / 2K / 4K`
- `1:1 / 4:3 / 3:4 / 16:9 / 9:16`
- `Grounding with Google Search`

说明：

- `Image Search` 当前不在 Pro 模型上启用
- 当你在 Pro 模型上勾选 `Image Search` 时，程序会自动回退成仅 `Google Search`
- Pro 模型选择 `512` 时，程序会通过 `1K` 结果本地缩小实现
- Pro 模型选择 `4:1 / 1:4` 时，程序会通过接近比例生成后本地裁切实现

## 文件说明

- `app.py`：主程序，单文件即可启动
- `requirements.txt`：依赖列表
- `Start.bat`：Windows 便携版启动入口
- `Install_Shortcut.bat`：在桌面创建快捷方式
- `data/config.json`：本地保存 API Key、代理、Gemini Base URL、主输出目录和备份目录
- `data/prompt_history.json`：本地保存最近 Prompt 与基础参数，用于挑选复用
- `data/conversations.json`：旧版本生成记录文件；当前界面不再写入新的记录
- `runtime/pycache`：Python 运行缓存，便于和项目代码分开

## 分发给同事

当前目录是 Windows 便携版，可以直接压缩整个文件夹分发。分发前建议先移除或清空：

- `data/config.json`，避免带上本机 API Key
- `data/prompt_history.json`，如果不想带上本机 Prompt 历史
- `data/conversations.json`，旧版本记录文件可不带
- `outputs/`，如果不需要历史生成结果
- `runtime/*.log`，运行日志可不带

## 常见问题

### 1. API Key 无效

- 确认 Key 是从 AI Studio 页面复制的完整字符串
- 确认项目未被禁用，且 Key 仍然有效

### 2. 配额耗尽或 429

- 检查 Google AI Studio / Cloud Billing 是否已启用计费
- 稍后重试，避免短时间内连续高频请求

### 3. 权限不足或 403

- 某些模型可能需要计费账户或权限已开通
- 可先切回快速模型验证 Key 本身是否可用

### 4. 请求超时

- 这版程序把单次网络请求超时固定为 5 分钟
- 建议先降低分辨率、减少参考图数量，或改用快速模型

### 5. AI Studio 网页能开，但本地测试连接失败

- 这通常不是 Key 错，而是本地 Python 进程没有走你的浏览器代理
- 如果你在国内网络环境，请在程序顶部“设置”里填写可用的代理地址
- 示例：`http://127.0.0.1:7890` 或 `socks5://127.0.0.1:7890`

## 参考资料

- [Gemini 图像生成官方文档](https://ai.google.dev/gemini-api/docs/image-generation)
- [Gemini 3 官方文档](https://ai.google.dev/gemini-api/docs/gemini-3)
- [Google Gen AI SDK 文档](https://googleapis.github.io/python-genai/)
