"""Read-only raster qualification of the actual exported fixture PDF."""
import hashlib
import json
from importlib.metadata import version
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'evidence/pdf-visual-tools-20261004'))
import pypdfium2 as pdfium


def main():
    directory=Path(sys.argv[1]).resolve(strict=True)
    directory.relative_to((ROOT/'evidence').resolve())
    pdf_path=directory/'review-pack-delivery.pdf'
    context_path=directory/'review-pack-delivery-context.json'
    pdf_hash=hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    output=directory/'delivery-visual-qualified'
    output.mkdir()
    pages=[]
    with pdfium.PdfDocument(str(pdf_path)) as document:
        for index in range(len(document)):
            page=document[index]
            bitmap=page.render(scale=1.5)
            image=bitmap.to_pil()
            path=output/f'page-{index+1:02d}.png'
            image.save(path)
            pages.append({'page':index+1,'file':path.name,'width':image.width,'height':image.height,
                          'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
            bitmap.close();page.close()
    receipt={'input_pdf_sha256':pdf_hash,'context_sha256':hashlib.sha256(context_path.read_bytes()).hexdigest(),
             'tool':'pypdfium2','version':version('pypdfium2'),'pages':pages,'pdf_unchanged':pdf_hash==hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
             'scope':'synthetic fixture exported from actual Chromium worker delivery; raster inspection only'}
    (output/'raster-receipt.json').write_text(json.dumps(receipt,indent=2))
    print(json.dumps({'directory':str(output),'pages':len(pages),'pdf_unchanged':receipt['pdf_unchanged']}))


if __name__=='__main__':
    main()
