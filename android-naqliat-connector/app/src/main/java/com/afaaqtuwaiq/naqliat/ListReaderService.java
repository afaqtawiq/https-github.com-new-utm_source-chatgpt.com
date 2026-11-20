package com.afaaqtuwaiq.naqliat;

import android.accessibilityservice.AccessibilityService;
import android.content.SharedPreferences;
import android.os.Handler;
import android.os.Looper;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/**
 * v0.4 — reads the TEXT of the load list the owner has open in the Naqliat driver app (com.naqliat.carrier only)
 * and scrolls the list a few pages per round. Read-only: it never taps a load, calls, books or types anything.
 * The server splits the text into loads; خالد sends one summary of the new ones on WhatsApp.
 */
public class ListReaderService extends AccessibilityService {
    static final String PKG = "com.naqliat.carrier";
    private final Handler handler = new Handler(Looper.getMainLooper());
    private String lastSent = "";
    private long roundStart = 0;
    private int pages = 0;
    private final Runnable capture = this::captureNow;
    private final Runnable newRound = this::startRound;

    private SharedPreferences prefs() { return getSharedPreferences("connector", MODE_PRIVATE); }
    private boolean auto() { return prefs().getBoolean("auto_list", false); }
    private int maxPages() { return Math.max(1, Math.min(10, prefs().getInt("pages", 3))); }
    private long intervalMs() { return Math.max(15, Math.min(240, prefs().getInt("interval", 60))) * 60000L; }

    @Override protected void onServiceConnected() { handler.postDelayed(newRound, 60000); }

    @Override public void onAccessibilityEvent(AccessibilityEvent event) {
        if (!auto() || event == null || event.getPackageName() == null || !PKG.contentEquals(event.getPackageName())) return;
        handler.removeCallbacks(capture);
        handler.postDelayed(capture, 1500);
    }

    @Override public void onInterrupt() { }

    private AccessibilityNodeInfo naqliatRoot() {
        AccessibilityNodeInfo root = getRootInActiveWindow();
        return root != null && root.getPackageName() != null && PKG.contentEquals(root.getPackageName()) ? root : null;
    }

    private void captureNow() {
        AccessibilityNodeInfo root = naqliatRoot();
        if (root == null) return;
        StringBuilder sb = new StringBuilder();
        collect(root, sb, 0);
        String text = sb.toString().trim();
        // A list screen shows several cards (several «طن»); a single details screen is left to the share flow.
        if (text.length() < 40 || count(text, "طن") < 2) return;
        if (!text.equals(lastSent)) { lastSent = text; post(text, pages); }
        long now = System.currentTimeMillis();
        if (now - roundStart > intervalMs()) { roundStart = now; pages = 0; }
        if (pages < maxPages()) {
            final AccessibilityNodeInfo scroller = findScrollable(root);
            if (scroller != null) {
                pages++;
                handler.postDelayed(() -> scroller.performAction(AccessibilityNodeInfo.ACTION_SCROLL_FORWARD), 2500);
            }
        }
    }

    /** Every interval: back to the top of the list (newest loads) and read a fresh round, if Naqliat is open. */
    private void startRound() {
        handler.postDelayed(newRound, intervalMs());
        if (!auto()) return;
        AccessibilityNodeInfo root = naqliatRoot();
        if (root == null) return;
        final AccessibilityNodeInfo scroller = findScrollable(root);
        if (scroller == null) return;
        for (int i = 0; i < maxPages() + 2; i++) {
            handler.postDelayed(() -> scroller.performAction(AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD), 700L * (i + 1));
        }
        handler.postDelayed(() -> { roundStart = System.currentTimeMillis(); pages = 0; lastSent = ""; captureNow(); },
                700L * (maxPages() + 3));
    }

    private void collect(AccessibilityNodeInfo node, StringBuilder sb, int depth) {
        if (node == null || depth > 40 || sb.length() > 28000) return;
        CharSequence t = node.getText();
        if (t == null || t.length() == 0) t = node.getContentDescription();
        if (t != null && t.length() > 0) sb.append(t).append('\n');
        for (int i = 0; i < node.getChildCount(); i++) collect(node.getChild(i), sb, depth + 1);
    }

    private AccessibilityNodeInfo findScrollable(AccessibilityNodeInfo node) {
        if (node == null) return null;
        if (node.isScrollable()) return node;
        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo found = findScrollable(node.getChild(i));
            if (found != null) return found;
        }
        return null;
    }

    private static int count(String text, String word) {
        int n = 0, i = 0;
        while ((i = text.indexOf(word, i)) >= 0) { n++; i += word.length(); }
        return n;
    }

    private void post(final String text, final int page) {
        new Thread(() -> {
            String result;
            try {
                String base = prefs().getString("server", "").replaceAll("/+$", "");
                String key = prefs().getString("token", "");
                if (base.isEmpty() || key.isEmpty()) { remember("أكمل إعدادات الربط أولًا"); return; }
                JSONObject json = new JSONObject();
                json.put("text", text);
                json.put("page", page);
                HttpURLConnection c = (HttpURLConnection) new URL(base + "/api/v7/naqliat/list").openConnection();
                c.setRequestMethod("POST"); c.setConnectTimeout(20000); c.setReadTimeout(120000); c.setDoOutput(true);
                c.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                c.setRequestProperty("Authorization", "Bearer " + key);
                try (OutputStream os = c.getOutputStream()) { os.write(json.toString().getBytes(StandardCharsets.UTF_8)); }
                int code = c.getResponseCode();
                InputStream body = code < 400 ? c.getInputStream() : c.getErrorStream();
                String out = "";
                if (body != null) { ByteArrayOutputStream b = new ByteArrayOutputStream(); byte[] buf = new byte[4096]; int n; while ((n = body.read(buf)) > 0) b.write(buf, 0, n); out = b.toString("UTF-8"); }
                c.disconnect();
                result = code == 401 ? "رمز الربط غير صحيح" : "الصفحة " + (page + 1) + ": " + code;
                try { JSONObject r = new JSONObject(out); if (r.has("message")) result = "الصفحة " + (page + 1) + ": " + r.getString("message"); } catch (Exception ignored) { }
            } catch (Exception e) { result = "تعذر الاتصال بنظام آفاق طويق"; }
            remember(result);
        }).start();
    }

    private void remember(String text) {
        prefs().edit().putString("last_list", new java.text.SimpleDateFormat("HH:mm", java.util.Locale.US).format(new java.util.Date()) + " — " + text).apply();
    }
}
