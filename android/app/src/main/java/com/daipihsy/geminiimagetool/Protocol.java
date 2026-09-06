package com.daipihsy.geminiimagetool;

import org.json.JSONArray;
import org.json.JSONObject;
import java.net.URI;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Locale;
import java.util.regex.Pattern;

/** Shared request/response rules kept independent of Android for offline tests. */
public final class Protocol {
    public static final String BANANA = "gemini-3.1-flash-image-preview";
    public static final String PRO = "gemini-3-pro-image-preview";
    public static final String GPT = "gpt-image-2-vip";
    public static final String[] RATIOS = {"自适应", "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9", "4:1", "1:4"};
    public static final String[] RESOLUTIONS = {"512", "1K", "2K", "4K"};
    private static final Pattern MODEL = Pattern.compile("[A-Za-z0-9][A-Za-z0-9._-]{0,199}");
    private Protocol() {}

    public static String baseUrl(String value, boolean openAi) {
        String raw = value == null ? "" : value.trim();
        if (raw.isEmpty()) raw = openAi ? "https://api.apiyi.com" : "https://generativelanguage.googleapis.com";
        while (raw.endsWith("/")) raw = raw.substring(0, raw.length() - 1);
        URI uri;
        try { uri = URI.create(raw); } catch (Exception e) { throw new IllegalArgumentException("Base URL 格式不正确"); }
        if (!"https".equalsIgnoreCase(uri.getScheme()) || uri.getHost() == null || uri.getUserInfo() != null
                || uri.getRawQuery() != null || uri.getRawFragment() != null) {
            throw new IllegalArgumentException("Base URL 请填写 HTTPS 根地址，不能包含密钥、问号或片段");
        }
        String path = uri.getPath() == null ? "" : uri.getPath();
        if (path.contains("/models/") || path.endsWith("/images/generations") || path.endsWith("/images/edits"))
            throw new IllegalArgumentException("Base URL 只填写根地址，或以 /v1、/v1beta 结尾");
        raw = raw.replaceFirst("/v1(?:beta)?$", "");
        return raw + (openAi ? "/v1" : "/v1beta");
    }

    public static String modelId(String value) {
        String result = value == null ? "" : value.trim().replaceFirst("^models/", "");
        if (!MODEL.matcher(result).matches()) throw new IllegalArgumentException("模型名称格式不正确");
        return result;
    }

    public static boolean looksImage(String value) {
        String s = value.toLowerCase(Locale.ROOT);
        for (String key : new String[]{"image", "imagen", "banana", "dall", "flux", "seedream", "kontext", "sdxl", "stable-diffusion"})
            if (s.contains(key)) return true;
        return false;
    }

    public static String apiRatio(String model, String ratio) {
        if ("自适应".equals(ratio)) return "";
        if (Arrays.asList("1:1", "3:4", "4:3", "9:16", "16:9").contains(ratio)) return ratio;
        if (BANANA.equals(model) && Arrays.asList("4:1", "1:4").contains(ratio)) return ratio;
        return switch (ratio) {
            case "2:3", "4:5" -> "3:4";
            case "3:2", "5:4" -> "4:3";
            case "21:9", "4:1" -> "16:9";
            case "1:4" -> "9:16";
            default -> throw new IllegalArgumentException("不支持的宽高比");
        };
    }

    public static String apiResolution(String model, String resolution) {
        return "512".equals(resolution) && !BANANA.equals(model) ? "1K" : resolution;
    }

    public static String openAiSize(String model, String ratio, String resolution) {
        if ("自适应".equals(ratio)) return "auto";
        if (!GPT.equals(model)) {
            return switch (ratio) {
                case "1:1" -> "1024x1024";
                case "2:3", "3:4", "4:5", "9:16", "1:4" -> "1024x1536";
                default -> "1536x1024";
            };
        }
        String[] ratios = {"1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"};
        String[][] sizes = {
            {"1280x1280", "848x1280", "1280x848", "960x1280", "1280x960", "1024x1280", "1280x1024", "720x1280", "1280x720", "1280x544"},
            {"2048x2048", "1360x2048", "2048x1360", "1536x2048", "2048x1536", "1632x2048", "2048x1632", "1152x2048", "2048x1152", "2048x864"},
            {"2880x2880", "2336x3520", "3520x2336", "2480x3312", "3312x2480", "2560x3216", "3216x2560", "2160x3840", "3840x2160", "3840x1632"}
        };
        int row = "4K".equals(resolution) ? 2 : "2K".equals(resolution) ? 1 : 0;
        for (int i = 0; i < ratios.length; i++) if (ratios[i].equals(ratio)) return sizes[row][i];
        throw new IllegalArgumentException("GPT-Image-2-VIP 暂不支持 4:1 / 1:4");
    }

    public static JSONObject geminiBody(String model, String prompt, String ratio, String resolution,
                                         Long seed, boolean web, boolean imageSearch, JSONArray refs) throws Exception {
        String nativeRatio = apiRatio(model, ratio);
        String effective = prompt;
        if (!nativeRatio.isEmpty() && !nativeRatio.equals(ratio))
            effective += "\nCompose for a final " + ratio + " center crop. Keep the important subject away from the edges.";
        JSONArray parts = new JSONArray().put(new JSONObject().put("text", effective));
        for (int i = 0; i < refs.length(); i++) parts.put(refs.getJSONObject(i));
        JSONObject image = new JSONObject().put("imageSize", apiResolution(model, resolution));
        if (!nativeRatio.isEmpty()) image.put("aspectRatio", nativeRatio);
        JSONObject generation = new JSONObject()
            .put("responseModalities", new JSONArray().put("TEXT").put("IMAGE"))
            .put("candidateCount", 1).put("imageConfig", image);
        if (seed != null) generation.put("seed", seed);
        JSONObject body = new JSONObject()
            .put("contents", new JSONArray().put(new JSONObject().put("role", "user").put("parts", parts)))
            .put("generationConfig", generation);
        if (web) {
            JSONObject search = new JSONObject();
            if (imageSearch && BANANA.equals(model)) search.put("searchTypes",
                new JSONObject().put("webSearch", new JSONObject()).put("imageSearch", new JSONObject()));
            body.put("tools", new JSONArray().put(new JSONObject().put("googleSearch", search)));
        }
        return body;
    }

    public static JSONObject openAiBody(String model, String prompt, String ratio, String resolution) throws Exception {
        return new JSONObject().put("model", modelId(model)).put("prompt", prompt)
            .put("size", openAiSize(model, ratio, resolution)).put("n", 1).put("response_format", "b64_json");
    }

    public static JSONObject geminiImage(JSONObject response) throws Exception {
        JSONArray candidates = response.optJSONArray("candidates");
        if (candidates != null && candidates.length() > 0) {
            JSONObject candidate = candidates.getJSONObject(0);
            JSONObject content = candidate.optJSONObject("content");
            JSONArray parts = content == null ? null : content.optJSONArray("parts");
            if (parts != null) for (int i = 0; i < parts.length(); i++) {
                JSONObject part = parts.getJSONObject(i);
                if (part.optBoolean("thought", false)) continue;
                JSONObject data = part.optJSONObject("inlineData");
                if (data == null) data = part.optJSONObject("inline_data");
                if (data != null && !data.optString("data").isEmpty()) return data;
            }
            throw new IllegalStateException("模型没有返回图片（" + candidate.optString("finishReason", "未知原因") + "）");
        }
        JSONObject feedback = response.optJSONObject("promptFeedback");
        throw new IllegalStateException(feedback == null ? "接口未返回图片，请检查协议和模型" : "请求被拦截：" + feedback.optString("blockReason"));
    }

    public static String sources(JSONObject response) {
        JSONArray candidates = response.optJSONArray("candidates");
        if (candidates == null || candidates.length() == 0) return "";
        JSONObject candidate = candidates.optJSONObject(0);
        JSONObject meta = candidate == null ? null : candidate.optJSONObject("groundingMetadata");
        JSONArray chunks = meta == null ? null : meta.optJSONArray("groundingChunks");
        List<String> lines = new ArrayList<>();
        if (chunks != null) for (int i = 0; i < chunks.length(); i++) {
            JSONObject item = chunks.optJSONObject(i);
            JSONObject web = item == null ? null : item.optJSONObject("web");
            if (web != null) lines.add(web.optString("title") + "\n" + web.optString("uri"));
        }
        return String.join("\n\n", lines);
    }

    public static String friendlyError(int status, String body, String key) {
        String hint = switch (status) {
            case 401 -> "API Key 无效或已过期";
            case 403 -> "没有权限访问模型，请检查 Key、模型权限或网络地区";
            case 404 -> "接口或模型不存在，请检查协议、Base URL 和模型名称";
            case 429 -> "余额 / 配额不足或请求过于频繁";
            default -> "接口请求失败（HTTP " + status + "）";
        };
        String detail = "";
        try {
            JSONObject json = new JSONObject(body);
            Object error = json.opt("error");
            detail = error instanceof JSONObject ? ((JSONObject) error).optString("message") : json.optString("message", "");
        } catch (Exception ignored) { }
        detail = redact(detail, key);
        if (detail.length() > 350) detail = detail.substring(0, 350) + "…";
        return detail.isEmpty() ? hint : hint + "\n" + detail;
    }

    public static String redact(String value, String key) {
        String result = value == null || value.trim().isEmpty() ? "未知错误" : value;
        if (key != null && !key.isEmpty()) result = result.replace(key, "[已隐藏密钥]");
        return result.replaceAll("(?i)(?:sk-[A-Za-z0-9_-]{8,}|AIza[A-Za-z0-9_-]{15,})", "[已隐藏密钥]");
    }
}
