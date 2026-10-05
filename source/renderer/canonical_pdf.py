"""Normalize only freshly generated PDFs for replay in a pinned renderer.

Historical stored artifacts are never rewritten. Cross-version byte equality
is not claimed. Page content and accessibility structure are retained.
"""
import hashlib
from io import BytesIO
from datetime import datetime,UTC
import rfc8785
from pypdf import PdfReader,PdfWriter

PDF_ENGINE_VERSION='AL-PDF-1'

def normalize_generated_pdf(content,payload):
    reader=PdfReader(BytesIO(content),strict=True)
    if reader.is_encrypted or not reader.pages: raise ValueError('Generated PDF is invalid')
    # Fresh browser IDs/XMP are generation details, not admitted evidence.
    reader.trailer.pop('/ID',None)
    reader.trailer['/Root'].get_object().pop('/Metadata',None)
    writer=PdfWriter(clone_from=reader)
    instant=datetime.fromisoformat(payload['metadata']['assessment_date'].replace('Z','+00:00')).astimezone(UTC)
    timestamp=instant.strftime("D:%Y%m%d%H%M%S+00'00'")
    writer.metadata={'/Title':payload['title'],'/Producer':'Stewardence '+PDF_ENGINE_VERSION,
        '/CreationDate':timestamp,'/ModDate':timestamp,
        '/StewardenceReportIdentifier':payload['metadata']['report_identifier'],
        '/StewardenceContextSHA256':hashlib.sha256(rfc8785.dumps(payload)).hexdigest()}
    output=BytesIO()
    writer.write(output)
    return output.getvalue()
