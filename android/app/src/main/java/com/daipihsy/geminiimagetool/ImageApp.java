package com.daipihsy.geminiimagetool;

import android.app.Application;
import android.os.Handler;
import android.os.Looper;
import java.io.File;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;

public final class ImageApp extends Application {
    public String apiKey = "";
    public volatile boolean running, importing;
    public volatile int completed, total;
    public volatile String status = "准备开始创作";
    public volatile ApiClient.Options pending;
    public volatile ApiClient activeClient;
    public final List<File> references = new ArrayList<>();
    public final List<Runnable> listeners = new CopyOnWriteArrayList<>();
    private final Handler main = new Handler(Looper.getMainLooper());

    @Override public void onCreate() {
        super.onCreate(); apiKey = Settings.loadKey(this);
        if (Settings.prefs(this).getBoolean("task_pending", false)) {
            status = "上次生成被系统中断。已完成图片仍在作品中；为避免重复扣费，本次不会自动重试。";
            Settings.prefs(this).edit().putBoolean("task_pending", false).apply();
        }
        for (String name : Settings.prefs(this).getString("reference_files", "").split("\n")) {
            if (!name.isEmpty() && !name.contains("/") && !name.contains("..")) {
                File file = new File(Store.references(this), name);
                if (file.isFile()) references.add(file);
            }
        }
    }

    public void update(String message) { status = message; notifyChanged(); }
    public void notifyChanged() { main.post(() -> { for (Runnable listener : listeners) listener.run(); }); }
    public void persistReferences() {
        List<String> names = new ArrayList<>(); for (File f : references) names.add(f.getName());
        Settings.prefs(this).edit().putString("reference_files", String.join("\n", names)).apply();
    }
}
