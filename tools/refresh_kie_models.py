#!/usr/bin/env python3
"""从 kie.ai 文档生成图像模型参数表（kie_models.py）。

kie.ai 没有列出模型的接口，各模型的参数名又不统一（参考图字段有
image_input / input_urls / image_urls / image_url 等多种写法，分辨率有的叫
resolution 有的叫 image_size，还有的完全没有）。文档页提供机器可读的
OpenAPI 定义，这里批量解析出来生成一张表，供程序按模型取用。

kie.ai 上新模型后重新跑一次即可：
    python3 tools/refresh_kie_models.py            # 从网络抓取
    python3 tools/refresh_kie_models.py <目录>      # 用已下载的 .md 目录
"""
from __future__ import annotations

import pprint
import re
import sys
from pathlib import Path

import yaml

DOCS_BASE = "https://docs.kie.ai"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "kie_models.py"
LINKS_PATH = Path(__file__).resolve().parent / "kie_image_pages.txt"

# 参考图字段的候选名，按文档里出现过的写法列举。
IMAGE_FIELD_HINTS = ("image_url", "image_urls", "image_input", "input_urls",
                     "input_image_urls", "images", "image", "reference_image_urls",
                     "urls", "file_url", "image_urls_list")
# 部分模型用预设词而不是比例字符串表示画幅。
ASPECT_PRESET_TO_RATIO = {
    "square": "1:1", "square_hd": "1:1",
    "portrait_4_3": "3:4", "landscape_4_3": "4:3",
    "portrait_3_2": "2:3", "landscape_3_2": "3:2",
    "portrait_16_9": "9:16", "landscape_16_9": "16:9",
}


def load_spec(text: str) -> dict | None:
    match = re.search(r"```yaml\n(.*?)\n```", text, re.S)
    if not match:
        return None
    try:
        return yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None


def parse_page(text: str) -> dict | None:
    spec = load_spec(text)
    if not spec:
        return None
    schemas = (spec.get("components") or {}).get("schemas") or {}

    def resolve(node):
        seen = 0
        while isinstance(node, dict) and "$ref" in node and seen < 5:
            node = schemas.get(node["$ref"].split("/")[-1], {})
            seen += 1
        return node if isinstance(node, dict) else {}

    for path, methods in (spec.get("paths") or {}).items():
        if "createTask" not in path:
            continue
        body = (((methods.get("post") or {}).get("requestBody") or {})
                .get("content", {}).get("application/json", {}).get("schema"))
        props = resolve(body).get("properties") or {}
        model_field = resolve(props.get("model") or {})
        model_ids = model_field.get("enum") or ([model_field["default"]] if model_field.get("default") else [])
        if not model_ids:
            continue
        input_props = {k: resolve(v) for k, v in (resolve(props.get("input") or {}).get("properties") or {}).items()}

        image_field = None
        image_is_list = False
        max_references = 0
        for name in IMAGE_FIELD_HINTS:
            if name in input_props:
                field = input_props[name]
                image_field = name
                image_is_list = field.get("type") == "array"
                max_references = int(field.get("maxItems") or (10 if image_is_list else 1))
                break

        # 按取值判断字段用途，不能只看名字：image_size 在不同模型下
        # 可能是分辨率（1K/2K）、宽高比（16:9）或预设词（landscape_4_3）。
        resolution_field = aspect_field = None
        resolutions: list[str] = []
        aspects: list[str] = []
        aspect_style = None
        for name, field in input_props.items():
            values = [str(v) for v in (field.get("enum") or [])]
            # auto 是通用值，不参与判断，但始终可用。
            values = [v for v in values if v.lower() != "auto"]
            if not values:
                continue
            if resolution_field is None and all(re.fullmatch(r"\d+K", v) for v in values):
                resolution_field, resolutions = name, values
            elif aspect_field is None and all(":" in v for v in values):
                aspect_field, aspects, aspect_style = name, values, "ratio"
            elif aspect_field is None and all(
                v in ASPECT_PRESET_TO_RATIO for v in values
            ):
                aspect_field, aspects, aspect_style = name, values, "preset"

        title = (re.search(r"^#\s+(.+)$", text, re.M) or [None, model_ids[0]])[1]
        return {
            "model_id": str(model_ids[0]),
            "label": str(title).strip(),
            "image_field": image_field,
            "image_is_list": image_is_list,
            "max_references": max_references,
            "resolution_field": resolution_field,
            "resolutions": resolutions,
            "aspect_field": aspect_field,
            "aspects": aspects,
            "aspect_style": aspect_style,
            "supports_prompt": "prompt" in input_props,
        }
    return None


def main() -> int:
    pages = [line.strip() for line in LINKS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    cache_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    entries: dict[str, dict] = {}
    skipped: list[str] = []

    for page in pages:
        if cache_dir:
            candidate = cache_dir / (page.replace("/", "_") + ".md")
            text = candidate.read_text(encoding="utf-8") if candidate.exists() else ""
        else:
            import httpx
            text = httpx.get(f"{DOCS_BASE}{page}.md", timeout=30).text
        parsed = parse_page(text) if text else None
        if not parsed:
            skipped.append(page)
            continue
        entries[parsed.pop("model_id")] = parsed

    body = pprint.pformat(entries, width=110, sort_dicts=True)
    OUTPUT_PATH.write_text(
        '"""kie.ai 图像模型参数表——由 tools/refresh_kie_models.py 自动生成，请勿手改。\n\n'
        "各模型的参考图字段名、分辨率字段名与取值都不一致，这里按官方文档逐个登记。\n"
        f'共 {len(entries)} 个模型。\n"""\n\n'
        f"KIE_IMAGE_MODELS = {body}\n",
        encoding="utf-8",
    )
    print(f"已生成 {OUTPUT_PATH.name}：{len(entries)} 个模型")
    if skipped:
        print(f"跳过 {len(skipped)} 个页面（没解析出 createTask 定义）：")
        for page in skipped:
            print("   ", page)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
