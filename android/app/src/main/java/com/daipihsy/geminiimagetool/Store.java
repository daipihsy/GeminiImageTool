package com.daipihsy.geminiimagetool;

import android.content.ContentValues;
import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Matrix;
import android.net.Uri;
import android.os.Environment;
import android.provider.MediaStore;
import androidx.exifinterface.media.ExifInterface;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.UUID;

final class Store {
    private Store() {}
    static File directory(Context c, String name) {
        File dir = new File(c.getFilesDir(), name);
        if (!dir.exists() && !dir.mkdirs()) throw new IllegalStateException("无法创建储存目录");
        return dir;
    }
    static File references(Context c) { return directory(c, "references"); }
    static File outputs(Context c) { return directory(c, "images"); }

    static File importImage(Context c, Uri uri) throws Exception {
        File temp = File.createTempFile("reference-", ".tmp", c.getCacheDir());
        try {
            try (InputStream in = c.getContentResolver().openInputStream(uri); OutputStream out = new FileOutputStream(temp)) {
                if (in == null) throw new IOException("无法读取图片");
                byte[] buffer = new byte[16384]; int n, total = 0;
                while ((n = in.read(buffer)) != -1) {
                    total += n; if (total > ApiClient.MAX_REFERENCE_TOTAL) throw new IOException("单张图片超过 12MB");
                    out.write(buffer, 0, n);
                }
            }
            BitmapFactory.Options info = bounds(temp);
            if (info.outWidth <= 0 || info.outHeight <= 0) throw new IOException("无法识别图片，请使用 JPG、PNG、WebP 或 HEIC");
            if ((long) info.outWidth * info.outHeight > 48_000_000L) throw new IOException("图片超过 4800 万像素，请先缩小");
            int orientation = ExifInterface.ORIENTATION_NORMAL;
            try { orientation = new ExifInterface(temp.getAbsolutePath()).getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL); }
            catch (IOException ignored) {}
            boolean direct = ("image/jpeg".equals(info.outMimeType) || "image/png".equals(info.outMimeType) || "image/webp".equals(info.outMimeType))
                && orientation == ExifInterface.ORIENTATION_NORMAL;
            String id = UUID.randomUUID().toString();
            if (direct) {
                File target = new File(references(c), id + "." + ApiClient.extension(info.outMimeType));
                Files.move(temp.toPath(), target.toPath(), StandardCopyOption.REPLACE_EXISTING); return target;
            }
            Bitmap original = BitmapFactory.decodeFile(temp.getAbsolutePath());
            if (original == null) throw new IOException("图片解码失败");
            Matrix matrix = new Matrix();
            switch (orientation) {
                case ExifInterface.ORIENTATION_FLIP_HORIZONTAL -> matrix.setScale(-1, 1);
                case ExifInterface.ORIENTATION_ROTATE_180 -> matrix.setRotate(180);
                case ExifInterface.ORIENTATION_FLIP_VERTICAL -> matrix.setScale(1, -1);
                case ExifInterface.ORIENTATION_TRANSPOSE -> { matrix.setRotate(90); matrix.postScale(-1, 1); }
                case ExifInterface.ORIENTATION_ROTATE_90 -> matrix.setRotate(90);
                case ExifInterface.ORIENTATION_TRANSVERSE -> { matrix.setRotate(-90); matrix.postScale(-1, 1); }
                case ExifInterface.ORIENTATION_ROTATE_270 -> matrix.setRotate(-90);
                default -> {}
            }
            Bitmap upright = Bitmap.createBitmap(original, 0, 0, original.getWidth(), original.getHeight(), matrix, true);
            boolean alpha = upright.hasAlpha(); File target = new File(references(c), id + (alpha ? ".png" : ".jpg"));
            try (OutputStream out = new FileOutputStream(target)) {
                if (!upright.compress(alpha ? Bitmap.CompressFormat.PNG : Bitmap.CompressFormat.JPEG, 95, out)) throw new IOException("图片转换失败");
            } finally { if (upright != original) upright.recycle(); original.recycle(); }
            if (target.length() > ApiClient.MAX_REFERENCE_TOTAL) { Files.deleteIfExists(target.toPath()); throw new IOException("转换后图片超过 12MB"); }
            return target;
        } finally { Files.deleteIfExists(temp.toPath()); }
    }

    static JSONObject save(Context c, ApiClient.Result result, ApiClient.Options options, int index) throws Exception {
        BitmapFactory.Options info = new BitmapFactory.Options(); info.inJustDecodeBounds = true;
        BitmapFactory.decodeByteArray(result.bytes, 0, result.bytes.length, info);
        if (info.outWidth <= 0 || info.outHeight <= 0 || (long) info.outWidth * info.outHeight > 40_000_000L)
            throw new IOException("接口返回图片无法识别或过大");
        String id = "Gemini-" + new SimpleDateFormat("yyyyMMdd-HHmmss", Locale.ROOT).format(new Date()) + "-" + UUID.randomUUID().toString().substring(0, 8);
        boolean crop = !options.openAi && !"自适应".equals(options.ratio) && !Protocol.apiRatio(options.model, options.ratio).equals(options.ratio);
        boolean resize = !options.openAi && !Protocol.apiResolution(options.model, options.resolution).equals(options.resolution);
        File target = new File(outputs(c), id + (crop || resize ? ".png" : "." + ApiClient.extension(info.outMimeType == null ? "image/png" : info.outMimeType)));
        int width = info.outWidth, height = info.outHeight;
        if (crop || resize) {
            Bitmap bitmap = BitmapFactory.decodeByteArray(result.bytes, 0, result.bytes.length);
            if (bitmap == null) throw new IOException("图片解码失败");
            try {
                if (crop) {
                    String[] ratio = options.ratio.split(":"); double desired = Double.parseDouble(ratio[0]) / Double.parseDouble(ratio[1]);
                    int w = bitmap.getWidth(), h = bitmap.getHeight();
                    if ((double) w / h > desired) w = Math.max(1, (int) (h * desired)); else h = Math.max(1, (int) (w / desired));
                    Bitmap next = Bitmap.createBitmap(bitmap, (bitmap.getWidth() - w) / 2, (bitmap.getHeight() - h) / 2, w, h);
                    if (next != bitmap) bitmap.recycle(); bitmap = next;
                }
                if (resize) {
                    double scale = 512.0 / Math.max(bitmap.getWidth(), bitmap.getHeight());
                    Bitmap next = Bitmap.createScaledBitmap(bitmap, Math.max(1, (int) (bitmap.getWidth() * scale)), Math.max(1, (int) (bitmap.getHeight() * scale)), true);
                    if (next != bitmap) bitmap.recycle(); bitmap = next;
                }
                width = bitmap.getWidth(); height = bitmap.getHeight();
                try (OutputStream out = new FileOutputStream(target)) { if (!bitmap.compress(Bitmap.CompressFormat.PNG, 100, out)) throw new IOException("保存失败"); }
            } finally { bitmap.recycle(); }
        } else Files.write(target.toPath(), result.bytes);
        JSONObject meta = new JSONObject().put("file", target.getName()).put("prompt", options.prompt).put("model", options.model)
            .put("ratio", options.ratio).put("resolution", options.resolution).put("width", width).put("height", height)
            .put("created", System.currentTimeMillis()).put("sources", result.sources).put("cropped", crop);
        if (options.seed != null && !options.openAi) meta.put("seed", options.seed + index);
        write(new File(outputs(c), id + ".json"), meta.toString()); return meta;
    }

    static BitmapFactory.Options bounds(File f) { BitmapFactory.Options o = new BitmapFactory.Options(); o.inJustDecodeBounds = true; BitmapFactory.decodeFile(f.getAbsolutePath(), o); return o; }
    static Bitmap thumbnail(File f, int edge) {
        BitmapFactory.Options o = bounds(f); o.inSampleSize = 1;
        while (Math.max(o.outWidth, o.outHeight) / o.inSampleSize > edge * 2) o.inSampleSize *= 2;
        o.inJustDecodeBounds = false; return BitmapFactory.decodeFile(f.getAbsolutePath(), o);
    }
    static List<JSONObject> results(Context c) {
        List<JSONObject> values = new ArrayList<>(); File[] files = outputs(c).listFiles((d, n) -> n.endsWith(".json"));
        if (files != null) for (File f : files) try {
            JSONObject value = new JSONObject(new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8));
            if (resultFile(c, value.getString("file")).isFile()) values.add(value);
        } catch (Exception ignored) {}
        values.sort(Comparator.comparingLong((JSONObject x) -> x.optLong("created")).reversed()); return values;
    }
    static File resultFile(Context c, String name) throws IOException {
        if (name == null || !name.matches("Gemini-[A-Za-z0-9-]+\\.(png|jpg|webp)")) throw new IOException("无效图片名称");
        File f = new File(outputs(c), name);
        if (!f.getCanonicalFile().getParentFile().equals(outputs(c).getCanonicalFile())) throw new IOException("无效图片路径");
        return f;
    }
    static synchronized Uri saveGallery(Context c, File file) throws Exception {
        String key = "gallery_" + file.getName(), existing = Settings.prefs(c).getString(key, "");
        if (!existing.isEmpty()) try (android.os.ParcelFileDescriptor p = c.getContentResolver().openFileDescriptor(Uri.parse(existing), "r")) { if (p != null) return Uri.parse(existing); }
        catch (Exception ignored) {}
        ContentValues values = new ContentValues(); values.put(MediaStore.Images.Media.DISPLAY_NAME, file.getName()); values.put(MediaStore.Images.Media.MIME_TYPE, ApiClient.mime(file));
        values.put(MediaStore.Images.Media.RELATIVE_PATH, Environment.DIRECTORY_PICTURES + "/GeminiImageTool"); values.put(MediaStore.Images.Media.IS_PENDING, 1);
        Uri uri = c.getContentResolver().insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values); if (uri == null) throw new IOException("无法创建相册图片");
        try {
            try (OutputStream out = c.getContentResolver().openOutputStream(uri)) { if (out == null) throw new IOException("无法写入相册"); Files.copy(file.toPath(), out); }
            values.clear(); values.put(MediaStore.Images.Media.IS_PENDING, 0); c.getContentResolver().update(uri, values, null, null);
            Settings.prefs(c).edit().putString(key, uri.toString()).apply(); return uri;
        } catch (Exception e) { c.getContentResolver().delete(uri, null, null); throw e; }
    }
    static synchronized void addPrompt(Context c, String prompt) throws Exception {
        JSONArray old = prompts(c), next = new JSONArray(); next.put(prompt);
        for (int i = 0; i < old.length() && next.length() < 100; i++) if (!prompt.equals(old.optString(i))) next.put(old.optString(i));
        write(new File(c.getFilesDir(), "prompts.json"), next.toString());
    }
    static JSONArray prompts(Context c) {
        try { return new JSONArray(new String(Files.readAllBytes(new File(c.getFilesDir(), "prompts.json").toPath()), StandardCharsets.UTF_8)); }
        catch (Exception e) { return new JSONArray(); }
    }
    private static void write(File target, String value) throws IOException {
        File temp = new File(target.getParentFile(), target.getName() + ".tmp"); Files.write(temp.toPath(), value.getBytes(StandardCharsets.UTF_8));
        Files.move(temp.toPath(), target.toPath(), StandardCopyOption.REPLACE_EXISTING);
    }
}
