package com.daipihsy.geminiimagetool;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.app.Dialog;
import android.content.ClipData;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.content.res.ColorStateList;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowInsets;
import android.widget.ArrayAdapter;
import android.widget.AutoCompleteTextView;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.HorizontalScrollView;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.nio.file.Files;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class MainActivity extends Activity {
    private static final int PICK_IMAGES = 20;
    private static final int BG = Color.rgb(245, 244, 240), INK = Color.rgb(31, 45, 39), GREEN = Color.rgb(37, 90, 70), MUTED = Color.rgb(103, 113, 105);
    private ImageApp app;
    private SharedPreferences prefs;
    private LinearLayout root, body, page, referenceRow, resultList;
    private EditText prompt, seedInput, keyInput, baseInput;
    private AutoCompleteTextView modelInput;
    private Spinner ratio, resolution, count, protocol;
    private CheckBox webSearch, imageSearch, rememberKey;
    private TextView statusLabel, resultCount;
    private Button generateButton, stopButton;
    private ProgressBar progress;
    private int tab, galleryLimit = 20, shownCompleted = -1;
    private boolean detecting;
    private ApiClient detectionClient;
    private String referenceSignature = "";
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private final Runnable stateListener = this::refreshState;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state); app = (ImageApp) getApplication(); prefs = Settings.prefs(this);
        tab = state == null ? 0 : state.getInt("tab", 0); buildShell();
    }
    @Override protected void onResume() { super.onResume(); app.listeners.add(stateListener); refreshState(); }
    @Override protected void onPause() { saveDraft(); app.listeners.remove(stateListener); super.onPause(); }
    @Override protected void onSaveInstanceState(Bundle state) { saveDraft(); state.putInt("tab", tab); super.onSaveInstanceState(state); }
    @Override protected void onDestroy() { if (detectionClient != null) detectionClient.cancel(); io.shutdownNow(); super.onDestroy(); }

    private void buildShell() {
        root = vertical(); root.setBackgroundColor(BG);
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            if (Build.VERSION.SDK_INT >= 30) {
                android.graphics.Insets bars = insets.getInsets(WindowInsets.Type.systemBars());
                android.graphics.Insets ime = insets.getInsets(WindowInsets.Type.ime());
                view.setPadding(bars.left, bars.top, bars.right, Math.max(bars.bottom, ime.bottom));
            } else view.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(), insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets;
        });
        LinearLayout header = horizontal(); header.setGravity(Gravity.CENTER_VERTICAL); header.setPadding(dp(20), dp(15), dp(20), dp(10));
        LinearLayout titles = vertical(); titles.addView(text("GEMINI STUDIO", 12, GREEN, true)); titles.addView(text("把想法，变成图片", 23, INK, true));
        header.addView(titles, new LinearLayout.LayoutParams(0, -2, 1));
        TextView badge = text("安卓版", 12, GREEN, true); badge.setPadding(dp(12), dp(7), dp(12), dp(7)); badge.setBackground(shape(Color.rgb(226, 234, 221), 18)); header.addView(badge);
        root.addView(header); body = vertical(); root.addView(body, new LinearLayout.LayoutParams(-1, 0, 1));
        LinearLayout nav = horizontal(); nav.setPadding(dp(8), dp(4), dp(8), dp(4)); nav.setBackgroundColor(Color.WHITE);
        String[] labels = {"创作", "作品", "设置"};
        for (int i = 0; i < labels.length; i++) { int index = i; nav.addView(button(labels[i], tab == i, () -> switchTab(index)), weighted()); }
        root.addView(nav); setContentView(root); showPage();
    }

    private void switchTab(int value) { saveDraft(); tab = value; buildShell(); }
    private void showPage() {
        prompt = null; seedInput = null; modelInput = null; ratio = null; resolution = null; count = null;
        webSearch = null; imageSearch = null; statusLabel = null; generateButton = null; stopButton = null; progress = null; resultList = null;
        body.removeAllViews(); ScrollView scroll = new ScrollView(this); scroll.setFillViewport(true); scroll.setClipToPadding(false);
        page = vertical(); page.setPadding(dp(16), dp(3), dp(16), dp(22)); scroll.addView(page); body.addView(scroll, new LinearLayout.LayoutParams(-1, -1));
        if (tab == 0) buildCreate(); else if (tab == 1) buildGallery(); else buildSettings(); refreshState();
    }

    private void buildCreate() {
        LinearLayout description = card(); description.addView(text("01  /  描述画面", 13, GREEN, true));
        prompt = field("描述你想生成或修改的图片…", prefs.getString("draft", ""), true); prompt.setMinLines(5); prompt.setMaxLines(10); description.addView(prompt);
        description.addView(button("使用历史提示词", false, this::showPromptHistory)); page.addView(description);

        LinearLayout references = card(); references.addView(text("02  /  参考图片", 13, GREEN, true));
        references.addView(note("可选，最多 10 张、总计 12MB；顺序对应图1、图2……"));
        HorizontalScrollView strip = new HorizontalScrollView(this); strip.setHorizontalScrollBarEnabled(false); referenceRow = horizontal(); strip.addView(referenceRow); references.addView(strip);
        references.addView(button("＋ 从手机选择图片", false, this::pickImages)); page.addView(references); renderReferences();

        LinearLayout parameters = card(); parameters.addView(text("03  /  生成参数", 13, GREEN, true));
        parameters.addView(label("模型（可直接输入）"));
        modelInput = new AutoCompleteTextView(this); modelInput.setSingleLine(true); modelInput.setThreshold(0); modelInput.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS); styleField(modelInput);
        modelInput.setText(prefs.getString("model", openAi() ? Protocol.GPT : Protocol.BANANA)); modelInput.setAdapter(new ArrayAdapter<>(this, android.R.layout.simple_dropdown_item_1line, modelChoices())); parameters.addView(modelInput);
        parameters.addView(button("选择模型", false, this::chooseModel));
        LinearLayout row = horizontal(); ratio = selector(Protocol.RATIOS, prefs.getString("ratio", "1:1")); resolution = selector(Protocol.RESOLUTIONS, prefs.getString("resolution", "1K"));
        count = selector(new String[]{"1", "2", "3", "4", "5", "6", "7", "8", "9", "10"}, prefs.getString("count", "1"));
        row.addView(labelled("比例", ratio), weighted()); row.addView(labelled("清晰度", resolution), weighted()); row.addView(labelled("张数", count), weighted()); parameters.addView(row);
        parameters.addView(note(openAi() ? "使用 OpenAI Images 接口。GPT-Image-2-VIP 沿用电脑版尺寸表。" : "非原生比例会生成后居中裁切；Pro 的 512 档由 1K 缩小。"));
        LinearLayout advanced = vertical(); advanced.setVisibility(View.GONE); seedInput = field("留空为随机", prefs.getString("seed", ""), false); seedInput.setInputType(InputType.TYPE_CLASS_NUMBER);
        advanced.addView(label("固定种子（可选，每张依次 +1）")); advanced.addView(seedInput);
        webSearch = checkbox("使用 Google 搜索", prefs.getBoolean("web", false)); imageSearch = checkbox("同时使用图片搜索（Nano Banana 2）", prefs.getBoolean("image_search", false));
        advanced.addView(webSearch); advanced.addView(imageSearch);
        if (openAi()) { seedInput.setEnabled(false); webSearch.setEnabled(false); imageSearch.setEnabled(false); advanced.addView(note("Images 接口不发送种子与搜索参数。")); }
        parameters.addView(button("高级选项", false, () -> advanced.setVisibility(advanced.getVisibility() == View.VISIBLE ? View.GONE : View.VISIBLE))); parameters.addView(advanced); page.addView(parameters);

        LinearLayout actions = card(); statusLabel = text(app.status, 14, INK, false); statusLabel.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE); actions.addView(statusLabel);
        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal); progress.setProgressTintList(ColorStateList.valueOf(GREEN)); actions.addView(progress, new LinearLayout.LayoutParams(-1, dp(10)));
        generateButton = button("开始生成", true, this::startGeneration); actions.addView(generateButton);
        stopButton = button("停止本批次", false, this::confirmStop); actions.addView(stopButton);
        actions.addView(note("每张分别请求，费用由 API 服务商收取。生成时可以切换应用，进度会显示在通知中。")); page.addView(actions);
    }

    private void renderReferences() {
        if (referenceRow == null) return; referenceRow.removeAllViews();
        if (app.references.isEmpty()) { referenceRow.addView(note("未添加参考图 · 直接文字生成也可以")); return; }
        for (int i = 0; i < app.references.size(); i++) {
            int index = i; File file = app.references.get(i); LinearLayout item = vertical(); item.setPadding(dp(3), dp(6), dp(5), dp(5));
            item.addView(text("图" + (i + 1), 13, GREEN, true)); ImageView image = new ImageView(this); image.setContentDescription("参考图" + (i + 1)); image.setScaleType(ImageView.ScaleType.CENTER_CROP);
            item.addView(image, new LinearLayout.LayoutParams(dp(140), dp(96))); loadThumbnail(file, image, 320); image.setOnClickListener(v -> preview(file, null));
            LinearLayout controls = horizontal(); Button left = button("←", false, () -> moveReference(index, -1)); Button right = button("→", false, () -> moveReference(index, 1));
            Button remove = button("×", false, () -> removeReference(file)); left.setEnabled(i > 0 && !app.running); right.setEnabled(i < app.references.size() - 1 && !app.running); remove.setEnabled(!app.running);
            controls.addView(left, weighted()); controls.addView(right, weighted()); controls.addView(remove, weighted()); item.addView(controls); referenceRow.addView(item, new LinearLayout.LayoutParams(dp(154), -2));
        }
    }
    private void moveReference(int index, int delta) {
        if (app.running) { toast("生成中不能调整参考图"); return; } int target = index + delta; if (target < 0 || target >= app.references.size()) return;
        java.util.Collections.swap(app.references, index, target); app.persistReferences(); referenceSignature = ""; renderReferences();
    }
    private void removeReference(File file) {
        if (app.running) { toast("生成中不能调整参考图"); return; } app.references.remove(file); app.persistReferences(); referenceSignature = ""; renderReferences();
        io.execute(() -> { try { Files.deleteIfExists(file.toPath()); } catch (Exception ignored) {} });
    }
    private void pickImages() {
        if (app.running || app.importing) { toast(app.running ? "生成中不能调整参考图" : "正在读取图片"); return; }
        if (app.references.size() >= 10) { toast("最多添加 10 张参考图"); return; }
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("image/*").addCategory(Intent.CATEGORY_OPENABLE).putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
        startActivityForResult(intent, PICK_IMAGES);
    }
    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data); if (requestCode != PICK_IMAGES || resultCode != RESULT_OK || data == null) return;
        List<Uri> uris = new ArrayList<>(); if (data.getClipData() != null) for (int i = 0; i < data.getClipData().getItemCount(); i++) uris.add(data.getClipData().getItemAt(i).getUri()); else if (data.getData() != null) uris.add(data.getData());
        if (uris.size() + app.references.size() > 10) { toast("最多添加 10 张，请重新选择"); return; }
        long existing = 0; for (File file : app.references) existing += file.length(); final long current = existing;
        app.importing = true; app.update("正在读取参考图…");
        io.execute(() -> {
            List<File> imported = new ArrayList<>();
            try {
                long total = current; for (Uri uri : uris) { File f = Store.importImage(getApplicationContext(), uri); imported.add(f); total += f.length(); if (total > ApiClient.MAX_REFERENCE_TOTAL) throw new IllegalArgumentException("参考图总大小超过 12MB"); }
                runOnUiThread(() -> { app.references.addAll(imported); app.persistReferences(); app.importing = false; app.update("已添加 " + imported.size() + " 张参考图"); referenceSignature = ""; });
            } catch (Exception | OutOfMemoryError e) {
                for (File f : imported) try { Files.deleteIfExists(f.toPath()); } catch (Exception ignored) {}
                runOnUiThread(() -> { app.importing = false; app.update(e instanceof OutOfMemoryError ? "手机内存不足，请缩小参考图" : "导入失败：" + e.getMessage()); });
            }
        });
    }

    private void startGeneration() {
        if (app.running || app.importing) return;
        try {
            saveDraft(); ApiClient.Options value = options(); value.model = Protocol.modelId(modelInput.getText().toString()); value.prompt = prompt.getText().toString().trim();
            value.ratio = selected(ratio); value.resolution = selected(resolution); value.count = Integer.parseInt(selected(count)); value.references.addAll(app.references);
            if (!value.openAi) {
                value.webSearch = webSearch.isChecked(); value.imageSearch = imageSearch.isChecked(); String seed = seedInput.getText().toString().trim();
                if (!seed.isEmpty()) { long n = Long.parseLong(seed); if (n < 0 || n > Integer.MAX_VALUE - 10L) throw new IllegalArgumentException("种子请输入 0–2147483637"); value.seed = n; }
            }
            ApiClient.validate(value);
            if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED && !prefs.getBoolean("notification_asked", false)) {
                prefs.edit().putBoolean("notification_asked", true).apply(); requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 30);
            }
            app.pending = value; app.running = true; app.completed = 0; app.total = value.count; app.update("准备生成…");
            startForegroundService(new Intent(this, GenerationService.class));
        } catch (Exception e) { app.pending = null; app.running = false; app.update(Protocol.redact(e.getMessage(), app.apiKey)); }
    }
    private void confirmStop() {
        new AlertDialog.Builder(this).setTitle("停止生成？").setMessage("已完成图片会保留；已经发出的请求可能仍会处理和计费。")
            .setNegativeButton("继续生成", null).setPositiveButton("停止", (d, w) -> startService(new Intent(this, GenerationService.class).setAction(GenerationService.CANCEL))).show();
    }
    private ApiClient.Options options() {
        ApiClient.Options value = new ApiClient.Options(); value.openAi = openAi(); value.key = app.apiKey.trim(); value.base = prefs.getString("base", "");
        value.model = modelInput == null ? prefs.getString("model", value.openAi ? Protocol.GPT : Protocol.BANANA) : modelInput.getText().toString().trim(); return value;
    }
    private void saveDraft() {
        if (prompt == null) return;
        prefs.edit().putString("draft", prompt.getText().toString()).putString("model", modelInput.getText().toString().trim())
            .putString("ratio", selected(ratio)).putString("resolution", selected(resolution)).putString("count", selected(count))
            .putString("seed", seedInput.getText().toString()).putBoolean("web", webSearch.isChecked()).putBoolean("image_search", imageSearch.isChecked()).apply();
    }

    private void buildSettings() {
        LinearLayout connection = card(); connection.addView(text("连接图像模型", 20, INK, true)); connection.addView(note("手机直接连接服务商，无需开启电脑；网络跟随手机系统和 VPN。"));
        protocol = selector(new String[]{"Gemini 原生接口", "OpenAI Images 接口"}, openAi() ? "OpenAI Images 接口" : "Gemini 原生接口"); connection.addView(label("接口协议")); connection.addView(protocol);
        baseInput = field("留空使用默认地址", prefs.getString("base", ""), false); baseInput.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI); connection.addView(label("Base URL")); connection.addView(baseInput);
        connection.addView(note("Gemini 留空连接 Google；OpenAI Images 留空连接 APIYI。自定义地址必须为 HTTPS。"));
        keyInput = field("粘贴 API Key", app.apiKey, false); keyInput.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD); keyInput.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS);
        keyInput.setImeOptions(android.view.inputmethod.EditorInfo.IME_FLAG_NO_PERSONALIZED_LEARNING); connection.addView(label("API Key")); connection.addView(keyInput);
        CheckBox reveal = checkbox("显示密钥", false); reveal.setOnCheckedChangeListener((b, checked) -> { keyInput.setInputType(InputType.TYPE_CLASS_TEXT | (checked ? InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD : InputType.TYPE_TEXT_VARIATION_PASSWORD)); keyInput.setSelection(keyInput.length()); }); connection.addView(reveal);
        rememberKey = checkbox("在此手机记住密钥", prefs.getBoolean("remember_key", false)); connection.addView(rememberKey); connection.addView(note("勾选后使用 Android 系统密钥库加密；应用不参与系统备份。"));
        connection.addView(button("保存设置", true, () -> saveSettings(true))); connection.addView(button("检测可用模型 / 测试连接", false, this::detectModels));
        statusLabel = text(app.status, 14, INK, false); connection.addView(statusLabel); page.addView(connection);
        LinearLayout about = card(); about.addView(text("Gemini 图像工具 · Android", 17, INK, true));
        about.addView(note("1.0.0-beta1 · 支持 Android 10 及以上\n\n作品先保存在应用内；“存相册”会写入 Pictures/GeminiImageTool。卸载前请保存需要的图片。\n\n检测模型列表不发起收费生图请求。GRSAI 等专有异步接口暂未包含。")); page.addView(about);
    }
    private boolean saveSettings(boolean feedback) {
        try {
            boolean nextOpenAi = protocol.getSelectedItemPosition() == 1, changed = nextOpenAi != openAi(); String base = baseInput.getText().toString().trim(), key = keyInput.getText().toString().trim();
            Protocol.baseUrl(base, nextOpenAi); if (key.contains("\n") || key.contains("\r")) throw new IllegalArgumentException("API Key 不能包含换行"); Settings.saveKey(this, key, rememberKey.isChecked());
            SharedPreferences.Editor edit = prefs.edit().putBoolean("open_ai", nextOpenAi).putString("base", base); if (changed) edit.putString("model", nextOpenAi ? Protocol.GPT : Protocol.BANANA).remove("available_models"); edit.apply(); app.apiKey = key;
            if (feedback) app.update("设置已保存，可到「创作」开始生成"); return true;
        } catch (Exception e) { app.update("保存失败：" + Protocol.redact(e.getMessage(), app.apiKey)); return false; }
    }
    private void detectModels() {
        if (detecting) { toast("正在检测，请稍候"); return; } if (!saveSettings(false)) return; ApiClient.Options value = options();
        if (value.key.isEmpty()) { app.update("请先填写 API Key"); return; } detecting = true; app.update("正在读取可用模型…"); detectionClient = new ApiClient(); ApiClient client = detectionClient;
        io.execute(() -> {
            try {
                List<String> models = client.detectModels(value);
                runOnUiThread(() -> { detecting = false; prefs.edit().putString("available_models", String.join("\n", models)).apply(); app.update(models.isEmpty() ? "连接成功，但未筛出图像模型；可在创作页手动输入。" : "连接成功，找到 " + models.size() + " 个图像模型。能否生图以服务商权限为准。"); });
            } catch (Exception e) { runOnUiThread(() -> { detecting = false; app.update("检测失败：" + Protocol.redact(e.getMessage(), value.key)); }); }
        });
    }
    private void chooseModel() { List<String> values = modelChoices(); new AlertDialog.Builder(this).setTitle("选择图像模型").setItems(values.toArray(new String[0]), (d, i) -> modelInput.setText(values.get(i))).setNegativeButton("取消", null).show(); }
    private List<String> modelChoices() {
        List<String> result = new ArrayList<>(openAi() ? Arrays.asList(Protocol.GPT) : Arrays.asList(Protocol.BANANA, Protocol.PRO));
        for (String value : prefs.getString("available_models", "").split("\n")) if (!value.isEmpty() && !result.contains(value)) result.add(value); return result;
    }
    private void showPromptHistory() {
        JSONArray history = Store.prompts(this); if (history.length() == 0) { toast("生成后，提示词会自动保存在这里"); return; }
        String[] labels = new String[history.length()]; for (int i = 0; i < labels.length; i++) { String s = history.optString(i).replace('\n', ' '); labels[i] = s.length() > 100 ? s.substring(0, 100) + "…" : s; }
        new AlertDialog.Builder(this).setTitle("提示词历史").setItems(labels, (d, i) -> prompt.setText(history.optString(i))).setNegativeButton("关闭", null).show();
    }

    private void buildGallery() {
        LinearLayout header = card(); header.addView(text("你的作品", 22, INK, true)); header.addView(note("点击图片放大；可保存到相册或分享原图。")); statusLabel = text(app.status, 14, GREEN, false); header.addView(statusLabel);
        resultCount = note("正在读取…"); header.addView(resultCount); header.addView(button("刷新作品", false, this::renderGallery)); page.addView(header); resultList = vertical(); page.addView(resultList); shownCompleted = app.completed; renderGallery();
    }
    private void renderGallery() {
        if (resultList == null) return; LinearLayout destination = resultList;
        io.execute(() -> { List<JSONObject> items = Store.results(getApplicationContext()); runOnUiThread(() -> {
            if (isDestroyed() || destination != resultList) return; destination.removeAllViews(); resultCount.setText(String.format(Locale.CHINA, "共 %d 张作品", items.size()));
            if (items.isEmpty()) { LinearLayout empty = card(); empty.addView(text("第一张作品，从一个想法开始", 18, INK, true)); empty.addView(note("去创作页输入提示词，图片会出现在这里。")); destination.addView(empty); return; }
            for (int i = 0; i < Math.min(galleryLimit, items.size()); i++) addResult(destination, items.get(i));
            if (items.size() > galleryLimit) destination.addView(button("加载更多", false, () -> { galleryLimit += 20; renderGallery(); }));
        }); });
    }
    private void addResult(LinearLayout destination, JSONObject item) {
        try {
            File file = Store.resultFile(this, item.getString("file")); LinearLayout card = card(); ImageView image = new ImageView(this); image.setContentDescription("生成作品，点击查看大图"); image.setScaleType(ImageView.ScaleType.FIT_CENTER); image.setBackground(shape(BG, 12));
            card.addView(image, new LinearLayout.LayoutParams(-1, dp(235))); loadThumbnail(file, image, 700); image.setOnClickListener(v -> preview(file, item));
            card.addView(text(item.optInt("width") + " × " + item.optInt("height") + "  ·  " + item.optString("model"), 12, GREEN, true)); TextView caption = text(item.optString("prompt"), 14, INK, false); caption.setMaxLines(3); card.addView(caption);
            card.addView(note(new SimpleDateFormat("MM月dd日 HH:mm", Locale.CHINA).format(new Date(item.optLong("created"))) + (item.optBoolean("cropped") ? " · 已居中裁切" : "")));
            LinearLayout actions = horizontal(); actions.addView(button("存相册", true, () -> saveGallery(file)), weighted()); actions.addView(button("分享", false, () -> share(file)), weighted()); card.addView(actions);
            card.addView(button("再次使用提示词", false, () -> { prefs.edit().putString("draft", item.optString("prompt")).apply(); switchTab(0); })); destination.addView(card);
        } catch (Exception ignored) {}
    }
    private void preview(File file, JSONObject item) {
        Dialog dialog = new Dialog(this, android.R.style.Theme_Material_Light_NoActionBar); LinearLayout layout = vertical(); layout.setPadding(dp(14), dp(28), dp(14), dp(24)); layout.setBackgroundColor(BG);
        layout.addView(button("关闭预览", false, dialog::dismiss)); ImageView image = new ImageView(this); image.setContentDescription("图片大图预览"); image.setScaleType(ImageView.ScaleType.FIT_CENTER); layout.addView(image, new LinearLayout.LayoutParams(-1, 0, 1));
        if (item != null) { LinearLayout actions = horizontal(); actions.addView(button("存相册", true, () -> saveGallery(file)), weighted()); actions.addView(button("分享原图", false, () -> share(file)), weighted()); layout.addView(actions);
            if (!item.optString("sources").isEmpty()) layout.addView(button("查看搜索来源", false, () -> new AlertDialog.Builder(this).setTitle("搜索来源").setMessage(item.optString("sources")).setPositiveButton("关闭", null).show())); }
        dialog.setContentView(layout); dialog.show(); loadThumbnail(file, image, 2048);
    }
    private void saveGallery(File file) { io.execute(() -> { try { Store.saveGallery(getApplicationContext(), file); runOnUiThread(() -> toast("已保存到相册 · GeminiImageTool")); } catch (Exception e) { runOnUiThread(() -> toast("保存失败：" + e.getMessage())); } }); }
    private void share(File file) {
        Uri uri = new Uri.Builder().scheme("content").authority(getPackageName() + ".images").appendPath(file.getName()).build();
        Intent intent = new Intent(Intent.ACTION_SEND).setType(ApiClient.mime(file)).putExtra(Intent.EXTRA_STREAM, uri).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION); intent.setClipData(ClipData.newUri(getContentResolver(), "生成图片", uri)); startActivity(Intent.createChooser(intent, "分享原图"));
    }
    private void loadThumbnail(File file, ImageView target, int edge) { io.execute(() -> { Bitmap image = Store.thumbnail(file, edge); runOnUiThread(() -> { if (!isDestroyed() && target.isAttachedToWindow()) target.setImageBitmap(image); else if (image != null) image.recycle(); }); }); }

    private void refreshState() {
        if (isDestroyed()) return; if (statusLabel != null) statusLabel.setText(app.status);
        if (tab == 0 && referenceRow != null) { String signature = app.references.toString() + app.running; if (!signature.equals(referenceSignature)) { referenceSignature = signature; renderReferences(); } }
        if (generateButton != null) { generateButton.setText(app.running ? "正在生成 " + app.completed + " / " + app.total : "开始生成"); generateButton.setEnabled(!app.running && !app.importing); }
        if (stopButton != null) stopButton.setVisibility(app.running ? View.VISIBLE : View.GONE);
        if (progress != null) { progress.setVisibility(app.running ? View.VISIBLE : View.GONE); progress.setMax(Math.max(1, app.total)); progress.setProgress(app.completed); }
        if (tab == 1 && shownCompleted != app.completed) { shownCompleted = app.completed; renderGallery(); }
    }

    private boolean openAi() { return prefs.getBoolean("open_ai", false); }
    private String selected(Spinner spinner) { return spinner.getSelectedItem().toString(); }
    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }
    private void toast(String message) { Toast.makeText(getApplicationContext(), message, Toast.LENGTH_LONG).show(); }
    private LinearLayout vertical() { LinearLayout v = new LinearLayout(this); v.setOrientation(LinearLayout.VERTICAL); return v; }
    private LinearLayout horizontal() { LinearLayout v = new LinearLayout(this); v.setOrientation(LinearLayout.HORIZONTAL); return v; }
    private LinearLayout.LayoutParams weighted() { LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(0, -2, 1); p.setMargins(dp(2), 0, dp(2), 0); return p; }
    private TextView text(String value, int size, int color, boolean bold) { TextView v = new TextView(this); v.setText(value); v.setTextSize(size); v.setTextColor(color); v.setPadding(0, dp(4), 0, dp(5)); if (bold) v.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL)); return v; }
    private TextView note(String value) { TextView v = text(value, 12, MUTED, false); v.setLineSpacing(dp(3), 1f); return v; }
    private TextView label(String value) { return text(value, 13, INK, true); }
    private GradientDrawable shape(int color, int radius) { GradientDrawable v = new GradientDrawable(); v.setColor(color); v.setCornerRadius(dp(radius)); return v; }
    private LinearLayout card() { LinearLayout v = vertical(); v.setPadding(dp(15), dp(13), dp(15), dp(13)); v.setBackground(shape(Color.WHITE, 20)); LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(-1, -2); p.setMargins(0, dp(5), 0, dp(8)); v.setLayoutParams(p); return v; }
    private Button button(String label, boolean primary, Runnable action) { Button v = new Button(this); v.setText(label); v.setAllCaps(false); v.setTextSize(14); v.setMinHeight(dp(48)); v.setMinimumWidth(dp(48)); v.setTextColor(primary ? Color.WHITE : GREEN); v.setBackgroundTintList(ColorStateList.valueOf(primary ? GREEN : Color.rgb(237, 241, 233))); v.setOnClickListener(x -> action.run()); return v; }
    private void styleField(EditText v) { v.setTextColor(INK); v.setHintTextColor(MUTED); v.setMinHeight(dp(52)); v.setPadding(dp(12), dp(11), dp(12), dp(11)); GradientDrawable bg = shape(BG, 10); bg.setStroke(dp(1), Color.rgb(226, 229, 219)); v.setBackground(bg); LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(-1, -2); p.setMargins(0, dp(3), 0, dp(6)); v.setLayoutParams(p); }
    private EditText field(String hint, String content, boolean multiline) { EditText v = new EditText(this); v.setTextSize(15); v.setHint(hint); v.setSingleLine(!multiline); v.setGravity(Gravity.TOP | Gravity.START); if (multiline) v.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES); styleField(v); v.setText(content); return v; }
    private Spinner selector(String[] choices, String selected) { Spinner v = new Spinner(this); ArrayAdapter<String> adapter = new ArrayAdapter<>(this, android.R.layout.simple_spinner_item, choices); adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item); v.setAdapter(adapter); v.setMinimumHeight(dp(48)); v.setBackgroundTintList(ColorStateList.valueOf(GREEN)); v.setSelection(Math.max(0, Arrays.asList(choices).indexOf(selected))); return v; }
    private LinearLayout labelled(String title, View input) { LinearLayout v = vertical(); v.addView(label(title)); v.addView(input, new LinearLayout.LayoutParams(-1, dp(52))); return v; }
    private CheckBox checkbox(String title, boolean checked) { CheckBox v = new CheckBox(this); v.setText(title); v.setTextSize(14); v.setTextColor(INK); v.setMinHeight(dp(48)); v.setChecked(checked); v.setButtonTintList(ColorStateList.valueOf(GREEN)); return v; }
}
