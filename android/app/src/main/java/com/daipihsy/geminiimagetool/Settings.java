package com.daipihsy.geminiimagetool;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

final class Settings {
    private static final String ALIAS = "gemini_image_api_key";
    private Settings() {}
    static SharedPreferences prefs(Context context) { return context.getSharedPreferences("settings", Context.MODE_PRIVATE); }

    static String loadKey(Context context) {
        SharedPreferences p = prefs(context);
        String value = p.getString("encrypted_key", "");
        if (!p.getBoolean("remember_key", false) || value.isEmpty()) return "";
        try {
            String[] parts = value.split(":", 2);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, Base64.decode(parts[0], Base64.NO_WRAP)));
            return new String(cipher.doFinal(Base64.decode(parts[1], Base64.NO_WRAP)), StandardCharsets.UTF_8);
        } catch (Exception ignored) { return ""; }
    }

    static void saveKey(Context context, String apiKey, boolean remember) throws Exception {
        SharedPreferences.Editor edit = prefs(context).edit().putBoolean("remember_key", remember);
        if (!remember || apiKey.isEmpty()) {
            if (!edit.remove("encrypted_key").commit()) throw new IllegalStateException("无法保存设置");
            return;
        }
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, key());
        String value = Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP) + ":" +
            Base64.encodeToString(cipher.doFinal(apiKey.getBytes(StandardCharsets.UTF_8)), Base64.NO_WRAP);
        if (!edit.putString("encrypted_key", value).commit()) throw new IllegalStateException("无法保存密钥");
    }

    private static SecretKey key() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore"); store.load(null);
        if (store.containsAlias(ALIAS)) return (SecretKey) store.getKey(ALIAS, null);
        KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());
        return generator.generateKey();
    }
}
