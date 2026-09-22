"""Reproducible one-page Arabic brochure; typography rendered with HarfBuzz/RAQM."""
from io import BytesIO
from pathlib import Path
import sys
from PIL import Image, ImageDraw, ImageFont
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'app/assets/afaaq-jeddah-brochure.pdf'
FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
BOLD = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
pdfmetrics.registerFont(TTFont('BrandLatin', FONT))
pdfmetrics.registerFont(TTFont('BrandLatinBold', BOLD))
W, H = 595.276, 841.89
OUT.parent.mkdir(parents=True, exist_ok=True)
c = canvas.Canvas(str(OUT), pagesize=(W, H))
c.setTitle('آفاق طويق | خدمات ميناء جدة الإسلامي')
c.setAuthor('آفاق طويق')

def rect(x,y,w,h,color,r=0):
    c.setFillColor(HexColor(color))
    c.roundRect(x,y,w,h,r,stroke=0,fill=1) if r else c.rect(x,y,w,h,stroke=0,fill=1)

def ar(text,x,y,size=14,color='#122C3F',bold=False):
    scale=4
    font=ImageFont.truetype(BOLD if bold else FONT, round(size*scale))
    box=font.getbbox(text,direction='rtl',language='ar')
    im=Image.new('RGBA',(box[2]-box[0]+12,box[3]-box[1]+12))
    ImageDraw.Draw(im).text((6-box[0],6-box[1]),text,font=font,fill=color,direction='rtl',language='ar')
    c.drawImage(ImageReader(im),x-im.width/scale,y,width=im.width/scale,height=im.height/scale,mask='auto')

def latin(text,x,y,size=12,color='#122C3F',bold=False):
    c.setFillColor(HexColor(color));c.setFont('BrandLatinBold' if bold else 'BrandLatin',size)
    c.drawString(x,y,text)

rect(0,0,W,H,'#F5F3ED')
rect(0,548,W,H-548,'#0B2537')
rect(553,785,5,28,'#D9B365')
ar('آفاق طويق',541,784,25,'#FFFFFF',True)
latin('AFAQ TWIQ',38,802,13,'#D9B365',True)
latin('CUSTOMS  /  TRANSPORT  /  LOGISTICS',38,783,7.3,'#A8BAC5')
ar('شحناتكم عبر ميناء جدة',558,720,29,'#FFFFFF',True)
ar('خدمات متكاملة حتى وجهتكم',558,677,24,'#D9B365',True)
ar('من وصول الشحنة إلى التخليص والنقل والتسليم.',558,642,13,'#DAE4EA')
ar('شريككم لخدمات ميناء جدة الإسلامي.',558,617,13,'#DAE4EA')

# Quiet original port line illustration, not a photograph of company assets.
c.setStrokeColor(HexColor('#537184'));c.setLineWidth(1.1)
for x,y,h in ((46,562,46),(105,562,59),(164,562,40)):
    c.line(x,y,x,y+h);c.line(x,y+h,x+62,y+h);c.line(x+21,y+h,x+21,y+18)
    c.line(x-9,y,x+10,y);c.line(x,y+h,x+43,y+h-18)
for x in range(265,540,44):
    c.rect(x,559,39,19,stroke=1,fill=0)
    for dx in (8,15,22,29):c.line(x+dx,562,x+dx,575)
c.line(36,554,558,554)

ar('حلول عملية للمستوردين والشركات',558,511,18,'#0B2537',True)
services=[
 ('التخليص الجمركي','متابعة إجراءات التخليص في ميناء جدة.'),
 ('استقبال الشحنات','تنسيق وصول الشحنة ومتابعة المستندات.'),
 ('النقل البري','ترتيب نقل البضائع إلى وجهتها داخل المملكة.'),
 ('المناولة والتحميل','تنسيق تحميل وتفريغ ومناولة البضائع.'),
 ('التخزين والحاويات','حلول التخزين وتنظيم الحاويات والساحات.'),
 ('الشحن والتسليم','ترتيبات الشحن والتوصيل إلى الوجهة النهائية.'),
]
for i,(title,desc) in enumerate(services):
    col=i%2;row=i//2;x=306 if col==0 else 36;y=401-row*92
    rect(x,y,252,79,'#FFFFFF',9)
    rect(x+233,y+48,3,17,'#D9B365')
    ar(title,x+222,y+48,15,'#0B2537',True)
    ar(desc,x+237,y+22,9.2,'#526777')

rect(36,129,522,67,'#D9B365',10)
ar('اطلب عرض سعر لشحنتك',541,164,18,'#0B2537',True)
ar('أرسل نوع البضاعة والوزن أو عدد الحاويات وموعد الوصول والوجهة.',541,140,10.1,'#0B2537')
rect(0,0,W,110,'#0B2537')
ar('واتساب',558,81,10,'#D9B365',True)
ar('البريد الإلكتروني',363,81,10,'#D9B365',True)
ar('الموقع الإلكتروني',177,81,10,'#D9B365',True)
latin('+966 530 130 435',416,56,12,'#FFFFFF',True)
latin('afaq@shodai.cc',236,56,12,'#FFFFFF',True)
latin('www.afaqtwiq.com',37,56,12,'#FFFFFF',True)
c.linkURL('https://wa.me/966530130435',(405,47,564,100),relative=0,thickness=0)
c.linkURL('mailto:afaq@shodai.cc',(230,47,380,100),relative=0,thickness=0)
c.linkURL('https://www.afaqtwiq.com/',(30,47,205,100),relative=0,thickness=0)
ar('من الحدود... إلى وجهة تجارتك',558,18,10,'#BACCD7')
latin('JEDDAH ISLAMIC PORT',37,23,8,'#BACCD7')
c.showPage();c.save()
print(OUT)
