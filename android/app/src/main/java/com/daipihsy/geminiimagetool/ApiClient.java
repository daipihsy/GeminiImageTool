package com.daipihsy.geminiimagetool;

import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.SocketTimeoutException;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Base64;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CancellationException;

/** Direct HTTPS client compatible with the desktop app's two API protocols. */
public final class ApiClient {
    public static final int MAX_REFERENCE_TOTAL = 12 * 1024 * 1024;
    private static final int MAX_RESPONSE = 48 * 1024 * 1024;
    private volatile HttpURLConnection connection;
    private volatile boolean cancelled;

    public static final class Options {
        public String key = "", base = "", model = Protocol.BANANA, prompt = "", ratio = "1:1", resolution = "1K";
        public boolean openAi, webSearch, imageSearch;
        public Long seed;
        public int count = 1;
        public final List<File> references = new ArrayList<>();
    }
    public static final class Result { public byte[] bytes; public String sources = ""; }

    public void cancel() { cancelled = true; HttpURLConnection c = connection; if (c != null) c.disconnect(); }
    private void check() { if (cancelled || Thread.currentThread().isInterrupted()) throw new CancellationException("已停止"); }

    public static void validate(Options o) {
        if (o.key.trim().isEmpty()) throw new IllegalArgumentException("请先在设置中填写 API Key");
        if (o.key.contains("\n") || o.key.contains("\r")) throw new IllegalArgumentException("API Key 中含有换行，请重新粘贴");
        Protocol.baseUrl(o.base, o.openAi); Protocol.modelId(o.model);
        if (o.prompt.trim().isEmpty()) throw new IllegalArgumentException("请先填写提示词");
        if (o.prompt.length() > 30000) throw new IllegalArgumentException("提示词请控制在 30,000 字符以内");
        if (o.count < 1 || o.count > 10) throw new IllegalArgumentException("每批可生成 1–10 张");
        if (o.references.size() > 10) throw new IllegalArgumentException("最多使用 10 张参考图");
        long total = 0;
        for (File f : o.references) { if (!f.isFile() || f.length() == 0) throw new IllegalArgumentException("参考图已失效，请重新选择"); total += f.length(); }
        if (total > MAX_REFERENCE_TOTAL) throw new IllegalArgumentException("参考图总大小超过 12MB，请减少或压缩图片");
        if (o.openAi) Protocol.openAiSize(o.model, o.ratio, o.resolution); else Protocol.apiRatio(o.model, o.ratio);
    }

    private HttpURLConnection connect(String target, Options o, boolean authenticated) throws Exception {
        check(); URL url = new URL(target);
        if (!"https".equals(url.getProtocol()) || url.getUserInfo() != null) throw new IOException("仅允许安全的 HTTPS 接口和图片地址");
        HttpURLConnection c = (HttpURLConnection) url.openConnection(); connection = c;
        c.setConnectTimeout(30000); c.setReadTimeout(300000); c.setInstanceFollowRedirects(false);
        if (authenticated) c.setRequestProperty(o.openAi ? "Authorization" : "x-goog-api-key", o.openAi ? "Bearer " + o.key.trim() : o.key.trim());
        return c;
    }

    private byte[] response(HttpURLConnection c, Options o) throws Exception {
        try {
            check(); int status = c.getResponseCode();
            if (status >= 300 && status < 400) throw new IOException("接口发生重定向，请填写最终 HTTPS Base URL");
            InputStream input = status >= 400 ? c.getErrorStream() : c.getInputStream();
            byte[] bytes = input == null ? new byte[0] : read(input, status >= 400 ? 64 * 1024 : MAX_RESPONSE);
            if (status >= 400) throw new IOException(Protocol.friendlyError(status, new String(bytes, StandardCharsets.UTF_8), o.key));
            return bytes;
        } catch (SocketTimeoutException e) {
            throw new IOException("连接或生成超时。本次不会自动重试；请先检查服务商记录，避免重复扣费。");
        } finally { c.disconnect(); if (connection == c) connection = null; }
    }

    private byte[] read(InputStream input, int limit) throws Exception {
        try (InputStream in = input; ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[16384]; int n;
            while ((n = in.read(buffer)) != -1) { check(); if (out.size() + n > limit) throw new IOException("接口返回数据过大，请降低分辨率"); out.write(buffer, 0, n); }
            return out.toByteArray();
        }
    }

    private JSONObject json(String url, Options o, JSONObject body) throws Exception {
        HttpURLConnection c = connect(url, o, true);
        try {
            c.setRequestProperty("Accept", "application/json");
            if (body != null) {
                byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
                c.setRequestMethod("POST"); c.setDoOutput(true); c.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                c.setFixedLengthStreamingMode(bytes.length); try (OutputStream out = c.getOutputStream()) { out.write(bytes); }
            }
            return new JSONObject(new String(response(c, o), StandardCharsets.UTF_8));
        } finally { c.disconnect(); }
    }

    public List<String> detectModels(Options o) throws Exception {
        String base = Protocol.baseUrl(o.base, o.openAi), token = ""; List<String> result = new ArrayList<>();
        for (int page = 0; page < 10; page++) {
            String suffix = o.openAi ? "" : "?pageSize=100" + (token.isEmpty() ? "" : "&pageToken=" + URLEncoder.encode(token, "UTF-8"));
            JSONObject data = json(base + "/models" + suffix, o, null);
            JSONArray models = data.optJSONArray(o.openAi ? "data" : "models");
            if (models == null) throw new IOException("模型列表格式与所选协议不匹配，也可手动输入模型名称");
            for (int i = 0; i < models.length(); i++) {
                JSONObject item = models.optJSONObject(i); if (item == null) continue;
                String id = item.optString(o.openAi ? "id" : "name").replaceFirst("^models/", "");
                try { Protocol.modelId(id); } catch (Exception ignored) { continue; }
                if (Protocol.looksImage(id) && !result.contains(id)) result.add(id);
            }
            token = data.optString("nextPageToken", ""); if (o.openAi || token.isEmpty()) break;
        }
        return result;
    }

    public Result generate(Options o, int index) throws Exception {
        validate(o); check(); String base = Protocol.baseUrl(o.base, o.openAi); Result result = new Result();
        if (!o.openAi) {
            JSONArray refs = new JSONArray();
            for (File f : o.references) {
                check(); refs.put(new JSONObject().put("inlineData", new JSONObject().put("mimeType", mime(f))
                    .put("data", Base64.getEncoder().encodeToString(Files.readAllBytes(f.toPath())))));
            }
            JSONObject body = Protocol.geminiBody(o.model, o.prompt, o.ratio, o.resolution,
                o.seed == null ? null : o.seed + index, o.webSearch, o.imageSearch, refs);
            JSONObject payload = json(base + "/models/" + Protocol.modelId(o.model) + ":generateContent", o, body);
            result.bytes = Base64.getMimeDecoder().decode(Protocol.geminiImage(payload).getString("data"));
            result.sources = Protocol.sources(payload);
        } else {
            JSONObject body = Protocol.openAiBody(o.model, o.prompt, o.ratio, o.resolution);
            JSONObject payload = o.references.isEmpty() ? json(base + "/images/generations", o, body) : multipart(base + "/images/edits", o, body);
            JSONArray images = payload.optJSONArray("data"); if (images == null || images.length() == 0) throw new IOException("接口没有返回图片");
            JSONObject first = images.getJSONObject(0); String data = first.optString("b64_json", "");
            if (!data.isEmpty()) {
                if (data.startsWith("data:")) data = data.substring(data.indexOf(',') + 1);
                result.bytes = Base64.getMimeDecoder().decode(data);
            } else {
                String url = first.optString("url", ""); if (url.isEmpty()) throw new IOException("返回结果中没有图片数据或下载地址");
                result.bytes = download(url, o);
            }
        }
        check(); return result;
    }

    private JSONObject multipart(String url, Options o, JSONObject fields) throws Exception {
        String boundary = "GeminiAndroid" + UUID.randomUUID().toString().replace("-", "");
        HttpURLConnection c = connect(url, o, true);
        try {
            c.setRequestMethod("POST"); c.setDoOutput(true); c.setChunkedStreamingMode(16384);
            c.setRequestProperty("Content-Type", "multipart/form-data; boundary=" + boundary);
            try (OutputStream out = c.getOutputStream()) {
                java.util.Iterator<String> keys = fields.keys();
                while (keys.hasNext()) { String key = keys.next(); write(out, "--" + boundary + "\r\nContent-Disposition: form-data; name=\"" + key + "\"\r\n\r\n" + fields.get(key) + "\r\n"); }
                int i = 0;
                for (File f : o.references) {
                    check(); String field = Protocol.GPT.equals(o.model) ? "image" : "image[]";
                    write(out, "--" + boundary + "\r\nContent-Disposition: form-data; name=\"" + field + "\"; filename=\"reference-" + (++i) + "." + extension(mime(f)) + "\"\r\nContent-Type: " + mime(f) + "\r\n\r\n");
                    Files.copy(f.toPath(), out); write(out, "\r\n");
                }
                write(out, "--" + boundary + "--\r\n");
            }
            return new JSONObject(new String(response(c, o), StandardCharsets.UTF_8));
        } finally { c.disconnect(); }
    }

    private byte[] download(String url, Options o) throws Exception {
        for (int i = 0; i < 4; i++) {
            HttpURLConnection c = connect(url, o, false); int status = c.getResponseCode();
            if (status >= 300 && status < 400) {
                String next = c.getHeaderField("Location"); c.disconnect();
                if (next == null) throw new IOException("图片重定向缺少地址"); url = new URL(new URL(url), next).toString(); continue;
            }
            return response(c, o);
        }
        throw new IOException("图片下载重定向过多");
    }

    private static void write(OutputStream out, String value) throws IOException { out.write(value.getBytes(StandardCharsets.UTF_8)); }
    public static String extension(String mime) { return mime != null && mime.contains("jpeg") ? "jpg" : mime != null && mime.contains("webp") ? "webp" : "png"; }
    public static String mime(File f) {
        String n = f.getName().toLowerCase(java.util.Locale.ROOT);
        return n.endsWith(".jpg") || n.endsWith(".jpeg") ? "image/jpeg" : n.endsWith(".webp") ? "image/webp" : "image/png";
    }
}
