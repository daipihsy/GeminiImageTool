package com.daipihsy.geminiimagetool;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import java.io.File;
import java.io.FileNotFoundException;

/** Read-only provider granting a selected share target access to one result. */
public final class ImageProvider extends ContentProvider {
    @Override public boolean onCreate() { return true; }
    private File resolve(Uri uri) throws FileNotFoundException {
        try {
            if (uri.getPathSegments().size() != 1) throw new IllegalArgumentException();
            File file = Store.resultFile(getContext(), uri.getLastPathSegment()); if (!file.isFile()) throw new IllegalArgumentException(); return file;
        } catch (Exception e) { throw new FileNotFoundException("图片不存在"); }
    }
    @Override public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        if (!"r".equals(mode)) throw new FileNotFoundException("只支持读取");
        return ParcelFileDescriptor.open(resolve(uri), ParcelFileDescriptor.MODE_READ_ONLY);
    }
    @Override public String getType(Uri uri) { try { return ApiClient.mime(resolve(uri)); } catch (Exception e) { return "image/png"; } }
    @Override public Cursor query(Uri uri, String[] projection, String selection, String[] args, String order) {
        String[] cols = projection == null ? new String[]{OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE} : projection;
        MatrixCursor cursor = new MatrixCursor(cols);
        try {
            File file = resolve(uri); Object[] row = new Object[cols.length];
            for (int i = 0; i < cols.length; i++) { if (OpenableColumns.DISPLAY_NAME.equals(cols[i])) row[i] = file.getName(); if (OpenableColumns.SIZE.equals(cols[i])) row[i] = file.length(); }
            cursor.addRow(row);
        } catch (Exception ignored) {}
        return cursor;
    }
    @Override public Uri insert(Uri uri, ContentValues values) { throw new UnsupportedOperationException("只读"); }
    @Override public int delete(Uri uri, String selection, String[] args) { throw new UnsupportedOperationException("只读"); }
    @Override public int update(Uri uri, ContentValues values, String selection, String[] args) { throw new UnsupportedOperationException("只读"); }
}
