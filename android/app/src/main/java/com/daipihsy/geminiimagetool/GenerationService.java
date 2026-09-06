package com.daipihsy.geminiimagetool;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.IBinder;
import java.util.concurrent.CancellationException;

public final class GenerationService extends Service {
    static final String CANCEL = "cancel_generation";
    private static final String CHANNEL = "generation";
    private static final int ID = 17;
    private ImageApp app;
    private ApiClient client;
    private boolean started;

    @Override public void onCreate() {
        super.onCreate(); app = (ImageApp) getApplication();
        getSystemService(NotificationManager.class).createNotificationChannel(
            new NotificationChannel(CHANNEL, "图像生成进度", NotificationManager.IMPORTANCE_LOW));
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && CANCEL.equals(intent.getAction())) {
            if (client != null) client.cancel();
            app.update("正在停止…已发送的请求可能仍会计费");
            if (!started) { app.running = false; stopSelf(); }
            return START_NOT_STICKY;
        }
        if (started) return START_NOT_STICKY;
        startForeground(ID, notification("准备生成…", true), ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
        ApiClient.Options options = app.pending; app.pending = null;
        if (options == null) { app.running = false; stopForeground(STOP_FOREGROUND_REMOVE); stopSelf(); return START_NOT_STICKY; }
        started = true; app.running = true; app.completed = 0; app.total = options.count;
        client = new ApiClient(); app.activeClient = client;
        Settings.prefs(this).edit().putBoolean("task_pending", true).apply();
        new Thread(() -> runBatch(options), "image-generation").start();
        return START_NOT_STICKY;
    }

    private void runBatch(ApiClient.Options options) {
        try {
            Store.addPrompt(this, options.prompt);
            for (int i = 0; i < options.count; i++) {
                String text = "正在生成 " + (i + 1) + " / " + options.count + "…";
                app.update(text); notifyProgress(text, true);
                Store.save(this, client.generate(options, i), options, i);
                app.completed = i + 1; app.notifyChanged();
            }
            app.update("已完成 " + app.completed + " 张，打开「作品」查看");
        } catch (CancellationException e) {
            app.update("已停止，已完成的 " + app.completed + " 张图片已保留。已发出的请求可能仍会计费。");
        } catch (OutOfMemoryError e) {
            app.update("手机内存不足，已停止。请减少参考图或降低分辨率。");
        } catch (Exception e) {
            app.update("本批已完成 " + app.completed + " 张，剩余任务已停止。\n" + Protocol.redact(e.getMessage(), options.key));
        } finally {
            options.key = ""; app.activeClient = null; app.running = false;
            Settings.prefs(this).edit().putBoolean("task_pending", false).apply(); app.notifyChanged();
            stopForeground(STOP_FOREGROUND_REMOVE); notifyProgress(app.status, false); stopSelf();
        }
    }

    private Notification notification(String text, boolean ongoing) {
        Intent openIntent = new Intent(this, MainActivity.class);
        PendingIntent open = PendingIntent.getActivity(this, 0, openIntent, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        Notification.Builder builder = new Notification.Builder(this, CHANNEL).setSmallIcon(R.drawable.ic_notification)
            .setContentTitle("Gemini 图像工具").setContentText(text).setStyle(new Notification.BigTextStyle().bigText(text))
            .setContentIntent(open).setOngoing(ongoing).setOnlyAlertOnce(true).setAutoCancel(!ongoing);
        if (ongoing) {
            PendingIntent cancel = PendingIntent.getService(this, 1, new Intent(this, GenerationService.class).setAction(CANCEL), PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
            builder.setProgress(app.total, app.completed, app.total == 0).addAction(new Notification.Action.Builder(null, "停止", cancel).build());
        }
        return builder.build();
    }

    private void notifyProgress(String text, boolean ongoing) {
        try { getSystemService(NotificationManager.class).notify(ID, notification(text, ongoing)); } catch (SecurityException ignored) {}
    }

    @Override public void onTimeout(int startId, int foregroundServiceType) {
        if (client != null) client.cancel(); app.update("Android 已达到后台运行时限，已完成图片已保留");
        stopForeground(STOP_FOREGROUND_REMOVE); stopSelf();
    }
    @Override public void onDestroy() { if (client != null) client.cancel(); super.onDestroy(); }
    @Override public IBinder onBind(Intent intent) { return null; }
}
