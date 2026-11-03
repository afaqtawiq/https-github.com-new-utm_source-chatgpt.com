package com.afaaqtuwaiq.naqliat;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.net.Uri;
import android.os.Bundle;
import android.text.InputType;
import android.util.Base64;
import android.view.Gravity;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/** Sends a Naqliat load screenshot to the Afaq system; the server reads the Arabic text with Claude. */
public class MainActivity extends Activity {
    private EditText server;
    private EditText token;
    private TextView status;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL); box.setPadding(36,48,36,36); box.setGravity(Gravity.RIGHT);
        TextView title = new TextView(this); title.setText("موصل نقليات - آفاق طويق"); title.setTextSize(25); box.addView(title);
        TextView note = new TextView(this); note.setText("صوّر شاشة تفاصيل الحمولة في نقليات، ثم اضغط مشاركة واختر «موصل نقليات»، أو اختر الصورة من الزر أدناه. تصلك الحمولة في واتساب مع رمز التفاوض."); note.setTextSize(16); note.setPadding(0,24,0,24); box.addView(note);
        server = new EditText(this); server.setHint("رابط نظام آفاق طويق"); server.setInputType(InputType.TYPE_TEXT_VARIATION_URI); server.setText(prefs().getString("server", "https://gulf-logistics-ai-v7-production.up.railway.app")); box.addView(server);
        token = new EditText(this); token.setHint("رمز ربط الجهاز"); token.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD); token.setText(prefs().getString("token", "")); box.addView(token);
        Button save = new Button(this); save.setText("حفظ إعدادات الربط"); save.setOnClickListener(v -> { prefs().edit().putString("server", server.getText().toString().trim()).putString("token", token.getText().toString().trim()).apply(); Toast.makeText(this,"تم الحفظ",Toast.LENGTH_SHORT).show(); }); box.addView(save);
        Button pick = new Button(this); pick.setText("اختيار لقطة شاشة الحمولة وإرسالها"); pick.setOnClickListener(v -> startActivityForResult(new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("image/*").addCategory(Intent.CATEGORY_OPENABLE), 42)); box.addView(pick);
        status = new TextView(this); status.setTextSize(17); status.setPadding(0,28,0,0); box.addView(status);
        setContentView(box);
        handleShare(getIntent());
    }

    @Override protected void onNewIntent(Intent intent) { super.onNewIntent(intent); handleShare(intent); }

    private void handleShare(Intent intent) {
        if (intent != null && Intent.ACTION_SEND.equals(intent.getAction())) {
            Uri uri = intent.getParcelableExtra(Intent.EXTRA_STREAM);
            if (uri != null) send(uri);
        }
    }

    private android.content.SharedPreferences prefs() { return getSharedPreferences("connector", MODE_PRIVATE); }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == 42 && resultCode == RESULT_OK && data != null && data.getData() != null) send(data.getData());
    }

    private void show(String text) { runOnUiThread(() -> { status.setText(text); Toast.makeText(this, text, Toast.LENGTH_LONG).show(); }); }

    private void send(Uri uri) {
        show("جارٍ إرسال الصورة وقراءتها…");
        new Thread(() -> { try {
            String base = prefs().getString("server","").replaceAll("/+$",""); String key = prefs().getString("token","");
            if (base.isEmpty() || key.isEmpty()) { show("أكمل إعدادات الربط أولًا"); return; }
            Bitmap bitmap; try (InputStream in = getContentResolver().openInputStream(uri)) { bitmap = BitmapFactory.decodeStream(in); }
            if (bitmap == null) { show("تعذر فتح الصورة"); return; }
            int longest = Math.max(bitmap.getWidth(), bitmap.getHeight());
            if (longest > 1800) { float s = 1800f / longest; bitmap = Bitmap.createScaledBitmap(bitmap, Math.round(bitmap.getWidth()*s), Math.round(bitmap.getHeight()*s), true); }
            ByteArrayOutputStream jpg = new ByteArrayOutputStream(); bitmap.compress(Bitmap.CompressFormat.JPEG, 85, jpg);
            JSONObject json = new JSONObject(); json.put("image_base64", Base64.encodeToString(jpg.toByteArray(), Base64.NO_WRAP)); json.put("mime", "image/jpeg");
            HttpURLConnection c = (HttpURLConnection) new URL(base + "/api/v7/naqliat/screenshot").openConnection();
            c.setRequestMethod("POST"); c.setConnectTimeout(20000); c.setReadTimeout(90000); c.setDoOutput(true);
            c.setRequestProperty("Content-Type","application/json; charset=utf-8"); c.setRequestProperty("Authorization","Bearer " + key);
            try (OutputStream os = c.getOutputStream()) { os.write(json.toString().getBytes(StandardCharsets.UTF_8)); }
            int code = c.getResponseCode();
            InputStream body = code < 400 ? c.getInputStream() : c.getErrorStream();
            String text = ""; if (body != null) { ByteArrayOutputStream b = new ByteArrayOutputStream(); byte[] buf = new byte[4096]; int n; while ((n = body.read(buf)) > 0) b.write(buf, 0, n); text = b.toString("UTF-8"); }
            c.disconnect();
            String message = code == 401 ? "رمز الربط غير صحيح" : "تعذر الإرسال: " + code;
            try { JSONObject r = new JSONObject(text); if (r.has("message")) message = r.getString("message"); } catch (Exception ignored) {}
            show(message);
        } catch (Exception e) { show("تعذر الاتصال بنظام آفاق طويق"); } }).start();
    }
}
