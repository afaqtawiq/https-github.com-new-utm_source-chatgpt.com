"""Package the approved cinematic Jeddah campaign artwork as a clickable PDF.

Built-in image generation: navy/gold port at sunset, four logistics services,
Arabic headline and exact official contact details. JPEG source is committed.
"""
from pathlib import Path
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab import rl_config
rl_config.useA85 = 0
ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / 'app/assets/afaaq-jeddah-brochure.jpg'
OUT = ROOT / 'app/assets/afaaq-jeddah-brochure.pdf'
with Image.open(ART) as artwork:
    width, height = artwork.size
W = 595.276
H = W * height / width
c = canvas.Canvas(str(OUT), pagesize=(W, H), pageCompression=1)
c.setTitle('آفاق طويق | شحناتك في ميناء جدة — نكمل رحلتها')
c.setAuthor('آفاق طويق')
c.setSubject('Jeddah port logistics | afaq@shodai.cc | +966530130435 | www.afaqtwiq.com')
c.drawImage(str(ART), 0, 0, width=W, height=H)
c.linkURL('https://wa.me/966530130435', (W*.20,H*.105,W*.80,H*.18), relative=0, thickness=0)
c.linkURL('https://wa.me/966530130435', (W*.04,H*.025,W*.34,H*.085), relative=0, thickness=0)
c.linkURL('mailto:afaq@shodai.cc', (W*.37,H*.025,W*.65,H*.085), relative=0, thickness=0)
c.linkURL('https://www.afaqtwiq.com/', (W*.69,H*.025,W*.97,H*.085), relative=0, thickness=0)
c.showPage()
c.save()
print(OUT)
