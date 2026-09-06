# Gemini 图像工具 · Android

独立运行的安卓客户端，不需要启动 Mac / Windows 电脑，也不需要在手机安装 Python。

## 安装和使用

1. 下载 `GeminiImageTool-Android-1.0.0-beta1.apk`，在 Android 10 或更新版本安装。
2. 在「设置」选择接口协议，填写 API Key 和可选的 HTTPS Base URL，保存。
3. 点「检测可用模型 / 测试连接」。检测只读取模型列表，不发送收费生图请求。
4. 在「创作」输入提示词，可添加、排序最多 10 张参考图，再选择模型、比例、清晰度和张数。
5. 点「开始生成」。每张单独请求且不会自动重试；切到其他应用时，可从通知查看进度。
6. 在「作品」预览、保存到相册或分享原图。

该 APK 是测试用 debug 签名版本，尚未上架 Google Play。以后不同电脑生成的 debug 签名可能无法覆盖安装；卸载前请把作品保存到相册。

## 功能对照

| 功能 | 安卓版 |
| --- | --- |
| Gemini / Nano Banana | Gemini 原生 `generateContent`，支持文字和多张参考图 |
| OpenAI Images | `images/generations` 与 `images/edits`，兼容现有 APIYI GPT-Image-2-VIP 逻辑 |
| 参考图 | 系统图片选择器，多选、排序、移除；最多 10 张、总计 12MB |
| 连续生成 | 每批 1–10 张，逐张保存、显示进度、可停止 |
| 比例和清晰度 | 沿用桌面选项；非原生比例居中裁切，Pro 512 由 1K 缩小 |
| 搜索 | Gemini 可选网页搜索；Nano Banana 2 可选图片搜索 |
| 提示词历史 | 最近 100 条，本地去重保存 |
| 图片保存 | 应用内作品；手动存到 `Pictures/GeminiImageTool`，避免重复写入同一张 |
| API Key | 默认仅本次进程保存；可选 Android Keystore AES-GCM 加密保存 |

## 当前范围

- 网络使用手机系统及 VPN；未提供电脑端本机 HTTP / SOCKS 代理输入框。
- GRSAI 等专有异步接口、桌面版批量任务表、ZIP 导出和第二备份目录尚未移植。
- 应用内作品不会与电脑同步；卸载会清除应用内作品、参考图、设置和提示词历史，已保存到相册的图片保留。
- 超时或报错后不会自动重发，避免重复扣费；已提交的请求仍可能由服务商处理。
- 真机仍需补充验证各服务商、厂商后台管理和 Android 系统密钥库行为。

## 构建

依赖 JDK 17、Android SDK 35、Build Tools 35.0.0、Gradle 8.11.1、Android Gradle Plugin 8.9.2。

```bash
cd android
./gradlew testDebugUnitTest lintDebug assembleDebug
```

也可以在 GitHub Actions 运行 **Build Android APK**，下载名为 `GeminiImageTool-Android-beta` 的构建产物。
在手动运行工作流时填写发布标签，或推送 `v*` 标签，还会把 APK 添加到对应的 GitHub Release。
可安装文件输出为 `app/build/outputs/apk/debug/app-debug.apk`。
