# 构建与打包说明

本仓库只收录**源码**，不含内置 Python 运行时（`python/`，约 281MB）和运行期数据（`data/`、`outputs/`、`runtime/`）。

## 本地运行

需要一份完整便携目录（含 `python/` 运行时）。恢复 `python/` 的方式：
- 从任意一份已安装的 GeminiImageTool（或 `GeminiImageTool_Setup_*.exe` 安装后）拷贝 `python/` 目录到本仓库根；或
- 用同版本的 Windows 便携版 Python，`pip install -r requirements.txt`（gradio / google-genai / Pillow）。

然后双击 `Start.bat` 启动，浏览器打开 http://127.0.0.1:7860 。

## 打包成安装程序 (Windows)

1. 装 [Inno Setup 6](https://jrsoftware.org/isdl.php)。
2. 准备一个**干净的完整便携目录**（含 `python/` + `app.py` + 支持文件，不含 `data/config.json`、`outputs/`、`__pycache__`、`unins000.*`、`*.bak`）。
3. 编辑 `packaging/GeminiImageTool.iss`，把 `StageDir` 指向该目录。
4. 编译：`ISCC.exe packaging\GeminiImageTool.iss` → 生成 `GeminiImageTool_Setup_v<版本>.exe`。

安装包特性：内置 Python 免装环境、免管理员（装到用户目录）、x64、`pythonw` 静默启动。

## 主要功能

- 文/图生图（Gemini 图像模型，支持官方 Key 与中转站）
- **动态模型检测**：填 Key 后点“检测可用模型”，自动拉取端点当前可用模型
- **图片编辑**页：局部重绘 / 放大 / 去背 / 水印
- 宽高比含 `4:5` 竖版与 `自适应`（由 Prompt 决定比例）
- 批量生图（输入暗门指令解锁）、Prompt 历史、按日期归档 + 自动备份
