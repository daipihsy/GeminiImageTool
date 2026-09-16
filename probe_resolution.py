#!/usr/bin/env python3
"""探测中转站对各分辨率档位的真实支持情况。

只依赖标准库 + Pillow，不需要装 gradio。
尺寸计算直接从 app.py 里抽取，测的就是应用实际会发出的请求。

用法（运行时会提示输入 key 和地址，不写进 shell 历史）：
    python3 probe_resolution.py                 # 先列出可用的图像模型
    python3 probe_resolution.py <模型名>         # 探测该模型（默认只测 2K，计费 1 张）
    python3 probe_resolution.py <模型名> 1K 2K 4K  # 指定要测的档位
"""
import ast, base64, getpass, json, os, re, ssl, sys, urllib.request, urllib.error
from io import BytesIO
from PIL import Image

# python.org 版 Python 常缺根证书；有 certifi 就用，没有就退回系统钥匙串。
try:
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CTX = ssl.create_default_context()
    if not SSL_CTX.get_ca_certs():
        try:
            SSL_CTX.load_verify_locations("/etc/ssl/cert.pem")  # macOS 自带
        except OSError:
            pass

# key 优先用交互输入，避免留在 shell 历史里；环境变量仅作为自动化时的备选。
KEY = os.environ.get("RELAY_KEY", "").strip()
if not KEY:
    KEY = getpass.getpass("中转站 API Key（输入时不显示）：").strip()
BASE = os.environ.get("RELAY_BASE", "").strip().rstrip("/")
if not BASE:
    BASE = input("中转站地址 [https://api.openai.com]：").strip().rstrip("/") or "https://api.openai.com"
RATIO = os.environ.get("RELAY_RATIO", "16:9").strip()
if not KEY:
    sys.exit("没有输入 API Key，已退出。")
if not BASE.startswith("https://"):
    sys.exit("RELAY_BASE 必须是 https:// 开头的根地址")
if not BASE.endswith("/v1"):
    BASE += "/v1"

# ── 从 app.py 抽出真实的尺寸计算逻辑 ──────────────────────────────
_src = ast.parse(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py"), encoding="utf-8").read())
_want_fn = {"compute_size_for_resolution", "resolve_openai_image_size",
            "official_openai_size", "size_to_longest_side"}
_want_const = {"LONGEST_SIDE_BY_RESOLUTION", "GPT_IMAGE_2_VIP_SIZES"}
_ns = {"re": re}
exec(compile(ast.Module(body=[n for n in _src.body
    if (isinstance(n, ast.FunctionDef) and n.name in _want_fn)
    or (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in _want_const for t in n.targets))],
    type_ignores=[]), "app.py", "exec"), _ns)
resolve_size = _ns["resolve_openai_image_size"]


def call(path, payload=None):
    url = f"{BASE}{path}"
    headers = {"Authorization": f"Bearer {KEY}"}
    if payload is None:
        req = urllib.request.Request(url, headers=headers)
    else:
        headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=300, context=SSL_CTX) as resp:
            return json.loads(resp.read().decode()), None
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:400]
        return None, f"HTTP {e.code}: {body}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def load_image(item):
    if item.get("b64_json"):
        return Image.open(BytesIO(base64.b64decode(item["b64_json"])))
    if item.get("url"):
        with urllib.request.urlopen(item["url"], timeout=120, context=SSL_CTX) as r:
            return Image.open(BytesIO(r.read()))
    raise ValueError("返回里既没有 b64_json 也没有 url")


args = [a for a in sys.argv[1:] if a]
if not args:
    data, err = call("/models")
    if err:
        sys.exit(f"取模型列表失败：{err}")
    kw = ("image", "imagen", "banana", "dall", "flux", "seedream", "gpt-image", "grok-2-image", "ideogram")
    ids = sorted({m.get("id", "") for m in data.get("data", []) if isinstance(m, dict)})
    hits = [i for i in ids if any(k in i.lower() for k in kw)]
    print(f"共 {len(ids)} 个模型，其中像图像模型的 {len(hits)} 个：\n")
    for i in hits:
        print("   ", i)
    print("\n然后：python3 probe_resolution.py <上面某个模型名>")
    sys.exit(0)

model = args[0]
tiers = args[1:] or ["2K"]
print(f"模型：{model}")
print(f"端点：{BASE}")
print(f"比例：{RATIO}    档位：{', '.join(tiers)}")
print(f"⚠️  将实际生成 {len(tiers)} 张图，会计费。Ctrl+C 可中止。\n")

print(f"{'档位':<6}{'请求尺寸':>12}{'实际返回':>12}   结论")
print("-" * 62)
for tier in tiers:
    size = resolve_size(model, tier, RATIO)
    payload = {"model": model, "prompt": "a plain gray square, flat color, no detail",
               "n": 1, "size": size}
    if size == "auto":
        payload.pop("size")
    data, err = call("/images/generations", payload)
    if err:
        verdict = "❌ 被拒绝" if "size" in err.lower() or "尺寸" in err else "❌ 请求失败"
        print(f"{tier:<6}{size:>12}{'—':>12}   {verdict}")
        print(f"       └─ {err.splitlines()[0][:160]}")
        continue
    try:
        img = load_image(data["data"][0])
    except Exception as e:
        print(f"{tier:<6}{size:>12}{'—':>12}   ❌ 取图失败：{e}")
        continue
    got = f"{img.size[0]}x{img.size[1]}"
    want = _ns["size_to_longest_side"](size)
    actual = max(img.size)
    if want and actual >= want:
        verdict = "✅ 原生达标"
    elif want:
        verdict = f"⚠️  只有 {actual}px，未达 {want}px"
    else:
        verdict = "（未指定尺寸）"
    print(f"{tier:<6}{size:>12}{got:>12}   {verdict}")

print("\n提示：若 2K 显示「原生达标」，再肉眼比一下 1K 和 2K 的细节——")
print("     若 2K 只是更糊的 1K，说明是中转站服务端自己放大的，客户端看不出来。")
