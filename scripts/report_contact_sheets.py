"""Pair full-resolution raster pages for bounded visual inspection."""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
directory = ROOT/'evidence/report-layout-final'
for specimen in ['long-input','multi-tool','long-table']:
    pages = sorted(directory.glob(specimen+'-*.png'),key=lambda p:int(p.stem.rsplit('-',1)[1]))
    for offset in range(0,len(pages),2):
        selected = pages[offset:offset+2]
        images = [Image.open(p).convert('RGB') for p in selected]
        sheet = Image.new('RGB',(sum(p.width for p in images),max(p.height for p in images)+24),'#e6e9ef')
        x = 0
        for file,page in zip(selected,images):
            sheet.paste(page,(x,24))
            ImageDraw.Draw(sheet).text((x+12,5),file.name,fill='black')
            x += page.width
        sheet.save(directory/(specimen+'-sheet-'+str(offset//2+1)+'.png'))
print('Full-resolution paired page sheets prepared for visual inspection.')
