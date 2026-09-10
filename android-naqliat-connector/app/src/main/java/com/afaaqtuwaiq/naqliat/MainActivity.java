package com.afaaqtuwaiq.naqliat;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

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
        TextView steps = new TextView(this); steps.setText("لا يحتاج التطبيق إلى صلاحية إمكانية الوصول. أدخل بيانات الحمولة أو استخدم مشاركة تفاصيل الحمولة إلى النظام عند توفرها."); steps.setTextSize(16); steps.setPadding(0,28,0,0); box.addView(steps);
        setContentView(box);
    }
    private android.content.SharedPreferences getPreferences() { return getSharedPreferences("connector", MODE_PRIVATE); }
}
