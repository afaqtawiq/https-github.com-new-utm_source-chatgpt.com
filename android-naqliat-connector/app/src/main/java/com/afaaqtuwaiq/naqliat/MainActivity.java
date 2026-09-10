package com.afaaqtuwaiq.naqliat;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;
import com.google.mlkit.vision.common.InputImage;
import com.google.mlkit.vision.text.TextRecognition;
import com.google.mlkit.vision.text.latin.TextRecognizerOptions;
import org.json.JSONObject;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class MainActivity extends Activity {
    private EditText server;
    private EditText token;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL); box.setPadding(36,48,36,36); box.setGravity(Gravity.RIGHT);
        TextView title = new TextView(this); title.setText("موصل نقليات - آفاق طويق"); title.setTextSize(25); box.addView(title);
        TextView note = new TextView(this); note.setText("يقرأ التطبيق بيانات الحمولات الظاهرة داخل نقليات فقط. لا يقرأ كلمات المرور أو رموز التحقق."); note.setTextSize(16); note.setPadding(0,24,0,24); box.addView(note);
        server = new EditText(this); server.setHint("رابط نظام آفاق طويق"); server.setInputType(InputType.TYPE_TEXT_VARIATION_URI); server.setText(getPreferences().getString("server", "https://gulf-logistics-ai-v7-production.up.railway.app")); box.addView(server);
        token = new EditText(this); token.setHint("رمز ربط الجهاز"); token.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD); token.setText(getPreferences().getString("token", "")); box.addView(token);
        Button save = new Button(this); save.setText("حفظ إعدادات الربط"); save.setOnClickListener(v -> { getPreferences().edit().putString("server", server.getText().toString().trim()).putString("token", token.getText().toString().trim()).apply(); Toast.makeText(this,"تم الحفظ",Toast.LENGTH_SHORT).show(); }); box.addView(save);
        Button ocr = new Button(this); ocr.setText("اختيار لقطة شاشة واستخراج الحمولة"); ocr.setOnClickListener(v -> startActivityForResult(new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("image/*").addCategory(Intent.CATEGORY_OPENABLE), 42)); box.addView(ocr);
        TextView steps = new TextView(this); steps.setText("لا يحتاج التطبيق إلى صلاحية إمكانية الوصول. أدخل بيانات الحمولة أو استخدم مشاركة تفاصيل الحمولة إلى النظام عند توفرها."); steps.setTextSize(16); steps.setPadding(0,28,0,0); box.addView(steps);
        setContentView(box);
    }
    private android.content.SharedPreferences getPreferences() { return getSharedPreferences("connector", MODE_PRIVATE); }
    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data); if(requestCode!=42 || resultCode!=RESULT_OK || data==null) return;
        try { Uri uri=data.getData(); InputImage image=InputImage.fromFilePath(this,uri); TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS).process(image).addOnSuccessListener(r -> sendOcr(r.getText())).addOnFailureListener(e -> Toast.makeText(this,"تعذر قراءة الصورة، جرّب لقطة أوضح",Toast.LENGTH_LONG).show()); } catch(Exception e){ Toast.makeText(this,"تعذر فتح الصورة",Toast.LENGTH_SHORT).show(); }
    }
    private void sendOcr(String raw) {
        new Thread(() -> { try {
            String base=getPreferences().getString("server","").replaceAll("/+$",""); String key=getPreferences().getString("token","");
            if(base.isEmpty()||key.isEmpty()){ runOnUiThread(() -> Toast.makeText(this,"أكمل إعدادات الربط",Toast.LENGTH_LONG).show()); return; }
            String text=raw.replace('\u00a0',' ').replaceAll("\\s+"," ").trim();
            Matcher route=Pattern.compile("(?:مطلوب\\s+من|من)\\s*:?\\s*(.+?)\\s+(?:إلى|الى|إلي|الي)\\s*:?\\s*(.+?)(?=\\s+(?:الحمولة|نوع الشاحنة|الوصف|[0-9٠-٩]+\\s*طن)|$)").matcher(text);
            if(!route.find()){ runOnUiThread(() -> Toast.makeText(this,"تعذر تحديد المنشأ والوجهة من الصورة",Toast.LENGTH_LONG).show()); return; }
            Matcher weight=Pattern.compile("([0-9٠-٩]+(?:[.,][0-9٠-٩]+)?)\\s*(?:\\+\\s*)?طن").matcher(text);
            Matcher phone=Pattern.compile("(?:\\+|00)?966\\s*5(?:[\\s-]*\\d){8}").matcher(text);
            Matcher vehicle=Pattern.compile("نوع الشاحنة\\s*:?\\s*(.+?)(?=\\s+(?:حوالي|الدفع|التنزيل|$))").matcher(text);
            JSONObject json=new JSONObject(); json.put("origin",route.group(1).trim()); json.put("destination",route.group(2).trim());
            if(weight.find()) json.put("weight_tons",Double.parseDouble(arabicDigits(weight.group(1)).replace(',','.')));
            if(phone.find()) json.put("owner_phone",phone.group());
            if(vehicle.find()) json.put("vehicle_type",vehicle.group(1).trim());
            json.put("description",raw); json.put("raw_text",raw); json.put("capture_method","android_ocr");
            HttpURLConnection c=(HttpURLConnection)new URL(base+"/api/v7/naqliat/loads").openConnection(); c.setRequestMethod("POST"); c.setConnectTimeout(15000); c.setReadTimeout(15000); c.setDoOutput(true); c.setRequestProperty("Content-Type","application/json; charset=utf-8"); c.setRequestProperty("Authorization","Bearer "+key);
            try(OutputStream os=c.getOutputStream()){os.write(json.toString().getBytes(StandardCharsets.UTF_8));}
            int code=c.getResponseCode(); c.disconnect(); runOnUiThread(() -> Toast.makeText(this,code>=200&&code<300?"تم إرسال الحمولة إلى النظام":"تعذر حفظ الحمولة: "+code,Toast.LENGTH_LONG).show());
        } catch(Exception e){ runOnUiThread(() -> Toast.makeText(this,"تعذر الاتصال بالخادم",Toast.LENGTH_LONG).show()); } }).start();
    }
    private String arabicDigits(String value){ return value.replace('٠','0').replace('١','1').replace('٢','2').replace('٣','3').replace('٤','4').replace('٥','5').replace('٦','6').replace('٧','7').replace('٨','8').replace('٩','9'); }
}
