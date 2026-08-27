import base64
import json
import mimetypes
import os
import random
import re
import shutil
import socket
import sys
import threading
import webbrowser
import zipfile
from datetime import datetime
from html import escape
from io import BytesIO
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

import gradio as gr
import httpx
from PIL import Image, ImageDraw, ImageFont
from google import genai
from google.genai import types


# 基础路径与运行配置。
SOURCE_DIR = Path(__file__).resolve().parent


def _dir_is_writable(path: Path) -> bool:
    """检测目录是否可写（macOS 拖进 /Applications 后为只读）。"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except Exception:
        return False


def resolve_base_dir() -> Path:
    """兼容源码、Windows EXE 和 macOS App 的工作目录。"""
    if not getattr(sys, "frozen", False):
        return SOURCE_DIR

    executable_path = Path(sys.executable).resolve()
    executable_posix = executable_path.as_posix()
    if sys.platform == "darwin" and ".app/Contents/MacOS/" in executable_posix:
        candidate = executable_path.parent.parent.parent.parent
    else:
        candidate = executable_path.parent

    # 安装目录只读（典型：macOS 把 .app 拖进 /Applications）时，回退到用户主目录下的可写目录。
    if _dir_is_writable(candidate):
        return candidate
    fallback = Path.home() / "GeminiImageTool"
    try:
        fallback.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return fallback


BASE_DIR = resolve_base_dir()
DATA_DIR = BASE_DIR / "data"
RUNTIME_DIR = BASE_DIR / "runtime"
PYTHON_CACHE_DIR = RUNTIME_DIR / "pycache"
CONFIG_PATH = DATA_DIR / "config.json"
CONVERSATIONS_PATH = DATA_DIR / "conversations.json"
PROMPT_HISTORY_PATH = DATA_DIR / "prompt_history.json"
LEGACY_CONFIG_PATH = BASE_DIR / "config.json"
LEGACY_CONVERSATIONS_PATH = BASE_DIR / "conversations.json"
DEFAULT_OUTPUT_ROOT = BASE_DIR / "outputs"
DEFAULT_BACKUP_ROOT = DEFAULT_OUTPUT_ROOT / "backups"
REQUEST_TIMEOUT_MS = 300_000
MAX_HISTORY = 20
MAX_PROMPT_HISTORY = 100
BATCH_GATE_COMMAND = "Daipihsy"
MAX_REFERENCE_IMAGES = 10
MAX_GENERATE_IMAGES = 10
INITIAL_BATCH_ROWS = 10
MAX_BATCH_ROWS = 30
MAX_BATCH_ROW_INPUT_SIZE = 10
MAX_BATCH_TOTAL_IMAGES = MAX_BATCH_ROWS * MAX_GENERATE_IMAGES
MAX_REFERENCE_BYTES = 20 * 1024 * 1024
TEST_MODEL_ID = "gemini-2.5-flash-lite"
DEFAULT_RELAY_BASE_URL = "https://api.apiyi.com"
GPT_IMAGE_2_VIP_MODEL_ID = "gpt-image-2-vip"
# “自适应”表示不向 API 传固定宽高比，交给 Prompt / 参考图决定画面比例。
AUTO_ASPECT_RATIO = "自适应"
ASPECT_RATIO_CHOICES = [AUTO_ASPECT_RATIO, "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9", "4:1", "1:4"]
RESOLUTION_CHOICES = ["512", "1K", "2K", "4K"]
GPT_IMAGE_2_VIP_SIZES = {
    "1K": {
        "1:1": "1280x1280",
        "2:3": "848x1280",
        "3:2": "1280x848",
        "3:4": "960x1280",
        "4:3": "1280x960",
        "4:5": "1024x1280",
        "5:4": "1280x1024",
        "9:16": "720x1280",
        "16:9": "1280x720",
        "21:9": "1280x544",
    },
    "2K": {
        "1:1": "2048x2048",
        "2:3": "1360x2048",
        "3:2": "2048x1360",
        "3:4": "1536x2048",
        "4:3": "2048x1536",
        "4:5": "1632x2048",
        "5:4": "2048x1632",
        "9:16": "1152x2048",
        "16:9": "2048x1152",
        "21:9": "2048x864",
    },
    "4K": {
        "1:1": "2880x2880",
        "2:3": "2336x3520",
        "3:2": "3520x2336",
        "3:4": "2480x3312",
        "4:3": "3312x2480",
        "4:5": "2560x3216",
        "5:4": "3216x2560",
        "9:16": "2160x3840",
        "16:9": "3840x2160",
        "21:9": "3840x1632",
    },
}
PAGE_SWITCH_SCROLL_JS = """
() => {
  const resetScroll = () => {
    const targets = [
      document.scrollingElement,
      document.documentElement,
      document.body,
      document.querySelector(".gradio-container"),
      document.querySelector("main")
    ].filter(Boolean);
    targets.forEach((target) => {
      try {
        target.scrollTo({ top: 0, left: 0, behavior: "auto" });
      } catch (_) {
        target.scrollTop = 0;
        target.scrollLeft = 0;
      }
    });
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  };
  requestAnimationFrame(resetScroll);
  setTimeout(resetScroll, 80);
  setTimeout(resetScroll, 240);
}
"""

# 当前官方文档中的图像模型。
MODEL_OPTIONS = [
    {
        "label": "Nano Banana 2（gemini-3.1-flash-image-preview）— 默认，速度快",
        "value": "gemini-3.1-flash-image-preview",
        "short_name": "Nano Banana 2",
        "native_sizes": {"512", "1K", "2K", "4K"},
        "native_aspects": {"1:1", "4:3", "3:4", "16:9", "9:16", "4:1", "1:4"},
        "supports_google_search": True,
        "supports_image_search": True,
    },
    {
        "label": "Nano Banana Pro（gemini-3-pro-image-preview）— 高保真",
        "value": "gemini-3-pro-image-preview",
        "short_name": "Nano Banana Pro",
        "native_sizes": {"1K", "2K", "4K"},
        "native_aspects": {"1:1", "4:3", "3:4", "16:9", "9:16"},
        "supports_google_search": True,
        "supports_image_search": False,
    },
    {
        "label": "GPT-Image-2-VIP（gpt-image-2-vip）— APIYI，支持锁定尺寸",
        "value": GPT_IMAGE_2_VIP_MODEL_ID,
        "short_name": "GPT-Image-2-VIP",
        "native_sizes": {"1K", "2K", "4K"},
        "native_aspects": set(GPT_IMAGE_2_VIP_SIZES["2K"].keys()),
        "supports_google_search": False,
        "supports_image_search": False,
        "api_kind": "apiyi_openai_image",
    },
]
MODEL_BY_ID = {item["value"]: item for item in MODEL_OPTIONS}
MODEL_LABELS = {item["value"]: item["label"] for item in MODEL_OPTIONS}

# 检测“可用模型”时，用来从全部模型里筛出图像模型的关键词（中转站命名基本都含这些词）。
IMAGE_MODEL_KEYWORDS = [
    "image", "imagen", "banana", "dall", "dalle", "flux", "seedream",
    "kontext", "qwen-image", "hunyuan-image", "grok-2-image", "ideogram",
    "recraft", "sdxl", "stable-diffusion", "sd3", "nano-banana",
]


def is_probably_image_model(model_id: str) -> bool:
    """按名称判断一个模型是否是图像生成模型。"""
    lower = (model_id or "").lower()
    if lower in {mid.lower() for mid in MODEL_BY_ID}:
        return True
    return any(keyword in lower for keyword in IMAGE_MODEL_KEYWORDS)


def get_model_meta(model_id: str) -> dict[str, Any]:
    """返回模型能力元数据。已知模型用内置配置；未知模型给保守但可用的默认值。

    中转站模型更新很快，用户“检测可用模型”后可能选到内置列表里没有的新模型。
    对未知模型：默认按 Gemini 原生图像协议处理，常见比例走原生、其余本地裁切，
    分辨率超出即本地缩放；拿不准时用户可选“自适应”比例，届时完全不传约束参数。
    """
    if model_id in MODEL_BY_ID:
        return MODEL_BY_ID[model_id]
    lower = (model_id or "").lower()
    looks_gemini = lower.startswith("gemini") or "imagen" in lower or "banana" in lower
    return {
        "label": model_id,
        "value": model_id,
        "short_name": model_id,
        "native_sizes": {"1K", "2K", "4K"},
        "native_aspects": {"1:1", "4:3", "3:4", "16:9", "9:16"},
        "supports_google_search": looks_gemini,
        "supports_image_search": False,
        "api_kind": "gemini",
    }


MODEL_FALLBACK_ASPECTS = {
    "gemini-3.1-flash-image-preview": {
        # 4:5 / 5:4 非原生：先按最接近的原生比例出图，再本地裁切，避免从 1:1 大幅裁切。
        "4:5": "3:4",
        "5:4": "4:3",
    },
    "gemini-3-pro-image-preview": {
        "4:1": "16:9",
        "1:4": "9:16",
        "4:5": "3:4",
        "5:4": "4:3",
    },
    GPT_IMAGE_2_VIP_MODEL_ID: {
        "4:1": "21:9",
        "1:4": "9:16",
        "4:5": "3:4",
        "5:4": "4:3",
    },
}
LONGEST_SIDE_BY_RESOLUTION = {
    "512": 512,
    "1K": 1024,
    "2K": 2048,
    "4K": 4096,
}
DEFAULT_PARAMS = {
    "model_id": MODEL_OPTIONS[0]["value"],
    "aspect_ratio": "1:1",
    "resolution": "1K",
    "image_count": 1,
    "keep_seed": False,
    "seed": None,
    "enable_google_search": False,
    "enable_image_search": False,
}
APP_CSS = """
:root {
    --app-bg: #fbf6ef;
    --app-bg-soft: rgba(255, 255, 255, 0.78);
    --card-bg: rgba(255, 252, 247, 0.92);
    --card-border: rgba(190, 167, 136, 0.26);
    --card-shadow: 0 22px 50px rgba(87, 62, 35, 0.08);
    --text-main: #1f2430;
    --text-soft: #596171;
    --accent: #ff7a18;
    --accent-deep: #ed5d2a;
    --accent-soft: rgba(255, 122, 24, 0.12);
}
.gradio-container {
    background:
        radial-gradient(circle at top left, rgba(255, 183, 105, 0.22), transparent 30%),
        radial-gradient(circle at top right, rgba(255, 122, 24, 0.12), transparent 22%),
        linear-gradient(180deg, #fffdf9 0%, var(--app-bg) 100%);
    color: var(--text-main);
    font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
}
.app-shell {
    max-width: 1460px;
    margin: 0 auto;
    padding-bottom: 28px;
}
.workspace-shell {
    align-items: flex-start;
    gap: 18px;
}
.page-switcher {
    margin-bottom: 16px;
    border: 1px solid rgba(210, 185, 154, 0.34);
    border-radius: 22px;
    background: rgba(255, 252, 247, 0.78);
    box-shadow: var(--card-shadow);
}
.surface-card {
    border: 1px solid var(--card-border);
    border-radius: 24px;
    background: var(--card-bg);
    box-shadow: var(--card-shadow);
}
.settings-wrap {
    position: sticky;
    top: 14px;
    z-index: 20;
    margin-bottom: 18px;
    overflow: hidden;
    border: 1px solid rgba(222, 196, 166, 0.5);
    border-radius: 26px;
    background: linear-gradient(180deg, rgba(255, 250, 244, 0.97), rgba(250, 245, 236, 0.95));
    box-shadow: 0 22px 60px rgba(82, 55, 20, 0.08);
    backdrop-filter: blur(16px);
}
.settings-wrap .label-wrap {
    padding-top: 8px;
}
.main-panel {
    gap: 14px;
}
.side-panel {
    border: 1px solid rgba(201, 178, 148, 0.28);
    border-radius: 24px;
    background: rgba(255, 252, 247, 0.9);
    box-shadow: var(--card-shadow);
}
.sidebar-shell {
    position: sticky;
    top: 108px;
    align-self: flex-start;
}
.hero-card {
    margin-bottom: 10px;
    padding: 18px 22px;
    border: 1px solid rgba(255, 132, 33, 0.15);
    border-radius: 24px;
    background:
        linear-gradient(135deg, rgba(255, 122, 24, 0.12), rgba(255, 255, 255, 0.92)),
        var(--card-bg);
    box-shadow: var(--card-shadow);
}
.hero-card h3,
.hero-card h2,
.hero-card p {
    margin: 0;
}
.folder-links {
    margin: -2px 0 12px;
    color: var(--text-soft);
    font-size: 0.94rem;
}
.folder-links a {
    color: var(--accent-deep);
    font-weight: 600;
}
.composer-card,
.results-card {
    padding-top: 8px;
}
.sub-accordion {
    overflow: hidden;
    border: 1px solid rgba(210, 185, 154, 0.32);
    border-radius: 18px;
    background: rgba(255, 255, 255, 0.62);
}
.muted-note {
    color: var(--text-soft);
    font-size: 0.95rem;
    line-height: 1.65;
}
.prompt-box textarea {
    font-size: 0.98rem !important;
    line-height: 1.7 !important;
}
.prompt-box textarea {
    min-height: 188px !important;
}
.prompt-copy-card {
    position: relative;
    min-width: min(520px, 100%);
    min-height: 96px;
    padding: 34px 118px 34px 0;
}
.prompt-copy-text {
    white-space: pre-wrap;
    word-break: break-word;
    line-height: 1.7;
}
.prompt-copy-top,
.prompt-copy-bottom {
    position: absolute;
    right: 0;
}
.prompt-copy-top {
    top: 0;
}
.prompt-copy-bottom {
    bottom: 0;
}
.prompt-copy-button {
    border: 1px solid rgba(255, 255, 255, 0.5);
    border-radius: 999px;
    padding: 6px 12px;
    background: rgba(255, 255, 255, 0.86);
    color: var(--accent-deep);
    font-size: 12px;
    font-weight: 700;
    cursor: pointer;
    box-shadow: 0 8px 18px rgba(92, 64, 22, 0.08);
}
.prompt-copy-button:hover {
    background: #fff;
}
.status-box {
    margin-top: 14px;
    border-radius: 24px;
    padding: 18px 20px;
    background:
        linear-gradient(180deg, rgba(255, 250, 244, 0.96), rgba(255, 244, 231, 0.92));
    border: 1px solid rgba(255, 133, 39, 0.18);
    box-shadow: 0 18px 40px rgba(92, 64, 22, 0.06);
}
.generate-button button {
    min-height: 56px;
    border: none !important;
    background: linear-gradient(135deg, var(--accent), var(--accent-deep)) !important;
    color: #fff !important;
    font-size: 1.06rem !important;
    font-weight: 700 !important;
    box-shadow: 0 18px 34px rgba(237, 93, 42, 0.24);
}
.generate-button button:hover {
    filter: brightness(1.02);
    transform: translateY(-1px);
}
.cancel-button button {
    min-height: 56px;
    border: 2px solid #e05a3a !important;
    color: #e05a3a !important;
    background: transparent !important;
    font-size: 1rem !important;
    font-weight: 700 !important;
    border-radius: 10px !important;
}
.cancel-button button:hover {
    background: rgba(224, 90, 58, 0.07) !important;
}
.side-panel button {
    font-weight: 600;
}
.batch-page {
    gap: 16px;
}
.batch-page .dataframe {
    border-radius: 18px;
    overflow: hidden;
}
.batch-toolbar {
    gap: 14px;
}
.batch-default-card {
    padding: 14px 16px;
}
.batch-action-row {
    gap: 10px;
}
.batch-table-card {
    padding: 12px;
}
.batch-task-row {
    align-items: stretch;
    gap: 12px;
    margin-bottom: 12px;
    padding: 14px;
    border: 1px solid rgba(210, 185, 154, 0.36);
    border-radius: 22px;
    background:
        linear-gradient(135deg, rgba(255, 255, 255, 0.86), rgba(255, 247, 238, 0.72));
}
.batch-task-row textarea {
    min-height: 112px !important;
}
.batch-param-card {
    min-height: 100%;
}
.batch-sticky-actions {
    position: sticky;
    top: 112px;
    z-index: 12;
}
.gradio-container textarea,
.gradio-container input,
.gradio-container .wrap {
    border-radius: 16px !important;
}
.results-card .grid-wrap,
.composer-card .grid-wrap {
    border-radius: 18px;
}
.sidebar-shell .accordion {
    background: transparent;
}
@media (max-width: 960px) {
    .settings-wrap,
    .sidebar-shell {
        position: static;
        top: auto;
    }
    .workspace-shell {
        gap: 14px;
    }
}
@media (max-width: 640px) {
    .app-shell {
        padding-bottom: 16px;
    }
    .hero-card,
    .status-box {
        padding: 16px;
    }
    .prompt-box textarea {
        min-height: 168px !important;
    }
}
"""


def ensure_base_dirs() -> None:
    """确保默认输出与备份目录存在。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    PYTHON_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    DEFAULT_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    DEFAULT_BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    migrate_legacy_data_files()


def migrate_legacy_json_file(legacy_path: Path, target_path: Path) -> None:
    """兼容旧版本，把根目录的数据文件迁移到 data 目录。"""
    if target_path.exists() or not legacy_path.exists():
        return

    target_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(legacy_path), str(target_path))
        return
    except OSError:
        pass

    try:
        shutil.copy2(str(legacy_path), str(target_path))
        legacy_path.unlink()
    except OSError:
        return


def migrate_legacy_data_files() -> None:
    """启动时自动迁移旧的配置与会话文件。"""
    migrate_legacy_json_file(LEGACY_CONFIG_PATH, CONFIG_PATH)
    migrate_legacy_json_file(LEGACY_CONVERSATIONS_PATH, CONVERSATIONS_PATH)


def read_json_file(path: Path, default: Any) -> Any:
    """读取 JSON 文件，损坏时回退默认值。"""
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (json.JSONDecodeError, OSError):
        return default


def write_json_file(path: Path, data: Any) -> None:
    """原子写入 JSON，避免写到一半损坏。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    temp_path.replace(path)


def normalize_api_key(api_key: str) -> str:
    """统一处理 API Key 输入。"""
    return (api_key or "").strip()


def normalize_proxy_url(proxy_url: str) -> str:
    """统一处理代理地址输入。"""
    return (proxy_url or "").strip()


def normalize_api_base_url(api_base_url: str) -> str:
    """统一处理 Gemini Base URL，留空表示走 Google 官方端点。"""
    raw = (api_base_url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"https://{raw}"
    return raw.rstrip("/")


def detect_windows_system_proxy_url() -> str:
    """读取 Windows 当前用户代理设置，尽量自动补全本机代理。"""
    if os.name != "nt":
        return ""

    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        ) as key:
            proxy_enable = int(winreg.QueryValueEx(key, "ProxyEnable")[0])
            if not proxy_enable:
                return ""
            proxy_server = str(winreg.QueryValueEx(key, "ProxyServer")[0]).strip()
    except Exception:
        return ""

    if not proxy_server:
        return ""

    candidate = proxy_server.split(";", 1)[0]
    if "=" in candidate:
        parts = [part.split("=", 1)[1] for part in proxy_server.split(";") if "=" in part]
        candidate = parts[0] if parts else candidate

    candidate = candidate.strip()
    if not candidate:
        return ""

    if "://" not in candidate:
        candidate = f"http://{candidate}"
    return candidate


def normalize_output_root(output_root: str) -> Path:
    """把输出目录统一转换成绝对路径。"""
    raw = (output_root or "").strip()
    if not raw:
        return DEFAULT_OUTPUT_ROOT
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (BASE_DIR / path).resolve()
    return path


def normalize_backup_root(backup_root: str) -> Path:
    """把备份目录统一转换成绝对路径。"""
    raw = (backup_root or "").strip()
    if not raw:
        return DEFAULT_BACKUP_ROOT
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (BASE_DIR / path).resolve()
    return path


def ensure_storage_roots(output_root: str, backup_root: str) -> tuple[Path, Path]:
    """确保主输出根目录与备份根目录存在。"""
    output_path = normalize_output_root(output_root)
    backup_path = normalize_backup_root(backup_root)
    output_path.mkdir(parents=True, exist_ok=True)
    backup_path.mkdir(parents=True, exist_ok=True)
    return output_path, backup_path


def load_config() -> dict[str, Any]:
    """读取本地配置。"""
    data = read_json_file(CONFIG_PATH, {})
    if not isinstance(data, dict):
        return {}
    return data


def save_runtime_settings(
    api_key: str,
    proxy_url: str,
    api_base_url: str,
    output_root: str,
    backup_root: str,
    remember_api_key: bool,
) -> None:
    """保存 API Key、代理、Base URL、输出目录和备份目录。"""
    write_json_file(
        CONFIG_PATH,
        {
            "api_key": normalize_api_key(api_key) if remember_api_key else "",
            "proxy_url": normalize_proxy_url(proxy_url),
            "api_base_url": normalize_api_base_url(api_base_url),
            "output_root": str(normalize_output_root(output_root)),
            "backup_root": str(normalize_backup_root(backup_root)),
        },
    )


def normalize_prompt_history_params(params: dict[str, Any] | None) -> dict[str, Any]:
    """只保留复用 Prompt 时有价值、且不敏感的基础参数。"""
    if not isinstance(params, dict):
        return {}

    normalized: dict[str, Any] = {}
    text_keys = ("model_id", "aspect_ratio", "resolution")
    for key in text_keys:
        value = str(params.get(key, "")).strip()
        if value:
            normalized[key] = value

    if params.get("image_count") not in (None, ""):
        try:
            normalized["image_count"] = int(params["image_count"])
        except (TypeError, ValueError):
            pass

    if params.get("seed") not in (None, ""):
        try:
            normalized["seed"] = int(params["seed"])
        except (TypeError, ValueError):
            pass

    for key in ("keep_seed", "enable_google_search", "enable_image_search"):
        if key in params:
            normalized[key] = bool(params.get(key))

    return normalized


def normalize_prompt_history_entry(item: Any) -> dict[str, Any] | None:
    """兼容字符串或字典格式的 Prompt 历史条目。"""
    if isinstance(item, str):
        prompt = item.strip()
        if not prompt:
            return None
        return {
            "id": uuid4().hex,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "prompt": prompt,
            "params": {},
        }

    if not isinstance(item, dict):
        return None

    prompt = str(item.get("prompt", "")).strip()
    if not prompt:
        return None

    created_at = str(item.get("created_at") or item.get("updated_at") or "").strip()
    if not created_at:
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return {
        "id": str(item.get("id") or uuid4().hex),
        "created_at": created_at,
        "prompt": prompt,
        "params": normalize_prompt_history_params(item.get("params")),
    }


def load_prompt_history() -> list[dict[str, Any]]:
    """读取独立的 Prompt 历史，不恢复会话记录。"""
    data = read_json_file(PROMPT_HISTORY_PATH, [])
    if not isinstance(data, list):
        return []

    history: list[dict[str, Any]] = []
    for item in data:
        entry = normalize_prompt_history_entry(item)
        if entry:
            history.append(entry)
        if len(history) >= MAX_PROMPT_HISTORY:
            break
    return history


def save_prompt_history(history: list[dict[str, Any]]) -> None:
    """保存独立 Prompt 历史。"""
    cleaned: list[dict[str, Any]] = []
    for item in history:
        entry = normalize_prompt_history_entry(item)
        if entry:
            cleaned.append(entry)
        if len(cleaned) >= MAX_PROMPT_HISTORY:
            break
    write_json_file(PROMPT_HISTORY_PATH, cleaned)


def add_prompt_history_entry(prompt: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """每次成功生成后记录 Prompt，供后续挑选复用。"""
    clean_prompt = (prompt or "").strip()
    if not clean_prompt:
        return load_prompt_history()

    entry = {
        "id": uuid4().hex,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "prompt": clean_prompt,
        "params": normalize_prompt_history_params(params),
    }
    history = [entry, *load_prompt_history()][:MAX_PROMPT_HISTORY]
    try:
        save_prompt_history(history)
    except OSError:
        pass
    return history


def compact_prompt_history_label(prompt: str, max_chars: int = 64) -> str:
    """压缩 Prompt 下拉展示文本。"""
    compacted = re.sub(r"\s+", " ", (prompt or "").strip())
    if len(compacted) <= max_chars:
        return compacted
    return f"{compacted[: max_chars - 3]}..."


def format_prompt_history_time(value: str) -> str:
    """把完整时间压缩成适合下拉框的显示。"""
    raw = (value or "").strip()
    if not raw:
        return "未知时间"
    try:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").strftime("%m-%d %H:%M")
    except ValueError:
        return raw[:16]


def build_prompt_history_choices(
    history: list[dict[str, Any]] | None = None,
) -> list[tuple[str, str]]:
    """把 Prompt 历史转换成 Gradio 下拉选项。"""
    choices: list[tuple[str, str]] = []
    for item in history if history is not None else load_prompt_history():
        prompt = str(item.get("prompt", "")).strip()
        if not prompt:
            continue

        params = item.get("params") if isinstance(item.get("params"), dict) else {}
        meta_parts: list[str] = []
        model_id = str(params.get("model_id", "")).strip()
        if model_id:
            meta_parts.append(get_model_meta(model_id).get("short_name", model_id))
        aspect_ratio = str(params.get("aspect_ratio", "")).strip()
        resolution = str(params.get("resolution", "")).strip()
        if aspect_ratio or resolution:
            meta_parts.append("/".join(part for part in (aspect_ratio, resolution) if part))
        if params.get("image_count"):
            meta_parts.append(f"{params['image_count']}张")

        time_label = format_prompt_history_time(str(item.get("created_at", "")))
        prompt_label = compact_prompt_history_label(prompt)
        meta_label = f" | {' · '.join(meta_parts)}" if meta_parts else ""
        choices.append((f"{time_label} | {prompt_label}{meta_label}", prompt))
    return choices


def get_initial_api_key() -> str:
    """程序启动时预填 API Key。"""
    return str(load_config().get("api_key", "")).strip()


def get_initial_remember_api_key() -> bool:
    """启动时是否默认记住 API Key。"""
    return bool(get_initial_api_key())


def get_initial_proxy_url() -> str:
    """程序启动时预填代理。"""
    stored = str(load_config().get("proxy_url", "")).strip()
    if stored:
        return stored
    return detect_windows_system_proxy_url()


def get_initial_api_base_url() -> str:
    """程序启动时预填 Base URL，留空表示仍走 Google 官方端点。"""
    return normalize_api_base_url(str(load_config().get("api_base_url", "")).strip())


def get_initial_output_root() -> str:
    """程序启动时预填输出目录。"""
    stored = str(load_config().get("output_root", "")).strip()
    if stored:
        return str(normalize_output_root(stored))
    return str(DEFAULT_OUTPUT_ROOT)


def get_initial_backup_root() -> str:
    """程序启动时预填备份目录。"""
    stored = str(load_config().get("backup_root", "")).strip()
    if stored:
        return str(normalize_backup_root(stored))
    return str(DEFAULT_BACKUP_ROOT)


def build_allowed_launch_paths() -> list[str]:
    """构建 Gradio 可访问的本地目录白名单。"""
    config = load_config()
    candidates = [
        DEFAULT_OUTPUT_ROOT,
        DEFAULT_BACKUP_ROOT,
        normalize_output_root(str(config.get("output_root", "")).strip()),
        normalize_backup_root(str(config.get("backup_root", "")).strip()),
    ]
    seen: set[str] = set()
    allowed_paths: list[str] = []
    for candidate in candidates:
        try:
            normalized = str(candidate.resolve())
        except Exception:
            normalized = str(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        allowed_paths.append(normalized)
    return allowed_paths


def get_path_picker_root() -> str:
    """路径选择器默认浏览根目录。"""
    anchor = BASE_DIR.anchor or str(BASE_DIR)
    return anchor


def resolve_existing_directory(candidate: str, fallback: Path) -> Path:
    """解析当前输入框中的目录，用于原生文件夹选择框的初始位置。"""
    raw = (candidate or "").strip()
    if raw:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = (BASE_DIR / path).resolve()
        if path.exists():
            return path if path.is_dir() else path.parent
    return fallback


def safe_slug(text: str) -> str:
    """把会话标题转换成安全文件夹名。"""
    cleaned = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", (text or "").strip(), flags=re.UNICODE)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return cleaned[:40] or "conversation"


def build_conversation_slug(
    conversation_id: str,
    title: str,
    created_at: str | None = None,
) -> str:
    """根据会话 ID、标题与创建时间生成稳定的文件夹名。"""
    date_prefix = datetime.now().strftime("%Y%m%d")
    if created_at:
        try:
            date_prefix = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S").strftime("%Y%m%d")
        except ValueError:
            pass
    return f"{date_prefix}_{safe_slug(title)}_{conversation_id[:6]}"


def derive_conversation_title(prompt: str) -> str:
    """从首轮 prompt 自动生成会话标题。"""
    compact = re.sub(r"\s+", " ", (prompt or "").strip())
    if not compact:
        return "临时任务"
    title = compact[:24]
    return title + ("..." if len(compact) > 24 else "")


def create_conversation(title: str | None = None) -> dict[str, Any]:
    """创建新的会话对象。"""
    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conv_id = uuid4().hex
    final_title = title or f"临时任务 {datetime.now().strftime('%H:%M:%S')}"
    return {
        "id": conv_id,
        "title": final_title,
        "slug": build_conversation_slug(conv_id, final_title, now_text),
        "created_at": now_text,
        "updated_at": now_text,
        "turns": [],
        "last_params": dict(DEFAULT_PARAMS),
    }


def load_conversations() -> list[dict[str, Any]]:
    """读取会话列表。"""
    data = read_json_file(CONVERSATIONS_PATH, [])
    if not isinstance(data, list):
        return []
    conversations = [item for item in data if isinstance(item, dict)]
    for item in conversations:
        item.pop("memory", None)
    return conversations


def save_conversations(conversations: list[dict[str, Any]]) -> None:
    """不再持久化会话记录；保留函数以兼容现有回调结构。"""
    return


def ensure_initial_conversations() -> tuple[list[dict[str, Any]], str]:
    """启动时只创建一个临时任务状态，不再读取历史会话。"""
    first = create_conversation()
    return [first], first["id"]


def find_conversation(conversations: list[dict[str, Any]], conversation_id: str | None) -> dict[str, Any] | None:
    """按 ID 查找会话。"""
    if not conversation_id:
        return None
    return next((item for item in conversations if item.get("id") == conversation_id), None)


def build_conversation_choices(conversations: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """把会话列表转换成侧边栏选项。"""
    choices: list[tuple[str, str]] = []
    ordered = get_ordered_conversations(conversations)
    for item in ordered:
        title = item.get("title") or "未命名会话"
        updated = item.get("updated_at", "")[5:16] if item.get("updated_at") else "未知时间"
        turns_count = len(item.get("turns") or [])
        choices.append((f"{updated} | {title} | {turns_count} 轮", item.get("id", "")))
    return choices


def get_ordered_conversations(conversations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """返回按更新时间倒序排列的最近会话。"""
    return sorted(
        conversations,
        key=lambda item: item.get("updated_at", ""),
        reverse=True,
    )[:MAX_HISTORY]


def build_conversation_row_label(conversation: dict[str, Any]) -> str:
    """构造侧边栏每一行会话文案。"""
    title = conversation.get("title") or "未命名会话"
    updated = conversation.get("updated_at", "")[5:16] if conversation.get("updated_at") else "未知时间"
    turns_count = len(conversation.get("turns") or [])
    return f"{updated} | {title} | {turns_count} 轮"


def build_conversation_sidebar_updates(
    conversations: list[dict[str, Any]],
    current_conversation_id: str | None,
    pending_delete_id: str | None = None,
) -> tuple[list[str], tuple[Any, ...]]:
    """构造左侧最近会话区域的逐行更新。"""
    ordered = get_ordered_conversations(conversations)
    row_ids: list[str] = []
    updates: list[Any] = []

    for index in range(MAX_HISTORY):
        if index < len(ordered):
            conversation = ordered[index]
            conversation_id = conversation.get("id", "")
            row_ids.append(conversation_id)
            is_active = conversation_id == current_conversation_id
            is_pending = conversation_id == pending_delete_id
            updates.extend(
                [
                    gr.update(visible=True),
                    gr.update(
                        value=build_conversation_row_label(conversation),
                        visible=True,
                        variant="primary" if is_active else "secondary",
                    ),
                    gr.update(value="🗑", visible=not is_pending),
                    gr.update(value="确认删除？", visible=is_pending),
                    gr.update(value="删除", visible=is_pending),
                    gr.update(value="取消", visible=is_pending),
                ]
            )
        else:
            row_ids.append("")
            updates.extend(
                [
                    gr.update(visible=False),
                    gr.update(value="", visible=False),
                    gr.update(value="🗑", visible=False),
                    gr.update(value="确认删除？", visible=False),
                    gr.update(value="删除", visible=False),
                    gr.update(value="取消", visible=False),
                ]
            )

    return row_ids, tuple(updates)


def build_compact_conversation_sidebar_updates(
    conversations: list[dict[str, Any]],
    current_conversation_id: str | None,
    pending_delete_id: str | None = None,
) -> tuple[list[str], tuple[Any, ...]]:
    """构造更紧凑的最近会话更新，避免删除确认长期占位。"""
    ordered = get_ordered_conversations(conversations)
    row_ids: list[str] = []
    updates: list[Any] = []

    for index in range(MAX_HISTORY):
        if index < len(ordered):
            conversation = ordered[index]
            conversation_id = conversation.get("id", "")
            row_ids.append(conversation_id)
            is_active = conversation_id == current_conversation_id
            is_pending = conversation_id == pending_delete_id
            updates.extend(
                [
                    gr.update(visible=True),
                    gr.update(
                        value=build_conversation_row_label(conversation),
                        variant="primary" if is_active else "secondary",
                    ),
                    gr.update(visible=not is_pending),
                    gr.update(visible=is_pending),
                ]
            )
        else:
            row_ids.append("")
            updates.extend(
                [
                    gr.update(visible=False),
                    gr.update(value="", variant="secondary"),
                    gr.update(visible=False),
                    gr.update(visible=False),
                ]
            )

    return row_ids, tuple(updates)


def get_last_turn(conversation: dict[str, Any] | None) -> dict[str, Any] | None:
    """获取会话最后一轮。"""
    if not conversation:
        return None
    turns = conversation.get("turns") or []
    if not turns:
        return None
    return turns[-1]


def update_conversation_title_if_needed(conversation: dict[str, Any], prompt: str) -> None:
    """首轮成功生成后，自动把会话标题改成更可识别的名字。"""
    turns = conversation.get("turns") or []
    title = conversation.get("title") or ""
    if turns or (title and not title.startswith("临时任务")):
        return
    new_title = derive_conversation_title(prompt)
    conversation["title"] = new_title
    conversation["slug"] = build_conversation_slug(
        conversation["id"],
        new_title,
        conversation.get("created_at"),
    )


def build_effective_prompt(prompt: str, needs_ratio_postprocess: bool, aspect_ratio: str) -> str:
    """构造实际发送给 Gemini 的 prompt。"""
    clean_prompt = (prompt or "").strip()
    final_prompt = clean_prompt

    if not needs_ratio_postprocess:
        return final_prompt

    if aspect_ratio == "4:1":
        suffix = "请尽量按超宽横幅 4:1 构图，主体横向展开，避免重要内容贴近上下边缘。"
    elif aspect_ratio == "1:4":
        suffix = "请尽量按超高竖幅 1:4 构图，主体纵向展开，避免重要内容贴近左右边缘。"
    else:
        suffix = ""

    if not suffix:
        return final_prompt
    return f"{final_prompt}\n\n{suffix}"


def output_day_dir(root: Path, create: bool = True) -> Path:
    """按日期拆分当天输出。"""
    day_dir = root / datetime.now().strftime("%Y-%m-%d")
    if create:
        day_dir.mkdir(parents=True, exist_ok=True)
    return day_dir


def build_api_hint_text(api_key: str, remember_api_key: bool) -> str:
    """顶部 API Key 提示。"""
    if normalize_api_key(api_key):
        if remember_api_key:
            return "API Key 已就绪，点击“保存设置”后会写入本地 `data/config.json`，下次打开可直接使用。"
        return "API Key 已就绪，但当前设为仅本次运行使用；保存设置时不会把 Key 写入本地。"
    return "请先在上方设置 API Key。未填写时，生成按钮会保持禁用。"


def get_generate_button_update(api_key: str) -> gr.Button:
    """根据 API Key 切换生成按钮状态。"""
    return gr.update(interactive=bool(normalize_api_key(api_key)))


def get_creative_generate_button_update(api_key: str, prompt: str | None = None) -> gr.Button:
    """创作按钮：有 API Key 或输入暗门指令时可点击。"""
    return gr.update(interactive=bool(normalize_api_key(api_key)) or is_batch_gate_prompt(prompt))


def build_http_options_kwargs(proxy_url: str = "", api_base_url: str = "") -> dict[str, Any]:
    """统一构造 HTTP 配置，兼容官方端点和 Gemini 原生中转。"""
    clean_proxy = normalize_proxy_url(proxy_url) or detect_windows_system_proxy_url()
    clean_base_url = normalize_api_base_url(api_base_url)
    http_options_kwargs: dict[str, Any] = {"timeout": REQUEST_TIMEOUT_MS}
    if clean_proxy:
        http_options_kwargs["client_args"] = {"proxy": clean_proxy}
        http_options_kwargs["async_client_args"] = {"proxy": clean_proxy}
    if clean_base_url:
        http_options_kwargs["base_url"] = clean_base_url
        http_options_kwargs["api_version"] = "v1beta"
    return http_options_kwargs


def make_client(api_key: str, proxy_url: str = "", api_base_url: str = "") -> genai.Client:
    """创建带 5 分钟超时的 Gemini 客户端。"""
    key = normalize_api_key(api_key)
    if not key:
        raise ValueError("请先填写 API Key。")

    return genai.Client(
        api_key=key,
        http_options=types.HttpOptions(**build_http_options_kwargs(proxy_url, api_base_url)),
    )


def make_request_http_options(api_base_url: str = "") -> types.HttpOptions:
    """单次请求统一超时配置。"""
    clean_base_url = normalize_api_base_url(api_base_url)
    http_options_kwargs: dict[str, Any] = {"timeout": REQUEST_TIMEOUT_MS}
    if clean_base_url:
        http_options_kwargs["base_url"] = clean_base_url
        http_options_kwargs["api_version"] = "v1beta"
    return types.HttpOptions(**http_options_kwargs)


def is_apiyi_openai_image_model(model_id: str) -> bool:
    """是否为 APIYI OpenAI Images 兼容图像模型。"""
    return get_model_meta(model_id).get("api_kind") == "apiyi_openai_image"


def build_apiyi_openai_url(api_base_url: str, endpoint_path: str) -> str:
    """构造 APIYI OpenAI 兼容接口地址，留空时默认走 api.apiyi.com。"""
    base_url = normalize_api_base_url(api_base_url) or DEFAULT_RELAY_BASE_URL
    if not base_url.rstrip("/").endswith("/v1"):
        base_url = f"{base_url.rstrip('/')}/v1"
    return f"{base_url.rstrip('/')}/{endpoint_path.lstrip('/')}"


def make_httpx_client(proxy_url: str = "") -> httpx.Client:
    """创建普通 HTTP 客户端，用于 OpenAI Images 兼容接口。"""
    clean_proxy = normalize_proxy_url(proxy_url) or detect_windows_system_proxy_url()
    kwargs: dict[str, Any] = {
        "timeout": REQUEST_TIMEOUT_MS / 1000,
        "follow_redirects": True,
    }
    if clean_proxy:
        kwargs["proxy"] = clean_proxy
        kwargs["trust_env"] = False
    return httpx.Client(**kwargs)


def resolve_apiyi_openai_image_size(
    model_id: str,
    resolution: str,
    api_aspect_ratio: str | None,
) -> str:
    """把界面里的比例/档位转换为 GPT-Image-2-VIP 的 size。"""
    if model_id != GPT_IMAGE_2_VIP_MODEL_ID or not api_aspect_ratio:
        return "auto"
    return GPT_IMAGE_2_VIP_SIZES.get(resolution, {}).get(api_aspect_ratio, "auto")


def extract_error_detail(payload: Any) -> str:
    """从 OpenAI 兼容错误响应里提取可读信息。"""
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            return str(
                error.get("message")
                or error.get("code")
                or error.get("type")
                or error
            )
        if error:
            return str(error)
        for key in ("message", "detail", "msg"):
            if payload.get(key):
                return str(payload[key])
    return str(payload or "")


def parse_json_response(response: httpx.Response) -> dict[str, Any]:
    """解析 HTTP 响应，并把接口错误转为异常。"""
    try:
        payload = response.json()
    except ValueError:
        payload = {"message": response.text}

    if response.status_code >= 400:
        detail = extract_error_detail(payload)
        raise RuntimeError(f"APIYI HTTP {response.status_code}: {detail or response.text}")
    if not isinstance(payload, dict):
        raise RuntimeError(f"APIYI 返回格式异常：{payload}")
    return payload


def image_from_data_url(data_url: str) -> Image.Image:
    """从 data URL 或裸 base64 字符串读取图片。"""
    payload = (data_url or "").strip()
    if "," in payload and payload.lower().startswith("data:"):
        payload = payload.split(",", 1)[1]
    if not payload:
        raise RuntimeError("APIYI 返回了空的 b64_json 图片数据。")
    image_bytes = base64.b64decode(payload)
    return Image.open(BytesIO(image_bytes)).convert("RGB")


def extract_apiyi_openai_image(payload: dict[str, Any], client: httpx.Client) -> Image.Image:
    """解析 APIYI OpenAI Images 兼容接口返回的图片。"""
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise RuntimeError(f"APIYI 没有返回图片数据：{payload}")

    first = data[0]
    if not isinstance(first, dict):
        raise RuntimeError(f"APIYI 图片数据格式异常：{first}")

    if first.get("b64_json"):
        return image_from_data_url(str(first["b64_json"]))

    image_url = str(first.get("url") or "").strip()
    if image_url:
        response = client.get(image_url)
        response.raise_for_status()
        return Image.open(BytesIO(response.content)).convert("RGB")

    raise RuntimeError(f"APIYI 返回结果里没有 url 或 b64_json：{first}")


def generate_apiyi_openai_image(
    api_key: str,
    proxy_url: str,
    api_base_url: str,
    model_id: str,
    prompt: str,
    reference_paths: list[str] | None,
    resolution: str,
    api_aspect_ratio: str | None,
) -> Image.Image:
    """调用 APIYI 的 OpenAI Images/Edits 兼容端点生成图片。"""
    image_size = resolve_apiyi_openai_image_size(model_id, resolution, api_aspect_ratio)
    headers = {"Authorization": f"Bearer {normalize_api_key(api_key)}"}

    with make_httpx_client(proxy_url) as client:
        if reference_paths:
            files = [
                (
                    "image",
                    (Path(path).name, Path(path).read_bytes(), guess_mime_type(Path(path))),
                )
                for path in reference_paths
            ]
            data = {
                "model": model_id,
                "prompt": prompt,
                "size": image_size,
                "response_format": "b64_json",
            }
            response = client.post(
                build_apiyi_openai_url(api_base_url, "/images/edits"),
                headers=headers,
                data=data,
                files=files,
            )
        else:
            response = client.post(
                build_apiyi_openai_url(api_base_url, "/images/generations"),
                headers={**headers, "Content-Type": "application/json"},
                json={
                    "model": model_id,
                    "prompt": prompt,
                    "size": image_size,
                    "response_format": "b64_json",
                },
            )

        return extract_apiyi_openai_image(parse_json_response(response), client)


def model_supports_google_search(model_id: str) -> bool:
    """模型是否支持 Google Search grounding。"""
    return bool(get_model_meta(model_id).get("supports_google_search"))


def model_supports_image_search(model_id: str) -> bool:
    """模型是否支持 Image Search grounding。"""
    return bool(get_model_meta(model_id).get("supports_image_search"))


def build_grounding_hint(model_id: str, enable_google_search: bool) -> str:
    """根据当前模型给出 grounding 提示。"""
    if not enable_google_search:
        return "可选：启用后，模型会先调用 Google Search，再基于检索结果辅助生成图像。"
    if model_supports_image_search(model_id):
        return "当前模型支持 Google Search 和 Image Search；适合补足真实品牌、服装、商品外观等视觉细节。"
    if model_supports_google_search(model_id):
        return "当前模型支持 Google Search，但不支持 Image Search；如需图片搜索，请切换到 Nano Banana 2。"
    return "当前模型不支持 Google Search grounding。"


def refresh_grounding_controls(
    model_id: str,
    enable_google_search: bool,
    enable_image_search: bool,
) -> tuple[gr.Checkbox, str]:
    """根据模型刷新 Image Search 选项。"""
    if not enable_google_search:
        return (
            gr.update(value=False, interactive=False),
            build_grounding_hint(model_id, enable_google_search),
        )

    if model_supports_image_search(model_id):
        return (
            gr.update(value=bool(enable_image_search), interactive=True),
            build_grounding_hint(model_id, enable_google_search),
        )

    return (
        gr.update(value=False, interactive=False),
        build_grounding_hint(model_id, enable_google_search),
    )


def build_grounding_tool(
    model_id: str,
    enable_google_search: bool,
    enable_image_search: bool,
) -> tuple[list[types.Tool], bool, list[str]]:
    """把两个开关转换成 Gemini API 的 tools 配置。"""
    if not enable_google_search:
        return [], False, []

    notes: list[str] = []
    if not model_supports_google_search(model_id):
        notes.append("当前模型不支持 Google Search grounding，本次已自动忽略该开关。")
        return [], False, notes

    search_types_kwargs: dict[str, Any] = {"web_search": types.WebSearch()}
    actual_image_search = False

    if enable_image_search:
        if model_supports_image_search(model_id):
            search_types_kwargs["image_search"] = types.ImageSearch()
            actual_image_search = True
        else:
            notes.append("当前模型不支持 Image Search，本次仅启用 Google Search 文本 grounding。")

    return [
        types.Tool(
            google_search=types.GoogleSearch(
                search_types=types.SearchTypes(**search_types_kwargs)
            )
        )
    ], actual_image_search, notes


def summarize_grounding_mode(
    google_search_enabled: bool,
    image_search_enabled: bool,
) -> str:
    """把 grounding 状态转成简短文案。"""
    if not google_search_enabled:
        return "未启用"
    if image_search_enabled:
        return "Google Search + Image Search"
    return "Google Search"


def get_api_image_size(model_id: str, resolution: str) -> tuple[str, bool]:
    """解析 API 原生尺寸与是否需要本地缩放。"""
    model_meta = get_model_meta(model_id)
    if resolution in model_meta["native_sizes"]:
        return resolution, False
    return "1K", True


def resolve_aspect_ratio(model_id: str, aspect_ratio: str) -> tuple[str | None, bool]:
    """解析 API 原生比例与是否需要本地裁切。"""
    if aspect_ratio == AUTO_ASPECT_RATIO:
        # 自适应：不传宽高比，也不本地裁切，完全交给 Prompt / 参考图决定。
        return None, False
    model_meta = get_model_meta(model_id)
    if aspect_ratio in model_meta["native_aspects"]:
        return aspect_ratio, False
    fallback_map = MODEL_FALLBACK_ASPECTS.get(model_id, {})
    if aspect_ratio in fallback_map:
        return fallback_map[aspect_ratio], True
    return None, True


def parse_ratio(value: str) -> tuple[int, int]:
    """把 `16:9` 解析成整数比例。"""
    left, right = value.split(":")
    return int(left), int(right)


def crop_to_ratio(image: Image.Image, target_ratio: str) -> Image.Image:
    """居中裁切到指定宽高比。"""
    target_w, target_h = parse_ratio(target_ratio)
    target_value = target_w / target_h
    current_w, current_h = image.size
    current_value = current_w / current_h

    if abs(current_value - target_value) < 1e-4:
        return image

    if current_value > target_value:
        new_width = max(1, int(current_h * target_value))
        left = max(0, (current_w - new_width) // 2)
        return image.crop((left, 0, left + new_width, current_h))

    new_height = max(1, int(current_w / target_value))
    top = max(0, (current_h - new_height) // 2)
    return image.crop((0, top, current_w, top + new_height))


def resize_longest_side(image: Image.Image, longest_side: int) -> Image.Image:
    """把图片缩放到指定最长边。"""
    width, height = image.size
    current_longest = max(width, height)
    if current_longest == longest_side:
        return image
    scale = longest_side / current_longest
    return image.resize(
        (
            max(1, int(round(width * scale))),
            max(1, int(round(height * scale))),
        ),
        Image.LANCZOS,
    )


def ensure_pil_image(image_obj: Any) -> Image.Image:
    """把 SDK 返回对象统一转换成 PIL.Image。"""
    if hasattr(image_obj, "convert"):
        return image_obj.convert("RGB")

    loaded_image = getattr(image_obj, "_pil_image", None)
    if loaded_image is not None:
        return loaded_image.convert("RGB")

    image_bytes = getattr(image_obj, "image_bytes", None)
    if image_bytes:
        return Image.open(BytesIO(image_bytes)).convert("RGB")

    raise TypeError(f"暂不支持的图片对象类型：{type(image_obj).__name__}")


def postprocess_image(
    image: Any,
    requested_aspect_ratio: str,
    requested_resolution: str,
    needs_ratio_postprocess: bool,
    needs_resize_postprocess: bool,
) -> Image.Image:
    """执行本地裁切与缩放。"""
    result = ensure_pil_image(image)
    if needs_ratio_postprocess:
        result = crop_to_ratio(result, requested_aspect_ratio)
    if needs_resize_postprocess:
        result = resize_longest_side(result, LONGEST_SIDE_BY_RESOLUTION[requested_resolution])
    return result


def guess_mime_type(path: Path) -> str:
    """推断图片 MIME。"""
    mime_type, _ = mimetypes.guess_type(path.name)
    if mime_type and mime_type.startswith("image/"):
        return mime_type
    return "image/png"


def prepare_reference_parts(file_paths: list[str] | None) -> list[types.Part]:
    """把本地参考图转换成 SDK Part。"""
    if not file_paths:
        return []

    clean_paths = [Path(item) for item in file_paths if item]
    if len(clean_paths) > MAX_REFERENCE_IMAGES:
        raise ValueError(f"最多只能上传 {MAX_REFERENCE_IMAGES} 张参考图。")

    total_bytes = sum(path.stat().st_size for path in clean_paths if path.exists())
    if total_bytes > MAX_REFERENCE_BYTES:
        raise ValueError("参考图总大小超过 20MB，请压缩后再试。")

    parts: list[types.Part] = []
    for path in clean_paths:
        if not path.exists():
            raise ValueError(f"参考图不存在：{path}")
        parts.append(
            types.Part.from_bytes(
                data=path.read_bytes(),
                mime_type=guess_mime_type(path),
            )
        )
    return parts


def extract_first_image(response: Any) -> Image.Image:
    """从响应里提取首张图片。"""
    parts = getattr(response, "parts", None) or []
    for part in parts:
        inline_data = getattr(part, "inline_data", None)
        if not inline_data:
            continue
        try:
            image = part.as_image()
            if image:
                return ensure_pil_image(image)
        except Exception:
            pass

        data = getattr(inline_data, "data", None)
        if data:
            image_bytes = data.encode("utf-8") if isinstance(data, str) else data
            return Image.open(BytesIO(image_bytes)).convert("RGB")

    raise RuntimeError(explain_empty_image_response(response))


def extract_grounding_info(response: Any) -> dict[str, Any]:
    """提取 grounding 查询词与来源。"""
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return {"web_search_queries": [], "image_search_queries": [], "sources": []}

    grounding = getattr(candidates[0], "grounding_metadata", None)
    if grounding is None:
        return {"web_search_queries": [], "image_search_queries": [], "sources": []}

    web_queries = list(dict.fromkeys(getattr(grounding, "web_search_queries", None) or []))
    image_queries = list(dict.fromkeys(getattr(grounding, "image_search_queries", None) or []))
    sources: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for chunk in getattr(grounding, "grounding_chunks", None) or []:
        web = getattr(chunk, "web", None)
        if web and getattr(web, "uri", None):
            key = ("web", web.uri)
            if key not in seen:
                seen.add(key)
                sources.append(
                    {
                        "kind": "网页",
                        "title": getattr(web, "title", None) or getattr(web, "domain", None) or web.uri,
                        "url": web.uri,
                    }
                )

        image = getattr(chunk, "image", None)
        if image and (getattr(image, "source_uri", None) or getattr(image, "image_uri", None)):
            source_url = getattr(image, "source_uri", None) or getattr(image, "image_uri", None)
            key = ("image", source_url)
            if key not in seen:
                seen.add(key)
                sources.append(
                    {
                        "kind": "图片",
                        "title": getattr(image, "title", None) or getattr(image, "domain", None) or source_url,
                        "url": source_url,
                    }
                )

    return {
        "web_search_queries": web_queries,
        "image_search_queries": image_queries,
        "sources": sources,
    }


def build_grounding_markdown(grounding_info: dict[str, Any]) -> str:
    """整理 grounding 查询词和来源展示。"""
    lines: list[str] = []
    web_queries = grounding_info.get("web_search_queries") or []
    image_queries = grounding_info.get("image_search_queries") or []
    sources = grounding_info.get("sources") or []

    if web_queries:
        lines.append("Google Search 查询词：" + " / ".join(f"`{item}`" for item in web_queries[:5]))
    if image_queries:
        lines.append("Image Search 查询词：" + " / ".join(f"`{item}`" for item in image_queries[:5]))
    if sources:
        source_items = [
            f"{item['kind']}：[{item['title']}]({item['url']})"
            for item in sources[:6]
            if item.get("url")
        ]
        if source_items:
            lines.append("来源：  \n" + "  \n".join(source_items))
    return "\n\n".join(lines)


def explain_empty_image_response(response: Any) -> str:
    """把空响应转换成友好提示。"""
    finish_messages: list[str] = []
    prompt_feedback = getattr(response, "prompt_feedback", None)
    if prompt_feedback:
        block_reason = getattr(prompt_feedback, "block_reason", None)
        if block_reason:
            finish_messages.append(f"提示词被拦截：{block_reason}")

    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        finish_reason = getattr(candidate, "finish_reason", None)
        finish_message = getattr(candidate, "finish_message", None)
        if finish_reason:
            finish_messages.append(f"finish_reason={finish_reason}")
        if finish_message:
            finish_messages.append(str(finish_message))

    if finish_messages:
        raw_message = "；".join(dict.fromkeys(item for item in finish_messages if item))
        return map_error_message(RuntimeError(raw_message))

    return "模型没有返回图片结果，请尝试缩短 prompt、减少参考图，或稍后再试。"


def map_error_message(exc: Exception) -> str:
    """把常见异常转换成中文说明。"""
    raw_text = " ".join(
        [
            str(getattr(exc, "message", "") or ""),
            str(getattr(exc, "status", "") or ""),
            str(getattr(exc, "code", "") or ""),
            str(exc),
        ]
    ).strip()
    normalized = raw_text.lower()

    if not raw_text:
        return "请求失败，但没有拿到明确的错误信息。"
    if "winerror 10060" in normalized or "connecttimeout" in normalized:
        return (
            "连接 Google API 超时，当前更像是网络不通而不是 API Key 错误。"
            "如果你在国内网络环境，请配置可用代理，或在上方“设置”里填写 HTTP/SOCKS5 代理地址后重试。"
        )
    if "timed out" in normalized or "timeout" in normalized:
        return "请求超时（5 分钟内未完成）。请稍后重试，或降低分辨率 / 参考图数量。"
    if "api key not valid" in normalized or "unauthenticated" in normalized or "invalid api key" in normalized:
        return "API Key 无效，请检查是否复制完整，或确认该 Key 属于可用的 Google AI Studio 项目。"
    if "permission" in normalized or "forbidden" in normalized or "403" in normalized:
        return "当前 API Key 没有访问该模型的权限。请确认项目已开通计费，或改用可访问的模型。"
    if "quota" in normalized or "resource_exhausted" in normalized or "429" in normalized:
        return "配额已耗尽或触发限流。请稍后再试，或检查 Google AI Studio / Cloud Billing 的配额与计费状态。"
    if "safety" in normalized or "unsafe_prompt_for_image_generation" in normalized:
        return "内容被安全策略拦截，请调整 prompt 或参考图后重试。"
    if "blocked" in normalized or "rejected" in normalized or "filtered" in normalized:
        return "请求被模型拒绝，可能与安全策略、提示词表述或参考图内容有关。"
    if "output_mime_type parameter is not supported" in normalized:
        return "当前 Gemini 图像接口不支持 output_mime_type 参数，请升级到这份修复后的代码。"
    if "invalid_request_error" in normalized and "size" in normalized:
        return "GPT-Image-2-VIP 的 size 参数无效，请使用下拉框里的比例和分辨率组合，或改回支持的尺寸档位。"
    if "not found" in normalized or "404" in normalized:
        return "请求的模型不存在或当前 API 版本不可用。请更新到最新 `google-genai` 后重试。"
    if "exceeded" in normalized and "20mb" in normalized:
        return "上传内容超过接口允许大小，请压缩参考图后再试。"
    return f"请求失败：{raw_text}"


def ensure_seed(keep_seed: bool, seed_value: float | int | None) -> tuple[int, bool]:
    """生成本次任务的基础种子。"""
    if keep_seed:
        if seed_value in (None, ""):
            raise ValueError("已勾选“保持种子”，请填写一个整数种子。")
        return int(seed_value), True
    return random.randint(1, 2_147_483_647), False


def build_gallery_caption(
    model_label: str,
    prompt: str,
    seed: int,
    elapsed_seconds: float,
    aspect_ratio: str,
    resolution: str,
    grounding_summary: str,
) -> str:
    """构造画廊下方的说明文字。"""
    lines = [
        f"模型：{model_label}",
        f"Prompt：{prompt}",
        f"种子：{seed}",
        f"宽高比：{aspect_ratio}",
        f"分辨率：{resolution}",
        f"Grounding：{grounding_summary}",
        f"耗时：{elapsed_seconds:.1f}s",
    ]
    return "\n".join(lines)


def save_image_with_backup(
    image: Image.Image,
    index: int,
    conversation: dict[str, Any],
    output_root: Path,
    backup_root: Path,
) -> tuple[Path, Path]:
    """保存主图并同步写入备份目录。"""
    primary_dir = output_day_dir(output_root)
    backup_dir = output_day_dir(backup_root)
    file_name = f"{datetime.now().strftime('%H%M%S_%f')[:-3]}_{index:02d}.png"
    primary_path = primary_dir / file_name
    backup_path = backup_dir / file_name
    image.save(primary_path, format="PNG")
    shutil.copy2(primary_path, backup_path)
    return primary_path, backup_path


def create_zip_with_backup(
    image_paths: list[Path],
    conversation: dict[str, Any],
    output_root: Path,
    backup_root: Path,
) -> tuple[Path, Path]:
    """把本轮图片打包，同时保存备份 ZIP。"""
    primary_dir = output_day_dir(output_root)
    backup_dir = output_day_dir(backup_root)
    file_name = f"{datetime.now().strftime('%H%M%S_%f')[:-3]}_all.zip"
    primary_zip = primary_dir / file_name
    backup_zip = backup_dir / file_name
    with zipfile.ZipFile(primary_zip, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for image_path in image_paths:
            zip_file.write(image_path, arcname=image_path.name)
    shutil.copy2(primary_zip, backup_zip)
    return primary_zip, backup_zip


def build_batch_slug(batch_name: str | None) -> str:
    """生成批量任务的独立目录名。"""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    readable_name = safe_slug((batch_name or "").strip() or "batch")
    return f"{stamp}_{readable_name}_{uuid4().hex[:6]}"


def batch_prompt_dir(batch_root: Path, prompt_index: int, prompt: str) -> Path:
    """每条 Prompt 单独一个子目录，方便后续回看和整理。"""
    return batch_root / f"{prompt_index:03d}_{safe_slug(prompt)[:32]}"


def save_batch_image_with_backup(
    image: Image.Image,
    prompt_index: int,
    image_index: int,
    prompt: str,
    batch_root: Path,
    backup_batch_root: Path,
) -> tuple[Path, Path]:
    """保存批量任务图片，并同步写入备份目录。"""
    primary_dir = batch_prompt_dir(batch_root, prompt_index, prompt)
    backup_dir = batch_prompt_dir(backup_batch_root, prompt_index, prompt)
    primary_dir.mkdir(parents=True, exist_ok=True)
    backup_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"{datetime.now().strftime('%H%M%S_%f')[:-3]}_{image_index:02d}.png"
    primary_path = primary_dir / file_name
    backup_path = backup_dir / file_name
    image.save(primary_path, format="PNG")
    shutil.copy2(primary_path, backup_path)
    return primary_path, backup_path


def create_batch_zip_with_backup(
    image_paths: list[Path],
    batch_root: Path,
    backup_batch_root: Path,
) -> tuple[Path, Path]:
    """把批量任务所有图片打包，同时保存备份 ZIP。"""
    file_name = f"{batch_root.name}_all.zip"
    primary_zip = batch_root / file_name
    backup_zip = backup_batch_root / file_name
    with zipfile.ZipFile(primary_zip, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for image_path in image_paths:
            zip_file.write(image_path, arcname=image_path.relative_to(batch_root).as_posix())
    backup_batch_root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(primary_zip, backup_zip)
    return primary_zip, backup_zip


def build_reference_preview(file_paths: list[str] | None) -> tuple[gr.Gallery, str]:
    """把上传参考图转换成预览画廊。"""
    if not file_paths:
        return gr.update(value=[], visible=False), "未上传参考图。"

    items = []
    for file_path in file_paths[:MAX_REFERENCE_IMAGES]:
        path = Path(file_path)
        items.append((str(path), path.name))
    return (
        gr.update(value=items, visible=True),
        f"已选 {len(items)} 张参考图。点击缩略图可放大确认是否为正确图片。",
    )


def collect_reference_image_paths(*file_paths: str | None) -> list[str] | None:
    """把 5 个参考图槽位合并成路径列表。"""
    paths = [item for item in file_paths if item]
    return paths or None


def build_reference_slot_hint(*file_paths: str | None) -> str:
    """参考图槽位状态提示。"""
    paths = collect_reference_image_paths(*file_paths) or []
    if not paths:
        return "支持直接拖入、点击上传，或粘贴截图到任一参考图槽位。点击图片可放大确认。"
    return f"已放入 {len(paths)} 张参考图。支持继续拖入补充；点击图片可放大确认。"


def normalize_reference_gallery_value(value: Any) -> list[str]:
    """鎶婂弬鑰冨浘鐢诲粖鍊肩粺涓€鎴愭枃浠惰矾寰勫垪琛ㄣ€?"""
    if not value:
        return []

    paths: list[str] = []
    for item in value:
        candidate = item[0] if isinstance(item, (tuple, list)) else item
        if isinstance(candidate, Path):
            candidate = str(candidate)
        if isinstance(candidate, str) and candidate.strip():
            paths.append(candidate)
    return paths


def build_reference_gallery_items(file_paths: list[str] | None) -> list[str]:
    """鏍规嵁褰撳墠椤哄簭鏋勯€犲弬鑰冨浘鐢诲粖鍊笺€?"""
    return [str(path) for path in (file_paths or [])[:MAX_REFERENCE_IMAGES]]


def build_reference_gallery_hint(file_paths: list[str] | None = None) -> str:
    """鍙傝€冨浘鍖虹殑涓绘彁绀烘枃妗堛€?"""
    paths = file_paths or []
    if not paths:
        return f"支持直接拖入、点击上传和粘贴图片。最多 {MAX_REFERENCE_IMAGES} 张，点击缩略图可放大确认。"
    return f"已添加 {len(paths)} 张参考图。左到右的顺序就是 prompt 里的图 1 / 图 2 / 图 X 顺序。"


def build_reference_selection_hint(
    file_paths: list[str] | None,
    selected_index: int | None,
) -> str:
    """鏋勯€犲弬鑰冨浘鐨勯€変腑涓庨『搴忔彁绀恒€?"""
    paths = file_paths or []
    if not paths:
        return "未选择参考图。"

    order_line = " | ".join(
        f"图{index + 1}:{Path(path).name}" for index, path in enumerate(paths)
    )
    if selected_index is None or selected_index < 0 or selected_index >= len(paths):
        return f"当前顺序：{order_line}。点击下方图片后，可用“左移 / 右移”调整顺序。"

    return (
        f"已选中：图 {selected_index + 1}，{Path(paths[selected_index]).name}。"
        f" 当前顺序：{order_line}"
    )


def sync_reference_gallery_handler(
    gallery_value: Any,
) -> tuple[list[str], str, str, int]:
    """鍚屾鍙傝€冨浘鐢诲粖鍒扮姸鎬佷笌鎻愮ず銆?"""
    paths = normalize_reference_gallery_value(gallery_value)
    if len(paths) > MAX_REFERENCE_IMAGES:
        gr.Warning(f"最多只保留 {MAX_REFERENCE_IMAGES} 张参考图，已忽略多余部分。")
        paths = paths[:MAX_REFERENCE_IMAGES]

    return (
        paths,
        build_reference_gallery_hint(paths),
        build_reference_selection_hint(paths, -1),
        -1,
    )


def select_reference_image_handler(
    file_paths: list[str] | None,
    evt: gr.SelectData,
) -> tuple[gr.Gallery, str, int]:
    """璁板綍褰撳墠閫変腑鐨勫弬鑰冨浘锛屾柟渚夸箣鍚庤皟鏁撮『搴忋€?"""
    paths = file_paths or []
    index = int(evt.index) if getattr(evt, "index", None) is not None else -1
    if index < 0 or index >= len(paths):
        return gr.update(selected_index=None), build_reference_selection_hint(paths, -1), -1
    return (
        gr.update(selected_index=index),
        build_reference_selection_hint(paths, index),
        index,
    )


def move_reference_image_handler(
    file_paths: list[str] | None,
    selected_index: int | None,
    direction: int,
) -> tuple[gr.Gallery, list[str], str, str, int]:
    """鎸夌収褰撳墠閫変腑鍥剧墖鎶婂弬鑰冨浘鍚戝墠鎴栧悗璋冩暣銆?"""
    paths = list(file_paths or [])
    if not paths:
        raise gr.Error("请先上传参考图。")
    if selected_index is None or selected_index < 0 or selected_index >= len(paths):
        raise gr.Error("请先点击一张参考图，再调整顺序。")

    target_index = max(0, min(len(paths) - 1, selected_index + direction))
    if target_index != selected_index:
        moving_path = paths.pop(selected_index)
        paths.insert(target_index, moving_path)

    return (
        gr.update(value=build_reference_gallery_items(paths), selected_index=target_index),
        paths,
        build_reference_gallery_hint(paths),
        build_reference_selection_hint(paths, target_index),
        target_index,
    )


def remove_selected_reference_image_handler(
    file_paths: list[str] | None,
    selected_index: int | None,
) -> tuple[gr.Gallery, list[str], str, str, int]:
    """鍒犻櫎褰撳墠閫変腑鐨勫弬鑰冨浘锛屾柟渚夸慨姝ｉ『搴忋€?"""
    paths = list(file_paths or [])
    if not paths:
        return (
            gr.update(value=[], selected_index=None),
            [],
            build_reference_gallery_hint([]),
            build_reference_selection_hint([], -1),
            -1,
        )
    if selected_index is None or selected_index < 0 or selected_index >= len(paths):
        raise gr.Error("请先点击要移除的参考图。")

    paths.pop(selected_index)
    next_index = min(selected_index, len(paths) - 1) if paths else -1
    return (
        gr.update(
            value=build_reference_gallery_items(paths),
            selected_index=next_index if next_index >= 0 else None,
        ),
        paths,
        build_reference_gallery_hint(paths),
        build_reference_selection_hint(paths, next_index),
        next_index,
    )


def clear_reference_gallery_handler() -> tuple[gr.Gallery, list[str], str, str, int]:
    """娓呯┖鍙傝€冨浘銆?"""
    return (
        gr.update(value=[], selected_index=None),
        [],
        build_reference_gallery_hint([]),
        build_reference_selection_hint([], -1),
        -1,
    )


def append_reference_image_handler(
    new_image_path: str | None,
    file_paths: list[str] | None,
) -> tuple[gr.Image, gr.Gallery, list[str], str, str, int]:
    """把单个新增参考图追加到当前列表，并清空上传槽位。"""
    paths = list(file_paths or [])
    if not new_image_path:
        return (
            gr.update(value=None),
            gr.update(value=build_reference_gallery_items(paths), selected_index=None),
            paths,
            build_reference_gallery_hint(paths),
            build_reference_selection_hint(paths, -1),
            -1,
        )

    if len(paths) >= MAX_REFERENCE_IMAGES:
        gr.Warning(f"最多只能保留 {MAX_REFERENCE_IMAGES} 张参考图，请先移除后再添加。")
        selected_index = len(paths) - 1 if paths else -1
        return (
            gr.update(value=None),
            gr.update(
                value=build_reference_gallery_items(paths),
                selected_index=selected_index if selected_index >= 0 else None,
            ),
            paths,
            build_reference_gallery_hint(paths),
            build_reference_selection_hint(paths, selected_index),
            selected_index,
        )

    paths.append(new_image_path)
    selected_index = len(paths) - 1
    return (
        gr.update(value=None),
        gr.update(value=build_reference_gallery_items(paths), selected_index=selected_index),
        paths,
        build_reference_gallery_hint(paths),
        build_reference_selection_hint(paths, selected_index),
        selected_index,
    )


def append_reference_images_handler(
    new_image_paths: list[str] | None,
    file_paths: list[str] | None,
) -> tuple[gr.File, gr.Gallery, list[str], str, str, int]:
    """把一批新参考图追加到当前列表，并清空批量上传组件。"""
    paths = list(file_paths or [])
    incoming_paths = [item for item in (new_image_paths or []) if item]
    if not incoming_paths:
        selected_index = len(paths) - 1 if paths else -1
        return (
            gr.update(value=None),
            gr.update(
                value=build_reference_gallery_items(paths),
                selected_index=selected_index if selected_index >= 0 else None,
            ),
            paths,
            build_reference_gallery_hint(paths),
            build_reference_selection_hint(paths, selected_index),
            selected_index,
        )

    remaining_slots = max(0, MAX_REFERENCE_IMAGES - len(paths))
    accepted_paths = incoming_paths[:remaining_slots]
    if len(incoming_paths) > remaining_slots:
        gr.Warning(f"最多只能保留 {MAX_REFERENCE_IMAGES} 张参考图，超出的图片已忽略。")

    paths.extend(accepted_paths)
    selected_index = len(paths) - 1 if paths else -1
    return (
        gr.update(value=None),
        gr.update(
            value=build_reference_gallery_items(paths),
            selected_index=selected_index if selected_index >= 0 else None,
        ),
        paths,
        build_reference_gallery_hint(paths),
        build_reference_selection_hint(paths, selected_index),
        selected_index,
    )


def build_reference_selection_hint(
    file_paths: list[str] | None,
    selected_index: int | None,
) -> str:
    """构造参考图当前选中与顺序提示。"""
    paths = file_paths or []
    if not paths:
        return "未选择参考图。"

    order_line = " | ".join(
        f"图{index + 1}:{Path(path).name}" for index, path in enumerate(paths)
    )
    if selected_index is None or selected_index < 0 or selected_index >= len(paths):
        return f"当前顺序：{order_line}。请先在下拉框里选择要排序的图片。"

    return (
        f"已选中：图 {selected_index + 1}，{Path(paths[selected_index]).name}。"
        f" 当前顺序：{order_line}"
    )


def build_directory_link_markdown(
    primary_dir: Path | None,
    backup_dir: Path | None,
    label: str = "目录",
) -> str:
    """把输出目录和备份目录整理成简洁链接文案。"""
    links: list[str] = []
    if primary_dir:
        links.append(f"[打开主目录](<{primary_dir}>)")
    if backup_dir:
        links.append(f"[打开备份目录](<{backup_dir}>)")
    if not links:
        return ""
    prefix = f"{label}：" if label else ""
    return prefix + " · ".join(links)


def build_last_turn_asset_notice(turn: dict[str, Any] | None) -> str:
    """在恢复历史会话时，提示丢失的图片或压缩包。"""
    if not turn:
        return ""

    expected_image_count = max(
        len(turn.get("gallery_items") or []),
        len(turn.get("outputs") or []),
    )
    existing_image_count = len(build_gallery_from_turn(turn))
    zip_path = turn.get("zip_path")
    zip_exists = bool(zip_path and Path(zip_path).exists())
    notices: list[str] = []

    if expected_image_count and existing_image_count < expected_image_count:
        if existing_image_count == 0:
            notices.append("注意：上一轮历史图片当前未在本机可访问路径中，结果区暂时无法恢复旧图。")
        else:
            notices.append(
                f"注意：上一轮有 {expected_image_count - existing_image_count} 张历史图片未找到，当前只显示仍存在的文件。"
            )

    if zip_path and not zip_exists:
        notices.append("打包下载文件未找到，可能是输出目录已更换，或文件已被移动/删除。")

    return "\n\n".join(notices)


def build_turn_assistant_message(turn: dict[str, Any]) -> str:
    """把一次生成记录转换成聊天区助手消息。"""
    lines = [
        f"已生成 **{turn.get('image_count', 0)}** 张图",
        f"模型：`{turn.get('model_id', '')}`",
        f"宽高比：`{turn.get('aspect_ratio', '')}`，分辨率：`{turn.get('resolution', '')}`",
        f"Grounding：`{turn.get('grounding_summary', '未启用')}`",
        f"耗时：`{turn.get('elapsed_seconds', 0):.1f}s`",
    ]

    primary_dir = Path(turn["outputs"][0]).parent if turn.get("outputs") else None
    backup_dir = Path(turn["backup_outputs"][0]).parent if turn.get("backup_outputs") else None
    links_markdown = build_directory_link_markdown(primary_dir, backup_dir)
    if links_markdown:
        lines.append(links_markdown)
    return "\n\n".join(lines)


def build_prompt_message_content(prompt: str) -> str:
    """把用户 Prompt 渲染成带双复制按钮的聊天卡片。"""
    clean_prompt = prompt or ""
    prompt_b64 = base64.b64encode(clean_prompt.encode("utf-8")).decode("ascii")
    safe_prompt = escape(clean_prompt)
    copy_js = (
        "const card=this.closest('.prompt-copy-card');"
        "const bytes=Uint8Array.from(atob(card.dataset.promptB64),c=>c.charCodeAt(0));"
        "navigator.clipboard.writeText(new TextDecoder().decode(bytes));"
        "const old=this.textContent;"
        "this.textContent='已复制';"
        "setTimeout(()=>this.textContent=old,1200);"
    )
    button_html = (
        f'<button type="button" class="prompt-copy-button" onclick="{copy_js}">'
        "复制 Prompt"
        "</button>"
    )
    return (
        f'<div class="prompt-copy-card" data-prompt-b64="{prompt_b64}">'
        f'<div class="prompt-copy-top">{button_html}</div>'
        f'<div class="prompt-copy-text">{safe_prompt}</div>'
        f'<div class="prompt-copy-bottom">{button_html}</div>'
        "</div>"
    )


def build_chat_messages(turns: list[dict[str, Any]]) -> list[dict[str, str]]:
    """把若干轮会话记录转换成聊天消息。"""
    messages: list[dict[str, str]] = []
    for turn in turns:
        messages.append({"role": "user", "content": build_prompt_message_content(turn.get("prompt", ""))})
        messages.append({"role": "assistant", "content": build_turn_assistant_message(turn)})
    return messages


def build_older_history_markdown(turns: list[dict[str, Any]]) -> str:
    """把更早的对话整理成折叠区 Markdown。"""
    if not turns:
        return "暂无更多历史对话。"

    blocks: list[str] = [f"共折叠 **{len(turns)}** 组更早对话。"]
    for index, turn in enumerate(turns, start=1):
        blocks.append(
            "\n\n".join(
                [
                    f"#### 更早对话 {index}",
                    f"用户：\n\n{turn.get('prompt', '')}",
                    f"助手：\n\n{build_turn_assistant_message(turn)}",
                ]
            )
        )
    return "\n\n---\n\n".join(blocks)


def build_gallery_from_turn(turn: dict[str, Any] | None) -> list[tuple[str, str]]:
    """从最后一轮恢复结果画廊。"""
    if not turn:
        return []
    gallery_items = turn.get("gallery_items") or []
    return [
        (item["path"], item.get("caption", ""))
        for item in gallery_items
        if item.get("path") and Path(item["path"]).exists()
    ]


def build_download_file_list(turn: dict[str, Any] | None) -> list[str]:
    """从最后一轮恢复单张下载列表。"""
    if not turn:
        return []
    return [path for path in (turn.get("outputs") or []) if Path(path).exists()]


def build_session_title_markdown(conversation: dict[str, Any]) -> str:
    """隐藏的会话标题输出，用于保持回调结构稳定。"""
    title = conversation.get("title") or "临时任务"
    return f"**{title}**"


def build_folder_markdown(conversation: dict[str, Any], output_root: Path, backup_root: Path) -> str:
    """展示当天的主目录与备份目录。"""
    primary_dir = output_day_dir(output_root, create=False)
    backup_dir = output_day_dir(backup_root, create=False)
    return build_directory_link_markdown(primary_dir, backup_dir, label="当前目录")


def build_status_message(
    success_count: int,
    total_count: int,
    total_elapsed: float,
    requested_aspect: str,
    requested_resolution: str,
    used_model_id: str,
    grounding_summary: str,
    grounding_markdown: str,
    grounding_notes: list[str],
    conversation: dict[str, Any],
    output_root: Path,
    backup_root: Path,
) -> str:
    """构造结果区状态说明。"""
    lines = [
        f"本次完成：**{success_count}/{total_count}** 张，累计耗时 **{total_elapsed:.1f} 秒**。",
        f"模型：`{used_model_id}` · 宽高比：`{requested_aspect}` · 分辨率：`{requested_resolution}`。",
        f"Grounding：`{grounding_summary}`。",
        build_directory_link_markdown(
            output_day_dir(output_root, create=False),
            output_day_dir(backup_root, create=False),
        ),
    ]

    model_meta = get_model_meta(used_model_id)
    if requested_aspect == AUTO_ASPECT_RATIO:
        lines.append("说明：使用了 `自适应` 比例，未限制宽高比，画面比例由 Prompt / 参考图决定。")
    elif requested_aspect not in model_meta.get("native_aspects", set()):
        lines.append(f"说明：`{requested_aspect}` 不是该模型原生比例，程序已在本地做中心裁切。")
    if requested_resolution not in model_meta.get("native_sizes", set()):
        lines.append(f"说明：`{requested_resolution}` 不是该模型原生尺寸，程序已在本地做缩放处理。")

    lines.extend(grounding_notes)
    if grounding_markdown:
        lines.append(grounding_markdown)

    return "\n\n".join(lines)


def build_restored_status_message(
    turn: dict[str, Any] | None,
    conversation: dict[str, Any],
    output_root: Path,
    backup_root: Path,
) -> str:
    """根据结构化 turn 数据重建状态文案，避免旧路径文案长期滞留。"""
    if not turn:
        return "在下方输入 prompt 后开始生成。"

    success_count = int(turn.get("image_count") or 0)
    requested_count = int(turn.get("requested_image_count") or success_count or 1)
    restored = build_status_message(
        success_count=success_count,
        total_count=requested_count,
        total_elapsed=float(turn.get("elapsed_seconds") or 0),
        requested_aspect=str(turn.get("aspect_ratio") or "1:1"),
        requested_resolution=str(turn.get("resolution") or "1K"),
        used_model_id=str(turn.get("model_id") or MODEL_OPTIONS[0]["value"]),
        grounding_summary=str(turn.get("grounding_summary") or "未启用"),
        grounding_markdown=build_grounding_markdown(turn.get("grounding_info") or {}),
        grounding_notes=[],
        conversation=conversation,
        output_root=output_root,
        backup_root=backup_root,
    )
    if success_count < requested_count:
        restored += "\n\n注意：这轮生成只有部分图片成功保存。"
    return restored


def apply_directory_selection(selected_path: str | list[str] | None, picker_root: str) -> str:
    """把路径选择器结果转换成目录路径。"""
    if not selected_path:
        raise gr.Error("请先在路径选择器里点选一个目录或文件。")

    if isinstance(selected_path, list):
        selected_value = selected_path[0] if selected_path else ""
    else:
        selected_value = selected_path

    path = Path(selected_value)
    if not path.is_absolute():
        path = Path(picker_root) / path
    path = path.resolve()
    if path.is_file():
        path = path.parent
    return str(path)


def choose_directory_with_native_dialog(current_path: str, fallback_root: Path, dialog_title: str) -> str:
    """打开 Windows 原生文件夹选择框，让用户像安装软件一样选择目录。"""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:
        raise gr.Error("当前 Python 环境缺少桌面文件夹选择能力，请直接填写路径。") from exc

    initial_dir = resolve_existing_directory(current_path, fallback_root)
    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        root.lift()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(
            title=dialog_title,
            initialdir=str(initial_dir),
            mustexist=False,
        )
    except Exception as exc:
        raise gr.Error(f"打开系统目录选择框失败：{exc}") from exc
    finally:
        if root is not None:
            root.destroy()

    return selected or current_path or str(fallback_root)


def choose_output_dir_handler(current_path: str) -> str:
    """打开原生目录选择框并回填主输出目录。"""
    chosen = choose_directory_with_native_dialog(
        current_path=current_path,
        fallback_root=DEFAULT_OUTPUT_ROOT,
        dialog_title="选择出图储存位置",
    )
    gr.Info(f"主输出目录已选择：{chosen}")
    return chosen


def choose_backup_dir_handler(current_path: str) -> str:
    """打开原生目录选择框并回填备份目录。"""
    chosen = choose_directory_with_native_dialog(
        current_path=current_path,
        fallback_root=DEFAULT_BACKUP_ROOT,
        dialog_title="选择备份目录",
    )
    gr.Info(f"备份目录已选择：{chosen}")
    return chosen


def rename_conversation_handler(
    conversation_id: str | None,
    new_title: str,
    conversations_state: list[dict[str, Any]],
    output_root: str,
    backup_root: str,
) -> tuple[Any, ...]:
    """重命名当前会话。"""
    conversation = find_conversation(conversations_state, conversation_id)
    if not conversation:
        raise gr.Error("当前没有可重命名的会话。")

    title = (new_title or "").strip()
    if not title:
        raise gr.Error("请输入新的会话名称。")

    output_path, backup_path = ensure_storage_roots(output_root, backup_root)
    new_slug = build_conversation_slug(
        conversation["id"],
        title,
        conversation.get("created_at"),
    )
    conversation["title"] = title
    conversation["slug"] = new_slug
    conversation["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_conversations(conversations_state)
    row_ids, row_updates = build_compact_conversation_sidebar_updates(
        conversations_state,
        conversation["id"],
        "",
    )
    return (
        conversations_state,
        "",
        row_ids,
        *row_updates,
        build_session_title_markdown(conversation),
        build_folder_markdown(conversation, output_path, backup_path),
        title,
    )


def delete_conversation_handler(
    conversation_id: str | None,
    conversations_state: list[dict[str, Any]],
    output_root: str,
    backup_root: str,
) -> tuple[Any, ...]:
    """删除当前会话记录，但不删除磁盘上的输出与备份文件。"""
    if not conversation_id:
        raise gr.Error("当前没有可删除的会话。")

    remaining = [
        item
        for item in (conversations_state or [])
        if item.get("id") != conversation_id
    ]
    if len(remaining) == len(conversations_state or []):
        raise gr.Error("未找到要删除的会话。")

    if not remaining:
        fallback = create_conversation()
        remaining = [fallback]

    ordered = sorted(
        remaining,
        key=lambda item: item.get("updated_at", ""),
        reverse=True,
    )[:MAX_HISTORY]
    save_conversations(ordered)

    output_path, backup_path = ensure_storage_roots(output_root, backup_root)
    current_conversation = ordered[0]
    gr.Info("会话记录已删除；磁盘中的输出图片和备份图片不会删除。")

    return (
        ordered,
        *build_active_conversation_updates(
            current_conversation,
            ordered,
            str(output_path),
            str(backup_path),
            "",
        ),
    )


def get_conversation_view(
    conversation: dict[str, Any],
    output_root: Path,
    backup_root: Path,
) -> tuple[Any, ...]:
    """根据会话对象构造整套界面回填值。"""
    last_turn = get_last_turn(conversation)
    turns = conversation.get("turns") or []
    params = dict(DEFAULT_PARAMS)
    params.update(conversation.get("last_params") or {})
    gallery_items = build_gallery_from_turn(last_turn)
    download_files = build_download_file_list(last_turn)
    status_message = build_restored_status_message(
        last_turn,
        conversation,
        output_root,
        backup_root,
    )
    asset_notice = build_last_turn_asset_notice(last_turn)
    if asset_notice:
        status_message = f"{status_message}\n\n{asset_notice}"
    image_search_update, grounding_hint = refresh_grounding_controls(
        params["model_id"],
        bool(params["enable_google_search"]),
        bool(params["enable_image_search"]),
    )

    return (
        build_chat_messages(turns),
        "",
        build_session_title_markdown(conversation),
        gr.update(value=download_files, visible=bool(download_files)),
        gr.update(value=gallery_items),
        gr.update(value=None, visible=False),
        status_message,
        build_folder_markdown(conversation, output_root, backup_root),
        params["model_id"],
        params["aspect_ratio"],
        params["resolution"],
        int(params["image_count"]),
        bool(params["keep_seed"]),
        gr.update(value=params.get("seed"), interactive=bool(params["keep_seed"])),
        gr.update(value=bool(params["enable_google_search"])),
        image_search_update,
        grounding_hint,
    )


def build_active_conversation_updates(
    conversation: dict[str, Any],
    conversations_state: list[dict[str, Any]],
    output_root: str,
    backup_root: str,
    pending_delete_id: str = "",
) -> tuple[Any, ...]:
    """把当前会话回填成一整组界面更新值。"""
    output_path, backup_path = ensure_storage_roots(output_root, backup_root)
    view = get_conversation_view(conversation, output_path, backup_path)
    row_ids, row_updates = build_compact_conversation_sidebar_updates(
        conversations_state,
        conversation["id"],
        pending_delete_id,
    )
    return (
        conversation["id"],
        pending_delete_id,
        row_ids,
        *row_updates,
        view[0],
        view[1],
        view[2],
        view[3],
        view[4],
        view[5],
        view[6],
        view[7],
        conversation.get("title", ""),
        view[8],
        view[9],
        view[10],
        view[11],
        view[12],
        view[13],
        view[14],
        view[15],
        view[16],
        gr.update(value=None),
        gr.update(value=None),
        gr.update(value=[], selected_index=None),
        build_reference_gallery_hint([]),
        build_reference_selection_hint([], -1),
        [],
        -1,
    )


def build_sidebar_only_updates(
    conversations_state: list[dict[str, Any]],
    current_conversation_id: str | None,
    pending_delete_id: str | None = None,
) -> tuple[Any, ...]:
    """只刷新左侧会话列表和删除确认状态。"""
    row_ids, row_updates = build_compact_conversation_sidebar_updates(
        conversations_state,
        current_conversation_id,
        pending_delete_id,
    )
    return (
        current_conversation_id,
        pending_delete_id or "",
        row_ids,
        *row_updates,
    )


def get_conversation_id_by_row_index(
    row_index: int,
    row_ids_state: list[str] | None,
) -> str:
    """按行号拿到对应会话 ID。"""
    if row_ids_state and 0 <= row_index < len(row_ids_state):
        return row_ids_state[row_index]
    return ""


def select_conversation_row_handler(
    row_index: int,
    row_ids_state: list[str],
    conversations_state: list[dict[str, Any]],
    output_root: str,
    backup_root: str,
) -> tuple[Any, ...]:
    """点击某一行会话时加载该会话。"""
    conversation_id = get_conversation_id_by_row_index(row_index, row_ids_state)
    if not conversation_id:
        raise gr.Error("未找到该会话。")
    return load_conversation_handler(conversation_id, conversations_state, output_root, backup_root)


def ask_delete_conversation_row_handler(
    row_index: int,
    row_ids_state: list[str],
    conversations_state: list[dict[str, Any]],
    current_conversation_id: str | None,
) -> tuple[Any, ...]:
    """点击垃圾桶后，仅显示该行的确认删除。"""
    conversation_id = get_conversation_id_by_row_index(row_index, row_ids_state)
    if not conversation_id:
        raise gr.Error("未找到要删除的会话。")
    return build_sidebar_only_updates(conversations_state, current_conversation_id, conversation_id)


def cancel_delete_conversation_handler(
    conversations_state: list[dict[str, Any]],
    current_conversation_id: str | None,
) -> tuple[Any, ...]:
    """取消删除会话。"""
    return build_sidebar_only_updates(conversations_state, current_conversation_id, "")


def confirm_delete_conversation_row_handler(
    row_index: int,
    row_ids_state: list[str],
    conversations_state: list[dict[str, Any]],
    output_root: str,
    backup_root: str,
) -> tuple[Any, ...]:
    """确认删除某一行对应的会话。"""
    conversation_id = get_conversation_id_by_row_index(row_index, row_ids_state)
    if not conversation_id:
        raise gr.Error("未找到要删除的会话。")
    return delete_conversation_handler(conversation_id, conversations_state, output_root, backup_root)


def update_api_key_ui(api_key: str, remember_api_key: bool) -> tuple[gr.Button, str]:
    """API Key 输入框变化时刷新提示。"""
    return get_generate_button_update(api_key), build_api_hint_text(api_key, remember_api_key)


def save_settings_handler(
    api_key: str,
    proxy_url: str,
    api_base_url: str,
    output_root: str,
    backup_root: str,
    remember_api_key: bool,
) -> tuple[gr.Button, str]:
    """保存设置按钮事件。"""
    output_path, backup_path = ensure_storage_roots(output_root, backup_root)
    save_runtime_settings(
        api_key,
        proxy_url,
        api_base_url,
        str(output_path),
        str(backup_path),
        remember_api_key,
    )
    if normalize_api_key(api_key) and remember_api_key:
        gr.Info("设置已保存到 data/config.json，API Key 会在下次启动时自动回填。")
    elif normalize_api_key(api_key):
        gr.Info("设置已保存，但 API Key 只保留在当前运行中，重启后需要重新填写。")
    else:
        gr.Warning("设置已保存，但 API Key 为空，生成按钮会保持禁用。")
    base_dir_resolved = BASE_DIR.resolve()
    output_outside_base = not output_path.resolve().is_relative_to(base_dir_resolved)
    backup_outside_base = not backup_path.resolve().is_relative_to(base_dir_resolved)
    if output_outside_base or backup_outside_base:
        gr.Info("输出目录已保存在项目目录之外。若当前页面看不到新生成的图片，请重启一次应用，让新目录加入文件访问白名单。")
    return get_generate_button_update(api_key), build_api_hint_text(api_key, remember_api_key)


def update_generation_buttons_ui(
    api_key: str,
    remember_api_key: bool,
    prompt: str | None = None,
) -> tuple[gr.Button, gr.Button, str]:
    """同时刷新单次创作和批量生图的生成按钮。"""
    return (
        get_creative_generate_button_update(api_key, prompt),
        get_generate_button_update(api_key),
        build_api_hint_text(api_key, remember_api_key),
    )


def save_settings_for_all_pages_handler(
    api_key: str,
    proxy_url: str,
    api_base_url: str,
    output_root: str,
    backup_root: str,
    remember_api_key: bool,
    prompt: str | None = None,
) -> tuple[gr.Button, gr.Button, str]:
    """保存设置，并同步刷新两个页面的生成按钮。"""
    _generate_button_update, api_hint_text = save_settings_handler(
        api_key,
        proxy_url,
        api_base_url,
        output_root,
        backup_root,
        remember_api_key,
    )
    return get_creative_generate_button_update(api_key, prompt), get_generate_button_update(api_key), api_hint_text


def test_connection_handler(api_key: str, proxy_url: str, api_base_url: str) -> str:
    """测试连接按钮事件。"""
    if not normalize_api_key(api_key):
        raise gr.Error("请先填写 API Key。")
    try:
        client = make_client(api_key, proxy_url, api_base_url)
        response = client.models.generate_content(
            model=TEST_MODEL_ID,
            contents="ping",
            config=types.GenerateContentConfig(
                max_output_tokens=1,
                temperature=0,
                http_options=make_request_http_options(api_base_url),
            ),
        )
        _ = getattr(response, "text", None)
        endpoint_note = (
            f"自定义 Base URL：`{normalize_api_base_url(api_base_url)}`"
            if normalize_api_base_url(api_base_url)
            else "Google 官方端点"
        )
        gr.Info(f"连接测试成功：已通过 `{TEST_MODEL_ID}` 完成最小请求，当前使用 {endpoint_note}。")
        return "连接测试成功。"
    except Exception as exc:
        raise gr.Error(f"连接测试失败：{map_error_message(exc)}") from exc


def save_available_models(model_ids: list[str]) -> None:
    """把检测到的可用模型列表并入本地配置，供下次启动直接用。"""
    data = load_config()
    if not isinstance(data, dict):
        data = {}
    data["available_models"] = [m for m in model_ids if isinstance(m, str) and m]
    write_json_file(CONFIG_PATH, data)


def load_available_models() -> list[str]:
    """读取上次检测到的可用模型列表。"""
    data = load_config()
    models = data.get("available_models") if isinstance(data, dict) else None
    if isinstance(models, list):
        return [m for m in models if isinstance(m, str) and m]
    return []


def list_available_models(api_key: str, proxy_url: str, api_base_url: str) -> list[str]:
    """向当前端点查询账号 / 中转站可用的全部模型 ID。"""
    client = make_client(api_key, proxy_url, api_base_url)
    seen: set[str] = set()
    ordered: list[str] = []
    for model in client.models.list():
        name = getattr(model, "name", "") or ""
        model_id = name.split("/", 1)[1] if name.startswith("models/") else name
        model_id = (model_id or "").strip()
        if model_id and model_id not in seen:
            seen.add(model_id)
            ordered.append(model_id)
    return ordered


def build_model_choices(model_ids: list[str]) -> list[tuple[str, str]]:
    """把模型 ID 列表转成下拉框 (label, value)。已知模型显示友好名。"""
    choices: list[tuple[str, str]] = []
    for model_id in model_ids:
        if model_id in MODEL_BY_ID:
            label = MODEL_BY_ID[model_id]["label"]
        else:
            label = f"{model_id}（自动检测）"
        choices.append((label, model_id))
    return choices


def get_initial_model_choices() -> list[tuple[str, str]]:
    """启动时的模型下拉选项：优先用上次检测结果，否则用内置列表。"""
    detected = load_available_models()
    if detected:
        return build_model_choices(detected)
    return [(item["label"], item["value"]) for item in MODEL_OPTIONS]


def detect_models_handler(
    api_key: str,
    proxy_url: str,
    api_base_url: str,
    show_all: bool,
    current_model: str | None,
) -> tuple[Any, ...]:
    """检测可用模型：查询端点 → 筛图像模型 → 刷新所有模型下拉框并本地缓存。"""
    if not normalize_api_key(api_key):
        raise gr.Error("请先填写 API Key。")
    try:
        all_ids = list_available_models(api_key, proxy_url, api_base_url)
    except Exception as exc:
        raise gr.Error(f"检测失败：{map_error_message(exc)}") from exc

    if not all_ids:
        raise gr.Error("未检测到任何模型，请检查 API Key 与 Base URL 是否正确。")

    image_ids = [m for m in all_ids if is_probably_image_model(m)]
    chosen = all_ids if show_all else image_ids
    if not chosen:
        # 关键词没匹配到（可能是命名不含 image），退回展示全部，避免空列表。
        chosen = all_ids
        note = "（未按名称识别出图像模型，已列出全部模型，请自行选择图像模型）"
    else:
        note = ""

    save_available_models(chosen)
    choices = build_model_choices(chosen)
    values = [value for _, value in choices]
    creative_value = current_model if current_model in values else values[0]

    endpoint_note = (
        f"中转站 `{normalize_api_base_url(api_base_url)}`"
        if normalize_api_base_url(api_base_url)
        else "Google 官方端点"
    )
    status = (
        f"✅ 已从 {endpoint_note} 检测到 {len(all_ids)} 个模型"
        f"（疑似图像模型 {len(image_ids)} 个）。"
        f"下拉框已更新为 {len(chosen)} 个可选项。{note}"
    )
    gr.Info(status)

    row_updates = [gr.update(choices=choices) for _ in range(MAX_BATCH_ROWS)]
    return (
        status,
        gr.update(choices=choices, value=creative_value),
        gr.update(choices=choices),
        *row_updates,
    )


def new_conversation_handler(
    conversations_state: list[dict[str, Any]],
    output_root: str,
    backup_root: str,
) -> tuple[Any, ...]:
    """创建新会话并切换到它。"""
    new_conversation = create_conversation()
    conversations = [new_conversation, *(conversations_state or [])]
    save_conversations(conversations)
    return (
        conversations,
        *build_active_conversation_updates(
            new_conversation,
            conversations,
            output_root,
            backup_root,
            "",
        ),
    )


def load_conversation_handler(
    conversation_id: str | None,
    conversations_state: list[dict[str, Any]],
    output_root: str,
    backup_root: str,
) -> tuple[Any, ...]:
    """切换会话时回填聊天和最后一轮参数。"""
    conversation = find_conversation(conversations_state, conversation_id)
    if not conversation:
        raise gr.Error("未找到该会话，可能已被覆盖。")

    return build_active_conversation_updates(
        conversation,
        conversations_state,
        output_root,
        backup_root,
        "",
    )


def build_generate_noop_result(
    conversations_state: list[dict[str, Any]],
    conversation_id: str | None,
    output_root: str,
    backup_root: str,
    prompt_value: str,
    status_message: str | None = None,
) -> tuple[Any, ...]:
    """生成前校验失败时，保留当前界面并给出友好提示。"""
    conversations = conversations_state or []
    conversation = find_conversation(conversations, conversation_id)
    if not conversation:
        if conversations:
            conversation = conversations[0]
        else:
            conversation = create_conversation()
            conversations = [conversation]

    output_root_path, backup_root_path = ensure_storage_roots(output_root, backup_root)
    return (
        prompt_value,
        gr.update(choices=build_prompt_history_choices(load_prompt_history()), value=None),
        gr.update(),
        gr.update(),
        gr.update(),
        status_message or "在下方输入 prompt 后开始生成。",
        build_folder_markdown(conversation, output_root_path, backup_root_path),
        conversations,
        conversation["id"],
    )


def refresh_prompt_history_handler() -> gr.Dropdown:
    """手动刷新 Prompt 历史下拉列表。"""
    return gr.update(choices=build_prompt_history_choices(load_prompt_history()), value=None)


def use_prompt_history_handler(selected_prompt: str | None, api_key: str) -> tuple[Any, Any]:
    """把选中的历史 Prompt 填回输入框。"""
    prompt_value = "" if selected_prompt is None else str(selected_prompt)
    if not prompt_value.strip():
        gr.Warning("请先选择一条 Prompt 历史。")
        return gr.update(), get_creative_generate_button_update(api_key, "")
    return prompt_value, get_creative_generate_button_update(api_key, prompt_value)


def is_batch_gate_prompt(prompt: str | None) -> bool:
    """识别批量生图暗门指令。"""
    return (prompt or "").strip() == BATCH_GATE_COMMAND


def generate_handler(
    api_key: str,
    proxy_url: str,
    api_base_url: str,
    output_root: str,
    backup_root: str,
    conversation_id: str | None,
    conversations_state: list[dict[str, Any]],
    prompt: str,
    model_id: str,
    enable_google_search: bool,
    enable_image_search: bool,
    reference_image_paths: list[str] | None,
    aspect_ratio: str,
    resolution: str,
    image_count: int,
    keep_seed: bool,
    seed_value: float | int | None,
    progress: gr.Progress = gr.Progress(track_tqdm=False),
) -> tuple[Any, ...]:
    """主生成流程。"""
    if not normalize_api_key(api_key):
        message = "请先在上方设置 API Key。"
        gr.Warning(message)
        return build_generate_noop_result(
            conversations_state,
            conversation_id,
            output_root,
            backup_root,
            prompt or "",
            message,
        )

    clean_prompt = (prompt or "").strip()
    if not clean_prompt:
        message = "请输入 prompt 后再生成。"
        gr.Warning(message)
        return build_generate_noop_result(
            conversations_state,
            conversation_id,
            output_root,
            backup_root,
            prompt or "",
            message,
        )

    conversations = conversations_state or []
    conversation = find_conversation(conversations, conversation_id)
    if not conversation:
        conversation = create_conversation()
        conversations = [conversation, *conversations]

    try:
        output_root_path, backup_root_path = ensure_storage_roots(output_root, backup_root)
        update_conversation_title_if_needed(conversation, clean_prompt)
        base_seed, seed_locked = ensure_seed(keep_seed, seed_value)
        reference_paths = list(reference_image_paths or [])
        reference_parts = prepare_reference_parts(reference_paths)
        api_aspect_ratio, needs_ratio_postprocess = resolve_aspect_ratio(model_id, aspect_ratio)
        api_image_size, needs_resize_postprocess = get_api_image_size(model_id, resolution)
        tools, actual_image_search_enabled, grounding_notes = build_grounding_tool(
            model_id=model_id,
            enable_google_search=enable_google_search,
            enable_image_search=enable_image_search,
        )
        actual_google_search_enabled = bool(tools)
        grounding_summary = summarize_grounding_mode(
            actual_google_search_enabled, actual_image_search_enabled
        )
        effective_prompt = build_effective_prompt(
            prompt=clean_prompt,
            needs_ratio_postprocess=needs_ratio_postprocess,
            aspect_ratio=aspect_ratio,
        )
        client = None
        if not is_apiyi_openai_image_model(model_id):
            client = make_client(api_key, proxy_url, api_base_url)
    except Exception as exc:
        message = map_error_message(exc)
        gr.Warning(message)
        return build_generate_noop_result(
            conversations,
            conversation.get("id"),
            output_root,
            backup_root,
            prompt or "",
            message,
        )

    gallery_items: list[tuple[str, str]] = []
    saved_primary_paths: list[Path] = []
    saved_backup_paths: list[Path] = []
    stored_gallery_items: list[dict[str, str]] = []
    per_image_seeds: list[int] = []
    grounding_info: dict[str, Any] = {"web_search_queries": [], "image_search_queries": [], "sources": []}
    total_start = perf_counter()
    last_error: str | None = None

    for index in range(int(image_count)):
        _n = int(image_count)
        _base = index / _n
        _frac = 1.0 / _n
        image_seed = base_seed + index
        per_image_seeds.append(image_seed)

        # ── 阶段 1：发送 ─────────────────────────────────────────
        progress(_base + _frac * 0.04, desc=f"[{index + 1}/{_n}] 发送中...")

        # ── 阶段 2：接收（后台线程按实际耗时实时推送进度）────────
        _stop_timer = threading.Event()
        request_start = perf_counter()

        def _recv_updater(
            _stop=_stop_timer, _b=_base, _f=_frac,
            _t=request_start, _i=index, _total=_n,
        ) -> None:
            while not _stop.wait(0.5):
                _el = perf_counter() - _t
                # 渐近曲线：~0.5 at 20s, ~0.75 at 60s, 上限 85%
                _p = _el / (_el + 20)
                _v = min(_b + _f * (0.08 + 0.77 * _p), _b + _f * 0.85)
                try:
                    progress(_v, desc=f"[{_i + 1}/{_total}] 接收中... {_el:.0f}s")
                except Exception:
                    pass

        _recv_thread = threading.Thread(target=_recv_updater, daemon=True)
        _recv_thread.start()
        try:
            if is_apiyi_openai_image_model(model_id):
                image = generate_apiyi_openai_image(
                    api_key=api_key,
                    proxy_url=proxy_url,
                    api_base_url=api_base_url,
                    model_id=model_id,
                    prompt=effective_prompt,
                    reference_paths=reference_paths,
                    resolution=resolution,
                    api_aspect_ratio=api_aspect_ratio,
                )
            else:
                parts = [types.Part.from_text(text=effective_prompt), *reference_parts]
                config_kwargs: dict[str, Any] = {
                    "response_modalities": ["Image"],
                    "seed": image_seed,
                    "candidate_count": 1,
                    "http_options": make_request_http_options(api_base_url),
                }
                if tools:
                    config_kwargs["tools"] = tools
                if api_aspect_ratio:
                    config_kwargs["image_config"] = types.ImageConfig(
                        aspect_ratio=api_aspect_ratio,
                        image_size=api_image_size,
                    )
                else:
                    config_kwargs["image_config"] = types.ImageConfig(image_size=api_image_size)

                if client is None:
                    raise RuntimeError("Gemini 客户端未初始化。")
                response = client.models.generate_content(
                    model=model_id,
                    contents=types.Content(role="user", parts=parts),
                    config=types.GenerateContentConfig(**config_kwargs),
                )
                if index == 0:
                    grounding_info = extract_grounding_info(response)
                image = extract_first_image(response)
            _stop_timer.set()
            _recv_thread.join(timeout=1)
            _api_elapsed = perf_counter() - request_start

            # ── 阶段 3：完成，保存图片 ─────────────────────────
            progress(
                _base + _frac * 0.90,
                desc=f"[{index + 1}/{_n}] 完成 ({_api_elapsed:.1f}s)，保存中...",
            )
            image = postprocess_image(
                image=image,
                requested_aspect_ratio=aspect_ratio,
                requested_resolution=resolution,
                needs_ratio_postprocess=needs_ratio_postprocess,
                needs_resize_postprocess=needs_resize_postprocess,
            )
            primary_path, backup_path = save_image_with_backup(
                image=image,
                index=index + 1,
                conversation=conversation,
                output_root=output_root_path,
                backup_root=backup_root_path,
            )
            elapsed = perf_counter() - request_start
            caption = build_gallery_caption(
                model_label=MODEL_LABELS.get(model_id, model_id),
                prompt=clean_prompt,
                seed=image_seed,
                elapsed_seconds=elapsed,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                grounding_summary=grounding_summary,
            )
            gallery_items.append((str(primary_path), caption))
            saved_primary_paths.append(primary_path)
            saved_backup_paths.append(backup_path)
            stored_gallery_items.append(
                {
                    "path": str(primary_path),
                    "backup_path": str(backup_path),
                    "caption": caption,
                }
            )
            progress(_base + _frac, desc=f"第 {index + 1}/{_n} 张已完成 ✓")
        except Exception as exc:
            _stop_timer.set()
            _recv_thread.join(timeout=1)
            last_error = map_error_message(exc)
            if not saved_primary_paths:
                gr.Warning(last_error)
                return build_generate_noop_result(
                    conversations,
                    conversation.get("id"),
                    output_root,
                    backup_root,
                    prompt or "",
                    last_error,
                )
            break

    total_elapsed = perf_counter() - total_start
    progress(1.0, desc="全部完成 ✓")

    if not saved_primary_paths:
        message = last_error or "生成失败，未拿到任何图片。"
        gr.Warning(message)
        return build_generate_noop_result(
            conversations,
            conversation.get("id"),
            output_root,
            backup_root,
            prompt or "",
            message,
        )

    grounding_markdown = build_grounding_markdown(grounding_info)
    status_message = build_status_message(
        success_count=len(saved_primary_paths),
        total_count=int(image_count),
        total_elapsed=total_elapsed,
        requested_aspect=aspect_ratio,
        requested_resolution=resolution,
        used_model_id=model_id,
        grounding_summary=grounding_summary,
        grounding_markdown=grounding_markdown,
        grounding_notes=grounding_notes,
        conversation=conversation,
        output_root=output_root_path,
        backup_root=backup_root_path,
    )
    if last_error:
        status_message += f"\n\n部分失败说明：{last_error}"

    conversation["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conversation["turns"] = []
    conversation["last_params"] = {
        "model_id": model_id,
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
        "image_count": int(image_count),
        "keep_seed": seed_locked,
        "seed": base_seed,
        "enable_google_search": actual_google_search_enabled,
        "enable_image_search": actual_image_search_enabled,
    }
    prompt_history = add_prompt_history_entry(clean_prompt, conversation["last_params"])

    return (
        "",
        gr.update(choices=build_prompt_history_choices(prompt_history), value=None),
        gr.update(value=gallery_items),
        gr.update(value=[str(path) for path in saved_primary_paths], visible=True),
        gr.update(value=None, visible=False),
        status_message,
        build_folder_markdown(conversation, output_root_path, backup_root_path),
        conversations,
        conversation["id"],
    )


def generate_or_unlock_batch_handler(
    api_key: str,
    proxy_url: str,
    api_base_url: str,
    output_root: str,
    backup_root: str,
    conversation_id: str | None,
    conversations_state: list[dict[str, Any]],
    prompt: str,
    model_id: str,
    enable_google_search: bool,
    enable_image_search: bool,
    reference_image_paths: list[str] | None,
    aspect_ratio: str,
    resolution: str,
    image_count: int,
    keep_seed: bool,
    seed_value: float | int | None,
    progress: gr.Progress = gr.Progress(track_tqdm=False),
) -> tuple[Any, ...]:
    """生成按钮入口：暗门指令只解锁批量生图，不调用 API。"""
    if is_batch_gate_prompt(prompt):
        gr.Info("批量生图已解锁。")
        noop_result = build_generate_noop_result(
            conversations_state,
            conversation_id,
            output_root,
            backup_root,
            "",
            "批量生图已解锁。已为你打开批量生图页面；这个暗门指令不会消耗 Token。",
        )
        return (
            *noop_result,
            gr.update(
                choices=["创作工作台", "图片编辑", "批量生图"],
                value="批量生图",
                visible=True,
            ),
            gr.update(visible=False),  # 创作工作台
            gr.update(visible=False),  # 图片编辑
            gr.update(visible=True),   # 批量生图
        )

    result = generate_handler(
        api_key,
        proxy_url,
        api_base_url,
        output_root,
        backup_root,
        conversation_id,
        conversations_state,
        prompt,
        model_id,
        enable_google_search,
        enable_image_search,
        reference_image_paths,
        aspect_ratio,
        resolution,
        image_count,
        keep_seed,
        seed_value,
        progress,
    )
    return (
        *result,
        gr.update(),
        gr.update(),
        gr.update(),
        gr.update(),
    )


CREATIVE_PAGE_NAME = "创作工作台"
EDIT_PAGE_NAME = "图片编辑"
BATCH_PAGE_NAME = "批量生图"


def switch_workspace_page(page_name: str) -> tuple[Any, Any, Any]:
    """在创作工作台 / 图片编辑 / 批量生图三个独立页面之间切换。"""
    return (
        gr.update(visible=page_name == CREATIVE_PAGE_NAME),
        gr.update(visible=page_name == EDIT_PAGE_NAME),
        gr.update(visible=page_name == BATCH_PAGE_NAME),
    )


def clamp_positive_int(value: int | float | None, default: int, max_value: int) -> int:
    """把 UI 数值约束在安全范围内。"""
    if value in (None, ""):
        return default
    return max(1, min(int(value), max_value))


def compact_table_text(text: str, max_chars: int = 120) -> str:
    """让批量队列表格更像看板，避免长 Prompt 把行高撑爆。"""
    compacted = re.sub(r"\s+", " ", (text or "").strip())
    if len(compacted) <= max_chars:
        return compacted
    return f"{compacted[: max_chars - 3]}..."


def normalize_uploaded_reference_paths(value: Any) -> list[str]:
    """把 Gradio 上传组件的值统一成参考图路径列表。"""
    if not value:
        return []

    items = value if isinstance(value, (list, tuple, set)) else [value]
    paths: list[str] = []
    for item in items:
        candidate = item
        if isinstance(candidate, (list, tuple)) and candidate:
            candidate = candidate[0]
        if isinstance(candidate, dict):
            candidate = candidate.get("path") or candidate.get("name") or candidate.get("orig_name")
        if isinstance(candidate, Path):
            candidate = str(candidate)
        if not isinstance(candidate, str):
            candidate = getattr(candidate, "name", "")
        if isinstance(candidate, str) and candidate.strip():
            paths.append(candidate.strip())
    return paths


def build_batch_reference_hint(file_paths: list[str] | None = None) -> str:
    """批量页每行参考图提示。"""
    paths = file_paths or []
    if not paths:
        return "未添加参考图。可反复拖入或点击上传，上传后会自动清空上传框，方便继续补图。"
    return f"已添加 {len(paths)} 张参考图。继续拖入会追加到本批次；最多 {MAX_REFERENCE_IMAGES} 张。"


def append_batch_reference_images_handler(
    new_image_paths: Any,
    current_paths: list[str] | None,
) -> tuple[Any, Any, list[str], str]:
    """批量页追加参考图，并立刻清空上传框，保证可以再次拖入。"""
    paths = normalize_uploaded_reference_paths(current_paths)
    incoming_paths = normalize_uploaded_reference_paths(new_image_paths)
    if not incoming_paths:
        return (
            gr.update(value=None),
            gr.update(value=build_reference_gallery_items(paths), visible=bool(paths)),
            paths,
            build_batch_reference_hint(paths),
        )

    remaining_slots = max(0, MAX_REFERENCE_IMAGES - len(paths))
    accepted_paths = incoming_paths[:remaining_slots]
    if len(incoming_paths) > remaining_slots:
        gr.Warning(f"本批次最多只能保留 {MAX_REFERENCE_IMAGES} 张参考图，超出的图片已忽略。")
    paths.extend(accepted_paths)

    return (
        gr.update(value=None),
        gr.update(value=build_reference_gallery_items(paths), visible=bool(paths)),
        paths,
        build_batch_reference_hint(paths),
    )


def clear_batch_reference_images_handler() -> tuple[Any, Any, list[str], str]:
    """清空单个批次行的参考图。"""
    return (
        gr.update(value=None),
        gr.update(value=[], visible=False),
        [],
        build_batch_reference_hint([]),
    )


def merge_batch_prompt(prompt: str, global_prompt_suffix: str | None) -> str:
    """把单行 Prompt 和批次统一要求合并。"""
    clean_prompt = (prompt or "").strip()
    clean_suffix = (global_prompt_suffix or "").strip()
    if not clean_suffix:
        return clean_prompt
    return f"{clean_prompt}\n\n统一要求：{clean_suffix}"


def collect_batch_tasks(
    row_values: tuple[Any, ...],
    global_prompt_suffix: str | None = None,
) -> list[dict[str, Any]]:
    """从固定任务表里收集有效行；空行自动跳过。"""
    if len(row_values) % MAX_BATCH_ROW_INPUT_SIZE != 0:
        raise ValueError("批量任务表参数数量异常，请刷新页面后再试。")

    tasks: list[dict[str, Any]] = []
    clean_global_suffix = (global_prompt_suffix or "").strip()
    for offset in range(0, len(row_values), MAX_BATCH_ROW_INPUT_SIZE):
        row_index = offset // MAX_BATCH_ROW_INPUT_SIZE + 1
        (
            reference_value,
            prompt_value,
            model_id,
            enable_google_search,
            enable_image_search,
            aspect_ratio,
            resolution,
            images_per_prompt,
            keep_seed,
            seed_value,
        ) = row_values[offset : offset + MAX_BATCH_ROW_INPUT_SIZE]

        reference_paths = normalize_uploaded_reference_paths(reference_value)
        clean_prompt = (prompt_value or "").strip()
        if not clean_prompt and not reference_paths:
            continue
        if len(reference_paths) > MAX_REFERENCE_IMAGES:
            raise ValueError(f"第 {row_index} 行最多上传 {MAX_REFERENCE_IMAGES} 张参考图，请删减后再生成。")

        prompt_source = "用户输入"
        if not clean_prompt:
            prompt_source = "默认图生图提示"
            clean_prompt = "请基于本行参考图生成一张高质量图片，保持主体特征、构图逻辑和整体风格，并自然提升细节。"
        if keep_seed and seed_value in (None, ""):
            raise ValueError(f"第 {row_index} 行已勾选保持种子，请填写起始种子。")
        final_prompt = merge_batch_prompt(clean_prompt, clean_global_suffix)

        task = {
            "row_index": row_index,
            "reference_paths": reference_paths,
            "prompt": final_prompt,
            "row_prompt": clean_prompt,
            "global_prompt_suffix": clean_global_suffix,
            "prompt_source": prompt_source,
            "model_id": model_id or DEFAULT_PARAMS["model_id"],
            "enable_google_search": bool(enable_google_search),
            "enable_image_search": bool(enable_image_search),
            "aspect_ratio": aspect_ratio or DEFAULT_PARAMS["aspect_ratio"],
            "resolution": resolution or DEFAULT_PARAMS["resolution"],
            "images_per_prompt": clamp_positive_int(images_per_prompt, 1, MAX_GENERATE_IMAGES),
            "keep_seed": bool(keep_seed),
            "seed_value": seed_value,
        }
        tasks.append(task)

    if not tasks:
        raise ValueError("请至少填写一行任务：上传参考图或输入 Prompt 都可以。")
    if len(tasks) > MAX_BATCH_ROWS:
        raise ValueError(f"单个批次最多支持 {MAX_BATCH_ROWS} 行任务。")

    total_requested = sum(int(task["images_per_prompt"]) for task in tasks)
    if total_requested > MAX_BATCH_TOTAL_IMAGES:
        raise ValueError(
            f"本批次共 {total_requested} 张，超过安全上限 {MAX_BATCH_TOTAL_IMAGES} 张。"
            "请减少任务行或每行出图数。"
        )
    return tasks


def build_batch_task_rows(tasks: list[dict[str, Any]], status: str) -> list[list[Any]]:
    """把任务转成批量队列表格行。"""
    rows: list[list[Any]] = []
    for task in tasks:
        model_label = get_model_meta(task["model_id"])["short_name"]
        grounding = []
        if task["enable_google_search"]:
            grounding.append("Search")
        if task["enable_image_search"]:
            grounding.append("Image")
        note = f"{model_label} · {task['aspect_ratio']} · {task['resolution']}"
        if grounding:
            note = f"{note} · {'+'.join(grounding)}"
        if task["global_prompt_suffix"]:
            note = f"{note} · 统一要求"

        rows.append(
            [
                task["row_index"],
                status,
                f"{len(task['reference_paths'])} 张" if task["reference_paths"] else "无（文生图）",
                compact_table_text(task["prompt"]),
                f"0/{task['images_per_prompt']}",
                note,
            ]
        )
    return rows


def preview_batch_tasks_handler(
    global_prompt_suffix: str,
    *row_values: Any,
) -> tuple[list[list[Any]], str]:
    """生成前预览有效任务，降低误跑大批次的风险。"""
    try:
        tasks = collect_batch_tasks(row_values, global_prompt_suffix)
    except ValueError as exc:
        return [], f"预览未通过：{exc}"

    total_images = sum(int(task["images_per_prompt"]) for task in tasks)
    image_to_image_count = sum(1 for task in tasks if task["reference_paths"])
    text_to_image_count = len(tasks) - image_to_image_count
    status = (
        f"预览通过：将执行 **{len(tasks)}** 行任务，"
        f"其中图生图 **{image_to_image_count}** 行、文生图 **{text_to_image_count}** 行，"
        f"预计生成 **{total_images}** 张图。确认无误后点击“开始批量生成”。"
    )
    return build_batch_task_rows(tasks, "已识别"), status


def apply_batch_defaults_handler(
    model_id: str,
    enable_google_search: bool,
    enable_image_search: bool,
    aspect_ratio: str,
    resolution: str,
    images_per_prompt: int,
) -> tuple[Any, ...]:
    """把顶部默认参数一次性同步到全部任务行。"""
    image_search_update, grounding_hint = refresh_grounding_controls(
        model_id, enable_google_search, enable_image_search
    )
    safe_count = clamp_positive_int(images_per_prompt, 1, MAX_GENERATE_IMAGES)
    updates: list[Any] = []
    for _ in range(MAX_BATCH_ROWS):
        updates.extend(
            [
                gr.update(value=model_id),
                gr.update(value=bool(enable_google_search)),
                image_search_update,
                gr.update(value=aspect_ratio),
                gr.update(value=resolution),
                gr.update(value=safe_count),
                grounding_hint,
            ]
        )
    return tuple(updates)


def clear_batch_table_handler() -> tuple[Any, ...]:
    """清空批量页的任务输入和结果状态。"""
    row_updates: list[Any] = []
    for _ in range(MAX_BATCH_ROWS):
        row_updates.extend(
            [
                gr.update(value=None),
                gr.update(value=[], visible=False),
                [],
                build_batch_reference_hint([]),
                gr.update(value=""),
                gr.update(value=DEFAULT_PARAMS["model_id"]),
                gr.update(value=False),
                gr.update(value=False, interactive=False),
                gr.update(value=DEFAULT_PARAMS["aspect_ratio"]),
                gr.update(value=DEFAULT_PARAMS["resolution"]),
                gr.update(value=1),
                gr.update(value=False),
                gr.update(value=None, interactive=False),
            ]
        )

    return (
        gr.update(value=""),
        *row_updates,
        INITIAL_BATCH_ROWS,
        *build_batch_row_visibility_updates(INITIAL_BATCH_ROWS),
        build_batch_visible_rows_text(INITIAL_BATCH_ROWS),
        gr.update(value=[]),
        f"批量表已清空。默认显示 {INITIAL_BATCH_ROWS} 行；需要更多时点击“手动添加批次”。",
        "",
        gr.update(value=[]),
        gr.update(value=[], visible=False),
        gr.update(value=None, visible=False),
    )


def normalize_batch_visible_count(visible_count: Any) -> int:
    """把当前显示行数约束在批量页支持范围内。"""
    try:
        count = int(visible_count)
    except (TypeError, ValueError):
        count = INITIAL_BATCH_ROWS
    return max(INITIAL_BATCH_ROWS, min(count, MAX_BATCH_ROWS))


def build_batch_visible_rows_text(visible_count: int) -> str:
    """构造当前可见批次数提示。"""
    count = normalize_batch_visible_count(visible_count)
    return f"当前显示 **{count}/{MAX_BATCH_ROWS}** 个批次。空批次会自动跳过。"


def build_batch_row_visibility_updates(visible_count: int) -> list[Any]:
    """根据可见数量刷新批次行显隐。"""
    count = normalize_batch_visible_count(visible_count)
    return [gr.update(visible=index <= count) for index in range(1, MAX_BATCH_ROWS + 1)]


def add_batch_row_handler(visible_count: Any) -> tuple[Any, ...]:
    """手动展开一个新的批次行。"""
    current_count = normalize_batch_visible_count(visible_count)
    next_count = min(current_count + 1, MAX_BATCH_ROWS)
    if current_count >= MAX_BATCH_ROWS:
        gr.Warning(f"当前最多支持 {MAX_BATCH_ROWS} 个批次。")
    return (
        next_count,
        *build_batch_row_visibility_updates(next_count),
        build_batch_visible_rows_text(next_count),
    )


def clone_batch_rows(rows: list[list[Any]]) -> list[list[Any]]:
    """Dataframe 更新时返回新列表，避免前端拿不到变更。"""
    return [list(row) for row in rows]


def build_batch_manifest(
    batch_name: str,
    tasks: list[dict[str, Any]],
    rows: list[list[Any]],
    image_paths: list[Path],
    backup_paths: list[Path],
    zip_path: Path | None,
    backup_zip_path: Path | None,
) -> dict[str, Any]:
    """记录批量任务元数据，方便后续追加历史管理。"""
    return {
        "id": uuid4().hex,
        "batch_name": batch_name,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "prompts": [task["prompt"] for task in tasks],
        "tasks": [
            {
                "row_index": task["row_index"],
                "prompt": task["prompt"],
                "prompt_source": task["prompt_source"],
                "reference_paths": task["reference_paths"],
                "model_id": task["model_id"],
                "aspect_ratio": task["aspect_ratio"],
                "resolution": task["resolution"],
                "images_per_prompt": task["images_per_prompt"],
                "keep_seed": task["keep_seed"],
                "seed_value": task["seed_value"],
                "enable_google_search": task["enable_google_search"],
                "enable_image_search": task["enable_image_search"],
            }
            for task in tasks
        ],
        "rows": rows,
        "outputs": [str(path) for path in image_paths],
        "backup_outputs": [str(path) for path in backup_paths],
        "zip_path": str(zip_path) if zip_path else "",
        "backup_zip_path": str(backup_zip_path) if backup_zip_path else "",
    }


def batch_generate_handler(
    api_key: str,
    proxy_url: str,
    api_base_url: str,
    output_root: str,
    backup_root: str,
    global_prompt_suffix: str,
    *row_values: Any,
    progress: gr.Progress = gr.Progress(track_tqdm=False),
):
    """独立批量生图流程：按行读取参考图、Prompt 与参数，不写入单次创作会话。"""
    if not normalize_api_key(api_key):
        raise gr.Error("请先在上方设置 API Key。")

    try:
        tasks = collect_batch_tasks(row_values, global_prompt_suffix)
        total_requested = sum(int(task["images_per_prompt"]) for task in tasks)
        output_root_path, backup_root_path = ensure_storage_roots(output_root, backup_root)
        final_batch_name = f"批量生图 {datetime.now().strftime('%m-%d %H:%M')}"
        batch_slug = build_batch_slug(final_batch_name)
        batch_root = output_day_dir(output_root_path) / "batches" / batch_slug
        backup_batch_root = output_day_dir(backup_root_path) / "batches" / batch_slug
        batch_root.mkdir(parents=True, exist_ok=True)
        backup_batch_root.mkdir(parents=True, exist_ok=True)
        client = make_client(api_key, proxy_url, api_base_url)
    except ValueError as exc:
        raise gr.Error(str(exc)) from exc
    except Exception as exc:
        raise gr.Error(map_error_message(exc)) from exc

    rows = build_batch_task_rows(tasks, "待生成")
    gallery_items: list[tuple[str, str]] = []
    saved_primary_paths: list[Path] = []
    saved_backup_paths: list[Path] = []
    batch_start = perf_counter()
    folder_markdown = build_directory_link_markdown(batch_root, backup_batch_root, "批量目录")
    status_message = (
        f"批次 `{final_batch_name}` 已准备：{len(tasks)} 行任务，共 {total_requested} 张图。"
    )
    yield (
        gr.update(value=gallery_items),
        clone_batch_rows(rows),
        gr.update(value=[], visible=False),
        gr.update(value=None, visible=False),
        status_message,
        folder_markdown,
        gr.update(),
    )

    global_image_index = 0
    for task_order, task in enumerate(tasks, start=1):
        row_position = task_order - 1
        prompt_index = int(task["row_index"])
        prompt = task["prompt"]
        per_prompt_count = int(task["images_per_prompt"])
        rows[row_position][1] = "生成中"
        rows[row_position][5] = ""
        yield (
            gr.update(value=gallery_items),
            clone_batch_rows(rows),
            gr.update(value=[], visible=False),
            gr.update(value=None, visible=False),
            f"正在生成第 {task_order}/{len(tasks)} 行任务。",
            folder_markdown,
            gr.update(),
        )

        prompt_success_count = 0
        last_error = ""
        grounding_notes: list[str] = []
        grounding_summary = "关闭"
        try:
            base_seed, _seed_locked = ensure_seed(task["keep_seed"], task["seed_value"])
            reference_parts = prepare_reference_parts(task["reference_paths"])
            api_aspect_ratio, needs_ratio_postprocess = resolve_aspect_ratio(
                task["model_id"], task["aspect_ratio"]
            )
            api_image_size, needs_resize_postprocess = get_api_image_size(
                task["model_id"], task["resolution"]
            )
            tools, actual_image_search_enabled, grounding_notes = build_grounding_tool(
                model_id=task["model_id"],
                enable_google_search=task["enable_google_search"],
                enable_image_search=task["enable_image_search"],
            )
            actual_google_search_enabled = bool(tools)
            grounding_summary = summarize_grounding_mode(
                actual_google_search_enabled, actual_image_search_enabled
            )
            effective_prompt = build_effective_prompt(
                prompt=prompt,
                needs_ratio_postprocess=needs_ratio_postprocess,
                aspect_ratio=task["aspect_ratio"],
            )
        except Exception as exc:
            last_error = str(exc) if isinstance(exc, ValueError) else map_error_message(exc)
            rows[row_position][1] = "失败"
            rows[row_position][5] = last_error
            yield (
                gr.update(value=gallery_items),
                clone_batch_rows(rows),
                gr.update(value=[str(path) for path in saved_primary_paths], visible=bool(saved_primary_paths)),
                gr.update(value=None, visible=False),
                f"第 {prompt_index} 行任务准备失败，已继续处理后续任务。",
                folder_markdown,
                gr.update(),
            )
            continue

        for image_index in range(1, per_prompt_count + 1):
            global_image_index += 1
            image_seed = base_seed + image_index - 1
            progress(
                global_image_index / max(1, total_requested),
                desc=f"批量生图：第 {task_order}/{len(tasks)} 行，图片 {image_index}/{per_prompt_count}",
            )
            request_start = perf_counter()
            try:
                if is_apiyi_openai_image_model(task["model_id"]):
                    image = generate_apiyi_openai_image(
                        api_key=api_key,
                        proxy_url=proxy_url,
                        api_base_url=api_base_url,
                        model_id=task["model_id"],
                        prompt=effective_prompt,
                        reference_paths=task["reference_paths"],
                        resolution=task["resolution"],
                        api_aspect_ratio=api_aspect_ratio,
                    )
                else:
                    config_kwargs: dict[str, Any] = {
                        "response_modalities": ["Image"],
                        "seed": image_seed,
                        "candidate_count": 1,
                        "http_options": make_request_http_options(api_base_url),
                    }
                    if tools:
                        config_kwargs["tools"] = tools
                    if api_aspect_ratio:
                        config_kwargs["image_config"] = types.ImageConfig(
                            aspect_ratio=api_aspect_ratio,
                            image_size=api_image_size,
                        )
                    else:
                        config_kwargs["image_config"] = types.ImageConfig(image_size=api_image_size)

                    response = client.models.generate_content(
                        model=task["model_id"],
                        contents=types.Content(
                            role="user",
                            parts=[types.Part.from_text(text=effective_prompt), *reference_parts],
                        ),
                        config=types.GenerateContentConfig(**config_kwargs),
                    )
                    image = extract_first_image(response)
                image = postprocess_image(
                    image=image,
                    requested_aspect_ratio=task["aspect_ratio"],
                    requested_resolution=task["resolution"],
                    needs_ratio_postprocess=needs_ratio_postprocess,
                    needs_resize_postprocess=needs_resize_postprocess,
                )
                primary_path, backup_path = save_batch_image_with_backup(
                    image=image,
                    prompt_index=prompt_index,
                    image_index=image_index,
                    prompt=prompt,
                    batch_root=batch_root,
                    backup_batch_root=backup_batch_root,
                )
                elapsed = perf_counter() - request_start
                caption = build_gallery_caption(
                    model_label=MODEL_LABELS.get(task["model_id"], task["model_id"]),
                    prompt=prompt,
                    seed=image_seed,
                    elapsed_seconds=elapsed,
                    aspect_ratio=task["aspect_ratio"],
                    resolution=task["resolution"],
                    grounding_summary=grounding_summary,
                )
                reference_summary = (
                    f"参考图：{len(task['reference_paths'])} 张"
                    if task["reference_paths"]
                    else "参考图：无（文生图）"
                )
                gallery_items.append(
                    (
                        str(primary_path),
                        f"第 {prompt_index} 行 / 图 {image_index}\n{caption}\n{reference_summary}",
                    )
                )
                saved_primary_paths.append(primary_path)
                saved_backup_paths.append(backup_path)
                prompt_success_count += 1
                rows[row_position][4] = f"{prompt_success_count}/{per_prompt_count}"
            except Exception as exc:
                last_error = map_error_message(exc)
                rows[row_position][5] = last_error
                break

        if prompt_success_count == per_prompt_count:
            rows[row_position][1] = "成功"
        elif prompt_success_count > 0:
            rows[row_position][1] = "部分成功"
        else:
            rows[row_position][1] = "失败"

        note_parts = []
        if task["prompt_source"] != "用户输入":
            note_parts.append("Prompt 使用默认图生图提示")
        if grounding_notes:
            note_parts.extend(grounding_notes)
        if note_parts and not rows[row_position][5]:
            rows[row_position][5] = "；".join(note_parts)
        elif last_error and grounding_notes:
            rows[row_position][5] = f"{last_error}；" + "；".join(grounding_notes)

        prompt_history_update = gr.update()
        if prompt_success_count > 0:
            prompt_history = add_prompt_history_entry(
                str(task["prompt"]),
                {
                    "model_id": task["model_id"],
                    "aspect_ratio": task["aspect_ratio"],
                    "resolution": task["resolution"],
                    "image_count": prompt_success_count,
                    "keep_seed": bool(task["keep_seed"]),
                    "seed": base_seed,
                    "enable_google_search": actual_google_search_enabled,
                    "enable_image_search": actual_image_search_enabled,
                },
            )
            prompt_history_update = gr.update(
                choices=build_prompt_history_choices(prompt_history),
                value=None,
            )

        yield (
            gr.update(value=gallery_items),
            clone_batch_rows(rows),
            gr.update(value=[str(path) for path in saved_primary_paths], visible=bool(saved_primary_paths)),
            gr.update(value=None, visible=False),
            f"已处理 {task_order}/{len(tasks)} 行任务。",
            folder_markdown,
            prompt_history_update,
        )

    total_elapsed = perf_counter() - batch_start
    manifest = build_batch_manifest(
        batch_name=final_batch_name,
        tasks=tasks,
        rows=rows,
        image_paths=saved_primary_paths,
        backup_paths=saved_backup_paths,
        zip_path=None,
        backup_zip_path=None,
    )
    write_json_file(batch_root / "batch_manifest.json", manifest)
    write_json_file(backup_batch_root / "batch_manifest.json", manifest)

    success_prompts = sum(1 for row in rows if row[1] == "成功")
    partial_prompts = sum(1 for row in rows if row[1] == "部分成功")
    failed_prompts = sum(1 for row in rows if row[1] == "失败")
    final_status = (
        f"批量完成：任务成功 **{success_prompts}** 行，部分成功 **{partial_prompts}** 行，"
        f"失败 **{failed_prompts}** 行；共生成 **{len(saved_primary_paths)}/{total_requested}** 张图，"
        f"耗时 **{total_elapsed:.1f} 秒**。\n\n"
        "每行使用自己的参考图、Prompt 和参数，详细记录已写入本批次目录的 `batch_manifest.json`。"
    )

    yield (
        gr.update(value=gallery_items),
        clone_batch_rows(rows),
        gr.update(value=[str(path) for path in saved_primary_paths], visible=bool(saved_primary_paths)),
        gr.update(value=None, visible=False),
        final_status,
        folder_markdown,
        gr.update(),
    )


# ── 图片编辑：局部重绘 / 放大 / 去背 / 水印 ────────────────────────────────

# 图片编辑仅使用 Gemini 原生图像模型（走 generate_content，支持参考图编辑）。
EDIT_MODEL_OPTIONS = [
    item for item in MODEL_OPTIONS if item.get("api_kind") != "apiyi_openai_image"
]
EDIT_MODEL_CHOICES = [(item["label"], item["value"]) for item in EDIT_MODEL_OPTIONS]
DEFAULT_EDIT_MODEL_ID = EDIT_MODEL_OPTIONS[0]["value"]

MAX_UPSCALE_LONGEST_SIDE = 8192

WATERMARK_POSITIONS = [
    "左上", "上中", "右上",
    "左中", "居中", "右中",
    "左下", "下中", "右下",
]

BACKGROUND_MODE_CHOICES = ["透明", "白色", "黑色", "绿幕"]
BACKGROUND_FILL_COLORS = {
    "白色": (255, 255, 255),
    "黑色": (0, 0, 0),
    "绿幕": (0, 177, 64),
}

WATERMARK_FONT_CANDIDATES = [
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
    "C:/Windows/Fonts/arial.ttf",
]


def extract_first_image_raw(response: Any) -> Image.Image:
    """从响应里提取首张图片，保留原始模式（用于去背时保留透明通道）。"""
    parts = getattr(response, "parts", None) or []
    for part in parts:
        inline_data = getattr(part, "inline_data", None)
        if not inline_data:
            continue
        try:
            image = part.as_image()
            if image is not None:
                return image
        except Exception:
            pass
        data = getattr(inline_data, "data", None)
        if data:
            image_bytes = data.encode("utf-8") if isinstance(data, str) else data
            return Image.open(BytesIO(image_bytes))
    raise RuntimeError(explain_empty_image_response(response))


def run_gemini_image_edit(
    api_key: str,
    proxy_url: str,
    api_base_url: str,
    model_id: str,
    prompt: str,
    image_paths: list[str],
    keep_alpha: bool = False,
) -> Image.Image:
    """统一的 Gemini 图像编辑调用：文本指令 + 参考图 → 返回一张图片。"""
    parts = [types.Part.from_text(text=prompt), *prepare_reference_parts(image_paths)]
    config_kwargs: dict[str, Any] = {
        "response_modalities": ["Image"],
        "candidate_count": 1,
        "http_options": make_request_http_options(api_base_url),
    }
    client = make_client(api_key, proxy_url, api_base_url)
    response = client.models.generate_content(
        model=model_id,
        contents=types.Content(role="user", parts=parts),
        config=types.GenerateContentConfig(**config_kwargs),
    )
    if keep_alpha:
        return extract_first_image_raw(response)
    return extract_first_image(response)


def save_single_edit_image(
    image: Image.Image,
    output_root: str,
    backup_root: str,
    tag: str,
) -> tuple[Path, Path]:
    """把单张编辑结果保存到 <日期>/edits/ 并同步备份。"""
    output_root_path, backup_root_path = ensure_storage_roots(output_root, backup_root)
    primary_dir = output_day_dir(output_root_path) / "edits"
    backup_dir = output_day_dir(backup_root_path) / "edits"
    primary_dir.mkdir(parents=True, exist_ok=True)
    backup_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"{datetime.now().strftime('%H%M%S_%f')[:-3]}_{safe_slug(tag) or 'edit'}.png"
    primary_path = primary_dir / file_name
    backup_path = backup_dir / file_name
    image.save(primary_path, format="PNG")
    shutil.copy2(primary_path, backup_path)
    return primary_path, backup_path


def build_edit_saved_note(primary_path: Path, backup_path: Path) -> str:
    """编辑结果保存位置说明。"""
    return (
        f"✅ 已保存：`{primary_path}`\n\n"
        f"📁 备份：`{backup_path}`"
    )


def load_watermark_font(size: int) -> Any:
    """加载支持中文的字体，失败时退回默认字体。"""
    size = max(8, int(size))
    for path in WATERMARK_FONT_CANDIDATES:
        try:
            if Path(path).exists():
                return ImageFont.truetype(path, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size)
    except Exception:
        return ImageFont.load_default()


def hex_to_rgb(value: str, default: tuple[int, int, int] = (255, 255, 255)) -> tuple[int, int, int]:
    """把 #rrggbb / rgba(...) 之类的颜色字符串解析成 RGB 元组。"""
    if not value:
        return default
    text = value.strip()
    if text.startswith("#"):
        text = text[1:]
        if len(text) == 3:
            text = "".join(ch * 2 for ch in text)
        if len(text) >= 6:
            try:
                return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
            except ValueError:
                return default
    match = re.findall(r"\d+", text)
    if len(match) >= 3:
        return (int(match[0]) % 256, int(match[1]) % 256, int(match[2]) % 256)
    return default


def compute_watermark_xy(
    position: str,
    canvas_size: tuple[int, int],
    text_size: tuple[int, int],
    margin: int,
) -> tuple[int, int]:
    """根据九宫格位置计算水印左上角坐标。"""
    canvas_w, canvas_h = canvas_size
    text_w, text_h = text_size
    if "左" in position:
        x = margin
    elif "右" in position:
        x = canvas_w - text_w - margin
    else:
        x = (canvas_w - text_w) // 2
    if "上" in position:
        y = margin
    elif "下" in position:
        y = canvas_h - text_h - margin
    else:
        y = (canvas_h - text_h) // 2
    return max(0, x), max(0, y)


def edit_noop(status: str) -> tuple[Any, Any, Any]:
    """图片编辑各标签页统一的失败返回（状态 + 结果图 + 下载按钮）。"""
    gr.Warning(status)
    return status, gr.update(), gr.update(visible=False)


def edit_inpaint_handler(
    editor_value: Any,
    instruction: str,
    model_id: str,
    api_key: str,
    proxy_url: str,
    api_base_url: str,
    output_root: str,
    backup_root: str,
    progress: gr.Progress = gr.Progress(track_tqdm=False),
) -> tuple[Any, Any, Any]:
    """局部重绘：在涂抹区域内按指令修改，其余保持不变。"""
    if not normalize_api_key(api_key):
        return edit_noop("请先在上方设置 API Key。")
    if not isinstance(editor_value, dict):
        return edit_noop("请先上传要编辑的图片。")
    background = editor_value.get("background")
    composite = editor_value.get("composite")
    if not background:
        return edit_noop("请先上传要编辑的图片。")
    if not (instruction or "").strip():
        return edit_noop("请填写修改要求。")

    image_paths = [background]
    has_mask = bool(composite) and composite != background
    if has_mask:
        image_paths.append(composite)
        prompt = (
            "参考图1是原图，参考图2用彩色笔迹标出了需要修改的区域。"
            "请只在被标记的区域内进行修改，被标记区域之外的内容"
            "（构图、光影、其它物体、背景）必须与原图严格保持一致，"
            "输出时不要保留任何彩色笔迹。\n\n"
            f"在标记区域内的修改要求：{instruction.strip()}"
        )
    else:
        prompt = (
            "请对这张图片做局部修改，尽量只改动与要求相关的区域，"
            "其余部分与原图保持一致。\n\n"
            f"修改要求：{instruction.strip()}"
        )

    try:
        progress(0.3, desc="重绘中...")
        image = run_gemini_image_edit(
            api_key, proxy_url, api_base_url, model_id, prompt, image_paths,
        )
        progress(0.9, desc="保存中...")
        primary_path, backup_path = save_single_edit_image(
            image, output_root, backup_root, "inpaint",
        )
    except Exception as exc:
        return edit_noop(map_error_message(exc))

    progress(1.0, desc="完成 ✓")
    return (
        build_edit_saved_note(primary_path, backup_path),
        gr.update(value=str(primary_path)),
        gr.update(value=str(primary_path), visible=True),
    )


def edit_upscale_handler(
    image_path: str | None,
    factor: str,
    target_longest: float | int | None,
    output_root: str,
    backup_root: str,
    progress: gr.Progress = gr.Progress(track_tqdm=False),
) -> tuple[Any, Any, Any]:
    """本地无损放大（LANCZOS），不消耗 API。"""
    if not image_path:
        return edit_noop("请先上传要放大的图片。")
    try:
        progress(0.3, desc="放大中...")
        image = Image.open(image_path)
        image = image.convert("RGBA") if image.mode in ("RGBA", "LA", "P") else image.convert("RGB")
        width, height = image.size
        if factor == "自定义最长边":
            longest = int(target_longest or 0)
            if longest <= 0:
                return edit_noop("请填写有效的目标最长边（像素）。")
            longest = min(longest, MAX_UPSCALE_LONGEST_SIDE)
            result = resize_longest_side(image, longest)
            desc = f"最长边 {longest}px"
        else:
            multiplier = 4 if factor == "4x" else 2
            new_longest = max(width, height) * multiplier
            if new_longest > MAX_UPSCALE_LONGEST_SIDE:
                scale = MAX_UPSCALE_LONGEST_SIDE / max(width, height)
                result = image.resize(
                    (max(1, int(width * scale)), max(1, int(height * scale))),
                    Image.LANCZOS,
                )
                desc = f"已限制在 {MAX_UPSCALE_LONGEST_SIDE}px 以内"
            else:
                result = image.resize((width * multiplier, height * multiplier), Image.LANCZOS)
                desc = f"{multiplier}x"
        progress(0.9, desc="保存中...")
        primary_path, backup_path = save_single_edit_image(
            result, output_root, backup_root, "upscale",
        )
    except Exception as exc:
        return edit_noop(f"放大失败：{exc}")

    progress(1.0, desc="完成 ✓")
    note = (
        f"✅ 放大完成（{desc}），{width}×{height} → {result.size[0]}×{result.size[1]}。\n\n"
        + build_edit_saved_note(primary_path, backup_path)
    )
    return (
        note,
        gr.update(value=str(primary_path)),
        gr.update(value=str(primary_path), visible=True),
    )


def edit_background_handler(
    image_path: str | None,
    background_mode: str,
    model_id: str,
    api_key: str,
    proxy_url: str,
    api_base_url: str,
    output_root: str,
    backup_root: str,
    progress: gr.Progress = gr.Progress(track_tqdm=False),
) -> tuple[Any, Any, Any]:
    """智能去背：调用 Gemini 抠出主体，按需要输出透明 / 纯色背景。"""
    if not normalize_api_key(api_key):
        return edit_noop("请先在上方设置 API Key。")
    if not image_path:
        return edit_noop("请先上传要去背的图片。")

    if background_mode == "透明":
        prompt = (
            "请精确抠出图片中的主体，移除背景，输出为背景完全透明的 PNG。"
            "保留主体边缘细节（如发丝），不要添加任何新的背景或阴影。"
        )
        keep_alpha = True
    else:
        color_name = background_mode
        prompt = (
            f"请精确抠出图片中的主体，移除原有背景，把背景替换为纯{color_name}背景。"
            "保留主体边缘细节，不要添加阴影或其它元素。"
        )
        keep_alpha = False

    try:
        progress(0.3, desc="去背中...")
        image = run_gemini_image_edit(
            api_key, proxy_url, api_base_url, model_id, prompt, [image_path],
            keep_alpha=keep_alpha,
        )
        if background_mode == "透明":
            image = image.convert("RGBA")
        else:
            fill = BACKGROUND_FILL_COLORS.get(background_mode, (255, 255, 255))
            if image.mode == "RGBA":
                canvas = Image.new("RGB", image.size, fill)
                canvas.paste(image, mask=image.split()[-1])
                image = canvas
            else:
                image = image.convert("RGB")
        progress(0.9, desc="保存中...")
        primary_path, backup_path = save_single_edit_image(
            image, output_root, backup_root, "cutout",
        )
    except Exception as exc:
        return edit_noop(map_error_message(exc))

    progress(1.0, desc="完成 ✓")
    tip = ""
    if background_mode == "透明":
        tip = "\n\n提示：透明背景依赖模型输出，如果结果仍带底色，可改用“白色/绿幕”背景再自行抠图。"
    return (
        build_edit_saved_note(primary_path, backup_path) + tip,
        gr.update(value=str(primary_path)),
        gr.update(value=str(primary_path), visible=True),
    )


def edit_watermark_handler(
    image_path: str | None,
    text: str,
    position: str,
    size_ratio: float,
    opacity: float,
    color: str,
    tiled: bool,
    output_root: str,
    backup_root: str,
) -> tuple[Any, Any, Any]:
    """本地批量水印，不消耗 API。"""
    if not image_path:
        return edit_noop("请先上传要加水印的图片。")
    if not (text or "").strip():
        return edit_noop("请填写水印文字。")
    try:
        base = Image.open(image_path).convert("RGBA")
        canvas_w, canvas_h = base.size
        overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        font_size = max(12, int(min(canvas_w, canvas_h) * float(size_ratio)))
        font = load_watermark_font(font_size)
        rgb = hex_to_rgb(color)
        alpha = max(0, min(255, int(float(opacity) * 255)))
        fill = (*rgb, alpha)
        clean_text = text.strip()
        bbox = draw.textbbox((0, 0), clean_text, font=font)
        text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        margin = max(6, int(min(canvas_w, canvas_h) * 0.03))
        if tiled:
            gap = max(font_size, int(min(canvas_w, canvas_h) * 0.06))
            step_x = text_w + gap
            step_y = text_h + gap
            for y in range(margin, canvas_h, step_y):
                for x in range(margin, canvas_w, step_x):
                    draw.text((x - bbox[0], y - bbox[1]), clean_text, font=font, fill=fill)
        else:
            x, y = compute_watermark_xy(position, base.size, (text_w, text_h), margin)
            draw.text((x - bbox[0], y - bbox[1]), clean_text, font=font, fill=fill)
        result = Image.alpha_composite(base, overlay).convert("RGB")
        primary_path, backup_path = save_single_edit_image(
            result, output_root, backup_root, "watermark",
        )
    except Exception as exc:
        return edit_noop(f"加水印失败：{exc}")

    return (
        build_edit_saved_note(primary_path, backup_path),
        gr.update(value=str(primary_path)),
        gr.update(value=str(primary_path), visible=True),
    )


def build_demo() -> gr.Blocks:
    """构建 Gradio 界面。"""
    ensure_base_dirs()
    initial_api_key = get_initial_api_key()
    initial_remember_api_key = get_initial_remember_api_key()
    initial_proxy = get_initial_proxy_url()
    initial_api_base_url = get_initial_api_base_url()
    initial_output_root = get_initial_output_root()
    initial_backup_root = get_initial_backup_root()
    conversations, initial_conversation_id = ensure_initial_conversations()
    initial_conversation = find_conversation(conversations, initial_conversation_id) or conversations[0]
    initial_output_root_path, initial_backup_root_path = ensure_storage_roots(
        initial_output_root, initial_backup_root
    )
    initial_view = get_conversation_view(
        initial_conversation, initial_output_root_path, initial_backup_root_path
    )
    initial_prompt_history_choices = build_prompt_history_choices(load_prompt_history())
    initial_model_choices = get_initial_model_choices()
    settings_open = not bool(initial_api_key)

    with gr.Blocks(title="Gemini 本地图像生成工具", fill_width=True) as demo:
        conversations_state = gr.State(conversations)
        current_conversation_id = gr.State(initial_conversation["id"])
        batch_visible_rows_state = gr.State(INITIAL_BATCH_ROWS)

        with gr.Column(elem_classes=["app-shell"]):
            with gr.Accordion("设置", open=settings_open, elem_classes=["settings-wrap"]):
                with gr.Row():
                    api_key_box = gr.Textbox(
                        label="API Key",
                        placeholder="请粘贴 Google 官方或 Gemini 中转站 API Key",
                        type="password",
                        value=initial_api_key,
                        scale=4,
                    )
                    api_base_url_box = gr.Textbox(
                        label="Gemini Base URL（可选）",
                        placeholder=f"留空=Google 官方；APIYI 示例：{DEFAULT_RELAY_BASE_URL}",
                        value=initial_api_base_url,
                        scale=4,
                    )
                    proxy_box = gr.Textbox(
                        label="代理（可选）",
                        placeholder="例如：http://127.0.0.1:7890 或 socks5://127.0.0.1:7890",
                        value=initial_proxy,
                        scale=2,
                    )
                with gr.Row():
                    output_root_box = gr.Textbox(
                        label="出图储存位置",
                        placeholder=str(DEFAULT_OUTPUT_ROOT),
                        value=initial_output_root,
                        scale=5,
                    )
                    choose_output_button = gr.Button("选择...", variant="secondary", scale=1)
                    backup_root_box = gr.Textbox(
                        label="备份目录",
                        placeholder=str(DEFAULT_BACKUP_ROOT),
                        value=initial_backup_root,
                        scale=5,
                    )
                    choose_backup_button = gr.Button("选择...", variant="secondary", scale=1)
                with gr.Row():
                    test_button = gr.Button("测试连接", variant="secondary", scale=1)
                    detect_models_button = gr.Button("检测可用模型", variant="secondary", scale=1)
                    save_button = gr.Button("保存设置", variant="secondary", scale=1)
                with gr.Row():
                    remember_api_key_checkbox = gr.Checkbox(
                        label="记住 API Key（保存到本机）",
                        value=initial_remember_api_key,
                    )
                    show_all_models_checkbox = gr.Checkbox(
                        label="检测时显示全部模型（含文本等非图像模型）",
                        value=False,
                    )
                detect_models_hint = gr.Markdown(
                    "填好 API Key（和中转站 Base URL）后点“检测可用模型”，程序会自动拉取"
                    "当前端点可用的模型并刷新下拉框——中转站上新后无需等更新，重新检测即可。",
                    elem_classes=["muted-note"],
                )
                api_hint = gr.Markdown(
                    build_api_hint_text(initial_api_key, initial_remember_api_key),
                    elem_classes=["muted-note"],
                )
                gr.Markdown(
                    "如果你在国内网络环境，浏览器插件代理通常不会自动传给 Python。可在这里填写本机 HTTP/SOCKS5 代理地址。",
                    elem_classes=["muted-note"],
                )
                gr.Markdown(
                    f"当前默认留空表示走 Google 官方 Gemini 端点；如果使用 APIYI 这类 Gemini 原生中转，请填写根域名，例如 `{DEFAULT_RELAY_BASE_URL}`。",
                    elem_classes=["muted-note"],
                )

            page_selector = gr.Radio(
                label="工作模式",
                choices=["创作工作台", "图片编辑"],
                value="创作工作台",
                visible=True,
                elem_classes=["page-switcher"],
            )

            with gr.Row(visible=True, elem_classes=["workspace-shell"]) as creative_page:
                with gr.Column(scale=4, min_width=720, elem_classes=["main-panel"]):
                    folder_markdown = gr.Markdown(initial_view[7], elem_classes=["folder-links"])

                    with gr.Column(elem_classes=["surface-card", "composer-card"]):
                        prompt_box = gr.Textbox(
                            label="本轮 Prompt",
                            lines=6,
                            placeholder="请输入本轮新指令，支持中文。示例：让主角换成红色风衣，保持原有构图与电影感光影。",
                            elem_classes=["prompt-box"],
                        )
                        gr.Markdown(
                            "直接描述这轮要改什么，最近一次使用的模型、比例、分辨率和种子策略会自动沿用。",
                            elem_classes=["muted-note"],
                        )
                        with gr.Accordion(
                            f"Prompt 历史（最近 {MAX_PROMPT_HISTORY} 条）",
                            open=False,
                            elem_classes=["sub-accordion"],
                        ):
                            prompt_history_dropdown = gr.Dropdown(
                                label="选择历史 Prompt",
                                choices=initial_prompt_history_choices,
                                value=None,
                            )
                            with gr.Row():
                                use_prompt_history_button = gr.Button(
                                    "填入 Prompt",
                                    variant="secondary",
                                    size="sm",
                                )
                                refresh_prompt_history_button = gr.Button(
                                    "刷新历史",
                                    variant="secondary",
                                    size="sm",
                                )

                        reference_image_paths_state = gr.State([])
                        reference_selected_index_state = gr.State(-1)
                        with gr.Accordion(
                            f"参考图（可选，最多 {MAX_REFERENCE_IMAGES} 张）",
                            open=False,
                            elem_classes=["sub-accordion"],
                        ):
                            gr.Markdown(
                                "支持粘贴、单张上传和批量上传。点击缩略图后可直接左移 / 右移，不再需要额外下拉框。",
                                elem_classes=["muted-note"],
                            )
                            reference_add_image = gr.Image(
                                label="新增参考图",
                                type="filepath",
                                sources=["upload", "clipboard"],
                                height=180,
                                buttons=["fullscreen"],
                            )
                            reference_batch_files = gr.File(
                                label="批量添加参考图",
                                file_count="multiple",
                                file_types=["image"],
                                type="filepath",
                                height=110,
                            )
                            reference_gallery = gr.Gallery(
                                label="参考图",
                                value=[],
                                interactive=False,
                                preview=True,
                                object_fit="contain",
                                height=220,
                                columns=5,
                                type="filepath",
                                file_types=["image"],
                                buttons=["fullscreen"],
                            )
                            with gr.Row():
                                reference_move_left_button = gr.Button("左移", variant="secondary", size="sm")
                                reference_move_right_button = gr.Button("右移", variant="secondary", size="sm")
                                reference_remove_button = gr.Button("移除选中", variant="secondary", size="sm")
                                reference_clear_button = gr.Button("清空参考图", variant="secondary", size="sm")
                            reference_hint = gr.Markdown(build_reference_gallery_hint([]), elem_classes=["muted-note"])
                            reference_selection_hint = gr.Markdown(
                                build_reference_selection_hint([], -1),
                                elem_classes=["muted-note"],
                            )

                        with gr.Row():
                            google_search_checkbox = gr.Checkbox(
                                label="Grounding with Google Search",
                                value=initial_view[14]["value"] if isinstance(initial_view[14], dict) else False,
                            )
                            image_search_checkbox = gr.Checkbox(
                                label="Image Search",
                                value=initial_view[15]["value"] if isinstance(initial_view[15], dict) else False,
                                interactive=initial_view[15]["interactive"] if isinstance(initial_view[15], dict) else False,
                            )
                        grounding_hint = gr.Markdown(initial_view[16], elem_classes=["muted-note"])

                        with gr.Row():
                            model_dropdown = gr.Dropdown(
                                label="模型",
                                choices=initial_model_choices,
                                value=initial_view[8],
                                allow_custom_value=True,
                            )
                            aspect_ratio_dropdown = gr.Dropdown(
                                label="宽高比",
                                choices=ASPECT_RATIO_CHOICES,
                                value=initial_view[9],
                            )
                            resolution_dropdown = gr.Dropdown(
                                label="分辨率",
                                choices=RESOLUTION_CHOICES,
                                value=initial_view[10],
                            )

                        with gr.Row():
                            image_count_slider = gr.Slider(
                                label="生成数量",
                                minimum=1,
                                maximum=MAX_GENERATE_IMAGES,
                                step=1,
                                value=initial_view[11],
                            )
                            keep_seed_checkbox = gr.Checkbox(
                                label="保持种子",
                                value=initial_view[12],
                            )
                            seed_number = gr.Number(
                                label="种子",
                                precision=0,
                                value=initial_view[13]["value"] if isinstance(initial_view[13], dict) else None,
                                interactive=initial_view[13]["interactive"] if isinstance(initial_view[13], dict) else False,
                            )

                        with gr.Row(elem_classes=["generate-row"]):
                            generate_button = gr.Button(
                                "开始生成",
                                variant="primary",
                                interactive=bool(initial_api_key),
                                scale=3,
                                elem_classes=["generate-button"],
                            )
                            cancel_button = gr.Button(
                                "取消",
                                variant="secondary",
                                scale=1,
                                elem_classes=["cancel-button"],
                            )

                    status_markdown = gr.Markdown(initial_view[6], elem_classes=["status-box"])

                    with gr.Column(elem_classes=["surface-card", "results-card"]):
                        result_gallery = gr.Gallery(
                            label="生成结果",
                            show_label=True,
                            columns=2,
                            preview=True,
                            object_fit="contain",
                            buttons=["download", "fullscreen"],
                            value=initial_view[4]["value"] if isinstance(initial_view[4], dict) else [],
                            height="auto",
                        )
                        with gr.Row():
                            download_files = gr.File(
                                label="下载本轮单图",
                                file_count="multiple",
                                value=initial_view[3]["value"] if isinstance(initial_view[3], dict) else None,
                                visible=initial_view[3]["visible"] if isinstance(initial_view[3], dict) else False,
                            )
                            download_all_button = gr.DownloadButton(
                                "下载本轮 ZIP",
                                value=initial_view[5]["value"] if isinstance(initial_view[5], dict) else None,
                                visible=initial_view[5]["visible"] if isinstance(initial_view[5], dict) else False,
                            )

            with gr.Column(visible=False, elem_classes=["edit-page"]) as edit_page:
                gr.Markdown(
                    "### 图片编辑\n\n"
                    "对已有图片做局部重绘、无损放大、智能去背和批量水印。"
                    "结果会保存到出图目录下的 `edits/` 子文件夹并自动备份。",
                    elem_classes=["hero-card"],
                )
                with gr.Tabs():
                    # —— 局部重绘 ——
                    with gr.Tab("局部重绘"):
                        with gr.Row():
                            with gr.Column(scale=3, min_width=420):
                                edit_inpaint_editor = gr.ImageEditor(
                                    label="上传图片，用画笔涂抹需要修改的区域（不涂则整体微调）",
                                    type="filepath",
                                    sources=["upload", "clipboard"],
                                    height=420,
                                )
                                edit_inpaint_prompt = gr.Textbox(
                                    label="修改要求",
                                    lines=3,
                                    placeholder="示例：把涂抹处的杯子换成透明玻璃杯，保持光影一致。",
                                )
                                edit_inpaint_model = gr.Dropdown(
                                    label="模型",
                                    choices=EDIT_MODEL_CHOICES,
                                    value=DEFAULT_EDIT_MODEL_ID,
                                )
                                edit_inpaint_button = gr.Button(
                                    "开始重绘", variant="primary",
                                    elem_classes=["generate-button"],
                                )
                            with gr.Column(scale=2, min_width=320):
                                edit_inpaint_result = gr.Image(
                                    label="重绘结果", type="filepath", interactive=False,
                                    height=420, buttons=["fullscreen"],
                                )
                                edit_inpaint_download = gr.DownloadButton(
                                    "下载结果", value=None, visible=False,
                                )
                                edit_inpaint_status = gr.Markdown(
                                    "涂抹越精确，改动越可控。", elem_classes=["status-box"],
                                )
                    # —— 放大 ——
                    with gr.Tab("放大"):
                        with gr.Row():
                            with gr.Column(scale=3, min_width=420):
                                edit_upscale_image = gr.Image(
                                    label="上传要放大的图片",
                                    type="filepath",
                                    sources=["upload", "clipboard"],
                                    height=360,
                                    buttons=["fullscreen"],
                                )
                                with gr.Row():
                                    edit_upscale_factor = gr.Radio(
                                        label="放大方式",
                                        choices=["2x", "4x", "自定义最长边"],
                                        value="2x",
                                    )
                                    edit_upscale_target = gr.Number(
                                        label="目标最长边(px)",
                                        value=4096, precision=0, minimum=1,
                                        maximum=MAX_UPSCALE_LONGEST_SIDE,
                                    )
                                edit_upscale_button = gr.Button(
                                    "开始放大", variant="primary",
                                    elem_classes=["generate-button"],
                                )
                                gr.Markdown(
                                    f"本地 LANCZOS 高质量放大，不消耗 API；最长边上限 {MAX_UPSCALE_LONGEST_SIDE}px。",
                                    elem_classes=["muted-note"],
                                )
                            with gr.Column(scale=2, min_width=320):
                                edit_upscale_result = gr.Image(
                                    label="放大结果", type="filepath", interactive=False,
                                    height=360, buttons=["fullscreen"],
                                )
                                edit_upscale_download = gr.DownloadButton(
                                    "下载结果", value=None, visible=False,
                                )
                                edit_upscale_status = gr.Markdown(
                                    "", elem_classes=["status-box"],
                                )
                    # —— 去背 ——
                    with gr.Tab("去背"):
                        with gr.Row():
                            with gr.Column(scale=3, min_width=420):
                                edit_bg_image = gr.Image(
                                    label="上传要去背的图片",
                                    type="filepath",
                                    sources=["upload", "clipboard"],
                                    height=360,
                                    buttons=["fullscreen"],
                                )
                                edit_bg_mode = gr.Radio(
                                    label="背景处理",
                                    choices=BACKGROUND_MODE_CHOICES,
                                    value="透明",
                                )
                                edit_bg_model = gr.Dropdown(
                                    label="模型",
                                    choices=EDIT_MODEL_CHOICES,
                                    value=DEFAULT_EDIT_MODEL_ID,
                                )
                                edit_bg_button = gr.Button(
                                    "开始去背", variant="primary",
                                    elem_classes=["generate-button"],
                                )
                                gr.Markdown(
                                    "由 Gemini 抠图。透明背景依赖模型输出，边缘要求高时可选“绿幕”后自行精修。",
                                    elem_classes=["muted-note"],
                                )
                            with gr.Column(scale=2, min_width=320):
                                edit_bg_result = gr.Image(
                                    label="去背结果", type="filepath", interactive=False,
                                    height=360, buttons=["fullscreen"],
                                )
                                edit_bg_download = gr.DownloadButton(
                                    "下载结果", value=None, visible=False,
                                )
                                edit_bg_status = gr.Markdown(
                                    "", elem_classes=["status-box"],
                                )
                    # —— 水印 ——
                    with gr.Tab("水印"):
                        with gr.Row():
                            with gr.Column(scale=3, min_width=420):
                                edit_wm_image = gr.Image(
                                    label="上传要加水印的图片",
                                    type="filepath",
                                    sources=["upload", "clipboard"],
                                    height=320,
                                    buttons=["fullscreen"],
                                )
                                edit_wm_text = gr.Textbox(
                                    label="水印文字",
                                    placeholder="例如：© 你的品牌 / @账号",
                                    value="© GeminiImageTool",
                                )
                                with gr.Row():
                                    edit_wm_position = gr.Dropdown(
                                        label="位置",
                                        choices=WATERMARK_POSITIONS,
                                        value="右下",
                                    )
                                    edit_wm_color = gr.ColorPicker(
                                        label="颜色", value="#ffffff",
                                    )
                                with gr.Row():
                                    edit_wm_size = gr.Slider(
                                        label="字号（相对短边比例）",
                                        minimum=0.02, maximum=0.2, step=0.005, value=0.05,
                                    )
                                    edit_wm_opacity = gr.Slider(
                                        label="不透明度",
                                        minimum=0.05, maximum=1.0, step=0.05, value=0.5,
                                    )
                                edit_wm_tiled = gr.Checkbox(
                                    label="平铺水印（铺满整图，防裁剪）", value=False,
                                )
                                edit_wm_button = gr.Button(
                                    "添加水印", variant="primary",
                                    elem_classes=["generate-button"],
                                )
                                gr.Markdown(
                                    "本地绘制，不消耗 API；平铺时忽略“位置”。",
                                    elem_classes=["muted-note"],
                                )
                            with gr.Column(scale=2, min_width=320):
                                edit_wm_result = gr.Image(
                                    label="水印结果", type="filepath", interactive=False,
                                    height=320, buttons=["fullscreen"],
                                )
                                edit_wm_download = gr.DownloadButton(
                                    "下载结果", value=None, visible=False,
                                )
                                edit_wm_status = gr.Markdown(
                                    "", elem_classes=["status-box"],
                                )

            with gr.Column(visible=False, elem_classes=["batch-page"]) as batch_page:
                gr.Markdown(
                    "### 批量生图\n\n按行建立图生图 / 文生图任务：每一行都有自己的参考图、Prompt 和参数设置。",
                    elem_classes=["hero-card"],
                )
                with gr.Row(elem_classes=["batch-toolbar"]):
                    add_batch_row_button = gr.Button("手动添加批次", variant="secondary", scale=1)
                    preview_batch_button = gr.Button("预览任务", variant="secondary", scale=1)
                    clear_batch_button = gr.Button("清空批量表", variant="secondary", scale=1)
                    batch_start_button = gr.Button(
                        "开始批量生成",
                        variant="primary",
                        interactive=bool(initial_api_key),
                        elem_classes=["generate-button"],
                        scale=2,
                    )
                batch_row_count_markdown = gr.Markdown(
                    build_batch_visible_rows_text(INITIAL_BATCH_ROWS),
                    elem_classes=["muted-note"],
                )
                gr.Markdown(
                    f"默认显示 {INITIAL_BATCH_ROWS} 个批次，可手动添加至 {MAX_BATCH_ROWS} 个；每个批次最多 {MAX_REFERENCE_IMAGES} 张参考图、最多 {MAX_GENERATE_IMAGES} 张输出。只填 Prompt 就是文生图，只上传参考图也会使用默认图生图提示。",
                    elem_classes=["muted-note"],
                )

                with gr.Row(elem_classes=["batch-toolbar"]):
                    with gr.Column(scale=3, min_width=420, elem_classes=["surface-card", "batch-default-card"]):
                        with gr.Accordion("统一 Prompt 补充（可选）", open=False, elem_classes=["sub-accordion"]):
                            batch_prompt_suffix_box = gr.Textbox(
                                label="追加到每个批次的统一要求",
                                lines=3,
                                placeholder="例如：统一做成高端电商主图，干净背景，产品清晰锐利，真实摄影质感。这里会追加到每一行任务后面。",
                            )
                            gr.Markdown(
                                "适合把所有图片都需要遵守的风格、品牌、光影、构图要求放在这里，不用每行重复粘贴。",
                                elem_classes=["muted-note"],
                            )
                    with gr.Column(
                        scale=3,
                        min_width=420,
                        elem_classes=["surface-card", "batch-default-card", "batch-sticky-actions"],
                    ):
                        with gr.Accordion("默认参数模板", open=False, elem_classes=["sub-accordion"]):
                            batch_default_model_dropdown = gr.Dropdown(
                                label="默认模型",
                                choices=initial_model_choices,
                                value=DEFAULT_PARAMS["model_id"],
                                allow_custom_value=True,
                            )
                            with gr.Row():
                                batch_default_aspect_ratio_dropdown = gr.Dropdown(
                                    label="默认宽高比",
                                    choices=ASPECT_RATIO_CHOICES,
                                    value=DEFAULT_PARAMS["aspect_ratio"],
                                )
                                batch_default_resolution_dropdown = gr.Dropdown(
                                    label="默认分辨率",
                                    choices=RESOLUTION_CHOICES,
                                    value=DEFAULT_PARAMS["resolution"],
                                )
                            batch_default_images_per_prompt_slider = gr.Slider(
                                label="默认每行出图数",
                                minimum=1,
                                maximum=MAX_GENERATE_IMAGES,
                                step=1,
                                value=1,
                            )
                            with gr.Row():
                                batch_default_google_search_checkbox = gr.Checkbox(
                                    label="默认启用 Google Search",
                                    value=False,
                                )
                                batch_default_image_search_checkbox = gr.Checkbox(
                                    label="默认启用 Image Search",
                                    value=False,
                                    interactive=False,
                                )
                            batch_default_grounding_hint = gr.Markdown(
                                build_grounding_hint(DEFAULT_PARAMS["model_id"], False),
                                elem_classes=["muted-note"],
                            )
                            apply_batch_defaults_button = gr.Button("应用到全部批次", variant="secondary")

                batch_row_inputs: list[Any] = []
                batch_row_clear_outputs: list[Any] = []
                batch_row_default_outputs: list[Any] = []
                batch_row_containers: list[Any] = []
                batch_row_reference_controls: list[tuple[Any, Any, Any, Any, Any]] = []
                batch_row_keep_seed_pairs: list[tuple[Any, Any]] = []
                batch_row_grounding_controls: list[tuple[Any, Any, Any, Any]] = []
                batch_row_model_dropdowns: list[Any] = []
                with gr.Column(elem_classes=["surface-card", "batch-table-card"]):
                    for row_index in range(1, MAX_BATCH_ROWS + 1):
                        with gr.Row(
                            visible=row_index <= INITIAL_BATCH_ROWS,
                            elem_classes=["batch-task-row"],
                        ) as batch_task_row:
                            batch_row_containers.append(batch_task_row)
                            with gr.Column(scale=2, min_width=220):
                                row_reference_paths_state = gr.State([])
                                row_reference_files = gr.File(
                                    label=f"{row_index}. 上传参考图",
                                    file_count="multiple",
                                    file_types=["image"],
                                    type="filepath",
                                    height=112,
                                )
                                row_reference_gallery = gr.Gallery(
                                    label="已添加参考图",
                                    value=[],
                                    visible=False,
                                    columns=5,
                                    preview=True,
                                    object_fit="cover",
                                    height=96,
                                    buttons=["fullscreen"],
                                )
                                row_reference_hint = gr.Markdown(
                                    build_batch_reference_hint([]),
                                    elem_classes=["muted-note"],
                                )
                                row_reference_clear_button = gr.Button(
                                    "清空本批次参考图",
                                    variant="secondary",
                                    size="sm",
                                )
                            with gr.Column(scale=3, min_width=320):
                                row_prompt_box = gr.Textbox(
                                    label=f"{row_index}. Prompt",
                                    lines=4,
                                    placeholder="例如：保持人物五官和服装，换成高级商业棚拍，干净背景，柔和布光。",
                                    elem_classes=["prompt-box"],
                                )
                            with gr.Column(scale=3, min_width=360, elem_classes=["batch-param-card"]):
                                with gr.Accordion(
                                    f"{row_index}. 各类参数设置",
                                    open=row_index == 1,
                                    elem_classes=["sub-accordion"],
                                ):
                                    row_model_dropdown = gr.Dropdown(
                                        label="模型",
                                        choices=initial_model_choices,
                                        value=DEFAULT_PARAMS["model_id"],
                                        allow_custom_value=True,
                                    )
                                    batch_row_model_dropdowns.append(row_model_dropdown)
                                    with gr.Row():
                                        row_aspect_ratio_dropdown = gr.Dropdown(
                                            label="宽高比",
                                            choices=ASPECT_RATIO_CHOICES,
                                            value=DEFAULT_PARAMS["aspect_ratio"],
                                        )
                                        row_resolution_dropdown = gr.Dropdown(
                                            label="分辨率",
                                            choices=RESOLUTION_CHOICES,
                                            value=DEFAULT_PARAMS["resolution"],
                                        )
                                    row_images_per_prompt_slider = gr.Slider(
                                        label="本行出图数",
                                        minimum=1,
                                        maximum=MAX_GENERATE_IMAGES,
                                        step=1,
                                        value=1,
                                    )
                                    with gr.Row():
                                        row_keep_seed_checkbox = gr.Checkbox(label="保持种子", value=False)
                                        row_seed_number = gr.Number(
                                            label="起始种子",
                                            precision=0,
                                            value=None,
                                            interactive=False,
                                        )
                                    with gr.Row():
                                        row_google_search_checkbox = gr.Checkbox(
                                            label="Grounding with Google Search",
                                            value=False,
                                        )
                                        row_image_search_checkbox = gr.Checkbox(
                                            label="Image Search",
                                            value=False,
                                            interactive=False,
                                        )
                                    row_grounding_hint = gr.Markdown(
                                        build_grounding_hint(DEFAULT_PARAMS["model_id"], False),
                                        elem_classes=["muted-note"],
                                    )

                            batch_row_inputs.extend(
                                [
                                    row_reference_paths_state,
                                    row_prompt_box,
                                    row_model_dropdown,
                                    row_google_search_checkbox,
                                    row_image_search_checkbox,
                                    row_aspect_ratio_dropdown,
                                    row_resolution_dropdown,
                                    row_images_per_prompt_slider,
                                    row_keep_seed_checkbox,
                                    row_seed_number,
                                ]
                            )
                            batch_row_clear_outputs.extend(
                                [
                                    row_reference_files,
                                    row_reference_gallery,
                                    row_reference_paths_state,
                                    row_reference_hint,
                                    row_prompt_box,
                                    row_model_dropdown,
                                    row_google_search_checkbox,
                                    row_image_search_checkbox,
                                    row_aspect_ratio_dropdown,
                                    row_resolution_dropdown,
                                    row_images_per_prompt_slider,
                                    row_keep_seed_checkbox,
                                    row_seed_number,
                                ]
                            )
                            batch_row_default_outputs.extend(
                                [
                                    row_model_dropdown,
                                    row_google_search_checkbox,
                                    row_image_search_checkbox,
                                    row_aspect_ratio_dropdown,
                                    row_resolution_dropdown,
                                    row_images_per_prompt_slider,
                                    row_grounding_hint,
                                ]
                            )
                            batch_row_reference_controls.append(
                                (
                                    row_reference_files,
                                    row_reference_gallery,
                                    row_reference_paths_state,
                                    row_reference_hint,
                                    row_reference_clear_button,
                                )
                            )
                            batch_row_keep_seed_pairs.append((row_keep_seed_checkbox, row_seed_number))
                            batch_row_grounding_controls.append(
                                (
                                    row_model_dropdown,
                                    row_google_search_checkbox,
                                    row_image_search_checkbox,
                                    row_grounding_hint,
                                )
                            )

                batch_status_markdown = gr.Markdown(
                    "批量任务还未开始。建议先填 1-2 行小批量试跑，确认模型和风格后再跑满 10 行。",
                    elem_classes=["status-box"],
                )
                batch_folder_markdown = gr.Markdown("", elem_classes=["folder-links"])
                batch_status_table = gr.Dataframe(
                    headers=["行", "状态", "参考图", "Prompt", "已生成", "说明"],
                    datatype=["number", "str", "str", "str", "str", "str"],
                    value=[],
                    label="批量队列",
                    interactive=False,
                    wrap=True,
                    max_height=360,
                )
                batch_result_gallery = gr.Gallery(
                    label="批量结果",
                    value=[],
                    columns=3,
                    preview=True,
                    object_fit="contain",
                    buttons=["download", "fullscreen"],
                    height="auto",
                )
                with gr.Row():
                    batch_download_files = gr.File(
                        label="下载本批次单图",
                        file_count="multiple",
                        visible=False,
                    )
                    batch_download_all_button = gr.DownloadButton(
                        "下载本批次 ZIP",
                        value=None,
                        visible=False,
                    )

        page_switch_event = page_selector.change(
            fn=switch_workspace_page,
            inputs=page_selector,
            outputs=[creative_page, edit_page, batch_page],
            queue=False,
            show_progress="hidden",
        )
        page_switch_event.then(
            fn=None,
            js=PAGE_SWITCH_SCROLL_JS,
            queue=False,
            show_progress="hidden",
        )
        api_key_box.input(
            fn=update_generation_buttons_ui,
            inputs=[api_key_box, remember_api_key_checkbox, prompt_box],
            outputs=[generate_button, batch_start_button, api_hint],
        )
        remember_api_key_checkbox.change(
            fn=update_generation_buttons_ui,
            inputs=[api_key_box, remember_api_key_checkbox, prompt_box],
            outputs=[generate_button, batch_start_button, api_hint],
        )
        prompt_box.input(
            fn=lambda prompt, api_key: get_creative_generate_button_update(api_key, prompt),
            inputs=[prompt_box, api_key_box],
            outputs=generate_button,
        )
        use_prompt_history_button.click(
            fn=use_prompt_history_handler,
            inputs=[prompt_history_dropdown, api_key_box],
            outputs=[prompt_box, generate_button],
        )
        refresh_prompt_history_button.click(
            fn=refresh_prompt_history_handler,
            outputs=prompt_history_dropdown,
        )
        save_button.click(
            fn=save_settings_for_all_pages_handler,
            inputs=[
                api_key_box,
                proxy_box,
                api_base_url_box,
                output_root_box,
                backup_root_box,
                remember_api_key_checkbox,
                prompt_box,
            ],
            outputs=[generate_button, batch_start_button, api_hint],
        )
        choose_output_button.click(
            fn=choose_output_dir_handler,
            inputs=output_root_box,
            outputs=output_root_box,
        )
        choose_backup_button.click(
            fn=choose_backup_dir_handler,
            inputs=backup_root_box,
            outputs=backup_root_box,
        )
        test_button.click(
            fn=test_connection_handler,
            inputs=[api_key_box, proxy_box, api_base_url_box],
            outputs=status_markdown,
        )
        detect_models_button.click(
            fn=detect_models_handler,
            inputs=[
                api_key_box,
                proxy_box,
                api_base_url_box,
                show_all_models_checkbox,
                model_dropdown,
            ],
            outputs=[
                detect_models_hint,
                model_dropdown,
                batch_default_model_dropdown,
                *batch_row_model_dropdowns,
            ],
        )
        keep_seed_checkbox.change(
            fn=lambda keep_seed: gr.update(interactive=bool(keep_seed)),
            inputs=keep_seed_checkbox,
            outputs=seed_number,
        )
        model_dropdown.change(
            fn=refresh_grounding_controls,
            inputs=[model_dropdown, google_search_checkbox, image_search_checkbox],
            outputs=[image_search_checkbox, grounding_hint],
        )
        google_search_checkbox.change(
            fn=refresh_grounding_controls,
            inputs=[model_dropdown, google_search_checkbox, image_search_checkbox],
            outputs=[image_search_checkbox, grounding_hint],
        )
        batch_default_model_dropdown.change(
            fn=refresh_grounding_controls,
            inputs=[
                batch_default_model_dropdown,
                batch_default_google_search_checkbox,
                batch_default_image_search_checkbox,
            ],
            outputs=[batch_default_image_search_checkbox, batch_default_grounding_hint],
        )
        batch_default_google_search_checkbox.change(
            fn=refresh_grounding_controls,
            inputs=[
                batch_default_model_dropdown,
                batch_default_google_search_checkbox,
                batch_default_image_search_checkbox,
            ],
            outputs=[batch_default_image_search_checkbox, batch_default_grounding_hint],
        )
        apply_batch_defaults_button.click(
            fn=apply_batch_defaults_handler,
            inputs=[
                batch_default_model_dropdown,
                batch_default_google_search_checkbox,
                batch_default_image_search_checkbox,
                batch_default_aspect_ratio_dropdown,
                batch_default_resolution_dropdown,
                batch_default_images_per_prompt_slider,
            ],
            outputs=batch_row_default_outputs,
        )
        preview_batch_button.click(
            fn=preview_batch_tasks_handler,
            inputs=[
                batch_prompt_suffix_box,
                *batch_row_inputs,
            ],
            outputs=[batch_status_table, batch_status_markdown],
        )
        add_batch_row_button.click(
            fn=add_batch_row_handler,
            inputs=batch_visible_rows_state,
            outputs=[
                batch_visible_rows_state,
                *batch_row_containers,
                batch_row_count_markdown,
            ],
        )
        clear_batch_button.click(
            fn=clear_batch_table_handler,
            outputs=[
                batch_prompt_suffix_box,
                *batch_row_clear_outputs,
                batch_visible_rows_state,
                *batch_row_containers,
                batch_row_count_markdown,
                batch_status_table,
                batch_status_markdown,
                batch_folder_markdown,
                batch_result_gallery,
                batch_download_files,
                batch_download_all_button,
            ],
        )
        for (
            row_reference_files,
            row_reference_gallery,
            row_reference_paths_state,
            row_reference_hint,
            row_reference_clear_button,
        ) in batch_row_reference_controls:
            row_reference_files.change(
                fn=append_batch_reference_images_handler,
                inputs=[row_reference_files, row_reference_paths_state],
                outputs=[
                    row_reference_files,
                    row_reference_gallery,
                    row_reference_paths_state,
                    row_reference_hint,
                ],
            )
            row_reference_clear_button.click(
                fn=clear_batch_reference_images_handler,
                outputs=[
                    row_reference_files,
                    row_reference_gallery,
                    row_reference_paths_state,
                    row_reference_hint,
                ],
            )
        for seed_checkbox, seed_number_input in batch_row_keep_seed_pairs:
            seed_checkbox.change(
                fn=lambda keep_seed: gr.update(interactive=bool(keep_seed)),
                inputs=seed_checkbox,
                outputs=seed_number_input,
            )
        for row_model_dropdown, row_google_search_checkbox, row_image_search_checkbox, row_grounding_hint in (
            batch_row_grounding_controls
        ):
            row_model_dropdown.change(
                fn=refresh_grounding_controls,
                inputs=[row_model_dropdown, row_google_search_checkbox, row_image_search_checkbox],
                outputs=[row_image_search_checkbox, row_grounding_hint],
            )
            row_google_search_checkbox.change(
                fn=refresh_grounding_controls,
                inputs=[row_model_dropdown, row_google_search_checkbox, row_image_search_checkbox],
                outputs=[row_image_search_checkbox, row_grounding_hint],
            )
        reference_add_image.change(
            fn=append_reference_image_handler,
            inputs=[reference_add_image, reference_image_paths_state],
            outputs=[
                reference_add_image,
                reference_gallery,
                reference_image_paths_state,
                reference_hint,
                reference_selection_hint,
                reference_selected_index_state,
            ],
        )
        reference_batch_files.change(
            fn=append_reference_images_handler,
            inputs=[reference_batch_files, reference_image_paths_state],
            outputs=[
                reference_batch_files,
                reference_gallery,
                reference_image_paths_state,
                reference_hint,
                reference_selection_hint,
                reference_selected_index_state,
            ],
        )
        reference_gallery.select(
            fn=select_reference_image_handler,
            inputs=[reference_image_paths_state],
            outputs=[
                reference_gallery,
                reference_selection_hint,
                reference_selected_index_state,
            ],
        )
        reference_move_left_button.click(
            fn=lambda paths, selected_index: move_reference_image_handler(paths, selected_index, -1),
            inputs=[reference_image_paths_state, reference_selected_index_state],
            outputs=[
                reference_gallery,
                reference_image_paths_state,
                reference_hint,
                reference_selection_hint,
                reference_selected_index_state,
            ],
        )
        reference_move_right_button.click(
            fn=lambda paths, selected_index: move_reference_image_handler(paths, selected_index, 1),
            inputs=[reference_image_paths_state, reference_selected_index_state],
            outputs=[
                reference_gallery,
                reference_image_paths_state,
                reference_hint,
                reference_selection_hint,
                reference_selected_index_state,
            ],
        )
        reference_remove_button.click(
            fn=remove_selected_reference_image_handler,
            inputs=[reference_image_paths_state, reference_selected_index_state],
            outputs=[
                reference_gallery,
                reference_image_paths_state,
                reference_hint,
                reference_selection_hint,
                reference_selected_index_state,
            ],
        )
        reference_clear_button.click(
            fn=clear_reference_gallery_handler,
            outputs=[
                reference_gallery,
                reference_image_paths_state,
                reference_hint,
                reference_selection_hint,
                reference_selected_index_state,
            ],
        )
        _gen_event = generate_button.click(
            fn=generate_or_unlock_batch_handler,
            inputs=[
                api_key_box,
                proxy_box,
                api_base_url_box,
                output_root_box,
                backup_root_box,
                current_conversation_id,
                conversations_state,
                prompt_box,
                model_dropdown,
                google_search_checkbox,
                image_search_checkbox,
                reference_image_paths_state,
                aspect_ratio_dropdown,
                resolution_dropdown,
                image_count_slider,
                keep_seed_checkbox,
                seed_number,
            ],
            outputs=[
                prompt_box,
                prompt_history_dropdown,
                result_gallery,
                download_files,
                download_all_button,
                status_markdown,
                folder_markdown,
                conversations_state,
                current_conversation_id,
                page_selector,
                creative_page,
                edit_page,
                batch_page,
            ],
        )
        cancel_button.click(fn=None, cancels=[_gen_event])
        batch_start_button.click(
            fn=batch_generate_handler,
            inputs=[
                api_key_box,
                proxy_box,
                api_base_url_box,
                output_root_box,
                backup_root_box,
                batch_prompt_suffix_box,
                *batch_row_inputs,
            ],
            outputs=[
                batch_result_gallery,
                batch_status_table,
                batch_download_files,
                batch_download_all_button,
                batch_status_markdown,
                batch_folder_markdown,
                prompt_history_dropdown,
            ],
        )

        # —— 图片编辑：四个标签页的按钮事件 ——
        edit_inpaint_button.click(
            fn=edit_inpaint_handler,
            inputs=[
                edit_inpaint_editor,
                edit_inpaint_prompt,
                edit_inpaint_model,
                api_key_box,
                proxy_box,
                api_base_url_box,
                output_root_box,
                backup_root_box,
            ],
            outputs=[edit_inpaint_status, edit_inpaint_result, edit_inpaint_download],
        )
        edit_upscale_button.click(
            fn=edit_upscale_handler,
            inputs=[
                edit_upscale_image,
                edit_upscale_factor,
                edit_upscale_target,
                output_root_box,
                backup_root_box,
            ],
            outputs=[edit_upscale_status, edit_upscale_result, edit_upscale_download],
        )
        edit_bg_button.click(
            fn=edit_background_handler,
            inputs=[
                edit_bg_image,
                edit_bg_mode,
                edit_bg_model,
                api_key_box,
                proxy_box,
                api_base_url_box,
                output_root_box,
                backup_root_box,
            ],
            outputs=[edit_bg_status, edit_bg_result, edit_bg_download],
        )
        edit_wm_button.click(
            fn=edit_watermark_handler,
            inputs=[
                edit_wm_image,
                edit_wm_text,
                edit_wm_position,
                edit_wm_size,
                edit_wm_opacity,
                edit_wm_color,
                edit_wm_tiled,
                output_root_box,
                backup_root_box,
            ],
            outputs=[edit_wm_status, edit_wm_result, edit_wm_download],
        )

    return demo


def open_browser_after_delay(url: str, delay_seconds: float = 2.0) -> None:
    """延迟打开浏览器，避免服务未就绪时打开空白页。"""
    timer = threading.Timer(delay_seconds, lambda: webbrowser.open(url))
    timer.daemon = True
    timer.start()


def is_port_available(port: int) -> bool:
    """检测本机端口是否可用。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def resolve_server_port(default_port: int = 7860) -> int:
    """优先使用默认端口；若被占用，则自动回退到下一个可用端口。"""
    env_port = os.getenv("GRADIO_SERVER_PORT", "").strip()
    try:
        preferred_port = int(env_port) if env_port else default_port
    except ValueError:
        preferred_port = default_port

    for candidate in range(preferred_port, preferred_port + 20):
        if is_port_available(candidate):
            if candidate != preferred_port:
                print(f"[启动提示] 端口 {preferred_port} 已占用，已自动切换到 {candidate}。")
            return candidate

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        fallback_port = int(sock.getsockname()[1])
    print(f"[启动提示] 常用端口已占满，已自动切换到 {fallback_port}。")
    return fallback_port


def launch_app(auto_open_browser: bool = False) -> None:
    """统一启动入口，兼容源码运行与 EXE 运行。"""
    # 某些代理环境会错误转发 127.0.0.1，自检时显式排除本地回环。
    os.environ["NO_PROXY"] = "127.0.0.1,localhost"
    os.environ["no_proxy"] = "127.0.0.1,localhost"
    server_port = resolve_server_port()
    app_url = f"http://127.0.0.1:{server_port}"
    if auto_open_browser:
        open_browser_after_delay(app_url)

    demo = build_demo()
    demo.launch(
        server_name="127.0.0.1",
        server_port=server_port,
        allowed_paths=build_allowed_launch_paths(),
        css=APP_CSS,
    )


if __name__ == "__main__":
    launch_app(auto_open_browser=True)
