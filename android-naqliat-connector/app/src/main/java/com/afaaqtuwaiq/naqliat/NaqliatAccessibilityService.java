package com.afaaqtuwaiq.naqliat;

import android.accessibilityservice.AccessibilityService;
import android.content.SharedPreferences;
import android.os.Handler;
import android.os.Looper;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import android.widget.Toast;

import org.json.JSONObject;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class NaqliatAccessibilityService extends AccessibilityService {
    private String lastHash = "";
    private long lastSentAt = 0;

    @Override public void onAccessibilityEvent(AccessibilityEvent event) {
        if (event.getPackageName() == null || !"com.naqliat.carrier".contentEquals(event.getPackageName())) return;
        AccessibilityNodeInfo root = getRootInActiveWindow(); if (root == null) return;
        List<String> parts = new ArrayList<>(); collect(root, parts);
        String raw = String.join("\n", parts);
        if (!raw.contains("تفاصيل الحمولة") && !raw.contains("مطلوب من:")) return;
        String hash = Integer.toHexString(raw.hashCode()); long now = System.currentTimeMillis();
        if (hash.equals(lastHash) && now-lastSentAt < 60000) return;
        ParsedLoad load = parse(raw); if (load == null) return;
        lastHash = hash; lastSentAt = now; new Thread(() -> send(load, raw)).start();
    }

    private void collect(AccessibilityNodeInfo node, List<String> out) {
        if (node.getText() != null) { String text=node.getText().toString().trim(); if(!text.isEmpty()) out.add(text); }
        for (int i=0;i<node.getChildCount();i++) { AccessibilityNodeInfo child=node.getChild(i); if(child!=null){ collect(child,out); child.recycle(); } }
    }

    private ParsedLoad parse(String raw) {
        Matcher route = Pattern.compile("مطلوب من:\\s*([^\\n]+?)\\s*(?:إلى:|الي:)\\s*(.+?)(?:\\s+الحمولة:|\\s+نوع الشاحنة:|\\n|$)").matcher(raw.replace('\u00a0',' '));
        if (!route.find()) return null;
        ParsedLoad p = new ParsedLoad(); p.origin=route.group(1).trim(); p.destination=route.group(2).trim();
        Matcher distance=Pattern.compile("([0-9٠-٩]+)\\s*Km",Pattern.CASE_INSENSITIVE).matcher(raw); if(distance.find()) p.distance=arabicNumber(distance.group(1));
        Matcher weight=Pattern.compile("([0-9٠-٩]+(?:[.,][0-9٠-٩]+)?)\\s*طن").matcher(raw); if(weight.find()) p.weight=Double.parseDouble(arabicDigits(weight.group(1)).replace(',','.'));
        Matcher vehicle=Pattern.compile("نوع الشاحنة:\\s*(.+?)(?:\\s+حوالي|\\s+الدفع|\\n|$)").matcher(raw); if(vehicle.find()) p.vehicle=vehicle.group(1).trim();
        return p;
    }

    private String arabicDigits(String value){ return value.replace('٠','0').replace('١','1').replace('٢','2').replace('٣','3').replace('٤','4').replace('٥','5').replace('٦','6').replace('٧','7').replace('٨','8').replace('٩','9'); }
    private int arabicNumber(String value){ return Integer.parseInt(arabicDigits(value)); }

    private void send(ParsedLoad p, String raw) {
        try {
            SharedPreferences prefs=getSharedPreferences("connector",MODE_PRIVATE); String base=prefs.getString("server","").replaceAll("/+$",""); String token=prefs.getString("token","");
            if(base.isEmpty() || token.isEmpty()) { toast("أكمل إعدادات موصل نقليات"); return; }
            JSONObject json=new JSONObject(); json.put("origin",p.origin); json.put("destination",p.destination); if(p.distance!=null)json.put("distance_km",p.distance); if(p.weight!=null)json.put("weight_tons",p.weight); json.put("vehicle_type",p.vehicle); json.put("description",raw); json.put("raw_text",raw); json.put("capture_method","android_accessibility");
            HttpURLConnection c=(HttpURLConnection)new URL(base+"/api/v7/naqliat/loads").openConnection(); c.setRequestMethod("POST"); c.setConnectTimeout(10000); c.setReadTimeout(10000); c.setDoOutput(true); c.setRequestProperty("Content-Type","application/json; charset=utf-8"); c.setRequestProperty("Authorization","Bearer "+token);
            try(OutputStream os=c.getOutputStream()){os.write(json.toString().getBytes(StandardCharsets.UTF_8));}
            int code=c.getResponseCode(); c.disconnect(); toast(code>=200&&code<300?"تم التقاط الحمولة":"تعذر إرسال الحمولة: "+code);
        } catch(Exception e){ toast("تعذر الاتصال بنظام آفاق طويق"); }
    }
    private void toast(String text){ new Handler(Looper.getMainLooper()).post(() -> Toast.makeText(this,text,Toast.LENGTH_SHORT).show()); }
    @Override public void onInterrupt() {}
    private static class ParsedLoad { String origin,destination,vehicle=""; Integer distance; Double weight; }
}
