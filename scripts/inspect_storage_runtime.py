"""Read-only report bucket metadata; credentials stay inside deployed web."""
import json,shlex,subprocess
from pathlib import Path
from datetime import datetime,UTC
from preserve_source import SSH

PROGRAM=r'''
import django,json
django.setup()
from django.conf import settings
import boto3
from botocore.config import Config
result={'backend':settings.REPORTS_STORAGE_BACKEND,'credential_material_printed':False,'writes_performed':False}
names=['REPORTS_BUCKET_NAME','REPORTS_BUCKET_ENDPOINT','REPORTS_BUCKET_ACCESS_KEY_ID','REPORTS_BUCKET_SECRET_ACCESS_KEY']
result['required_configuration_present']=all(bool(getattr(settings,n,'')) for n in names)
if result['required_configuration_present']:
 c=boto3.client('s3',endpoint_url=settings.REPORTS_BUCKET_ENDPOINT,region_name=settings.REPORTS_BUCKET_REGION,
  aws_access_key_id=settings.REPORTS_BUCKET_ACCESS_KEY_ID,aws_secret_access_key=settings.REPORTS_BUCKET_SECRET_ACCESS_KEY,
  config=Config(connect_timeout=10,read_timeout=10,retries={'max_attempts':1},s3={'addressing_style':settings.REPORTS_BUCKET_URL_STYLE}))
 try:
  acl=c.get_bucket_acl(Bucket=settings.REPORTS_BUCKET_NAME)
  public_grants=[g for g in acl.get('Grants',[]) if g.get('Grantee',{}).get('URI','').endswith(('AllUsers','AuthenticatedUsers'))]
  result['bucket_acl_read']=True;result['public_acl_grants']=len(public_grants)
 except Exception as e: result['bucket_acl_read']=False;result['acl_error_type']=type(e).__name__
 try:
  page=c.list_objects_v2(Bucket=settings.REPORTS_BUCKET_NAME,MaxKeys=1)
  result['bounded_list_read']=True;result['objects_present']=bool(page.get('Contents'))
 except Exception as e: result['bounded_list_read']=False;result['list_error_type']=type(e).__name__
print(json.dumps(result))
'''

def main():
    command='sudo -n docker exec stewardence-web /app/.venv/bin/python -c '+shlex.quote(PROGRAM)
    result=json.loads(subprocess.check_output(SSH+[command],timeout=45,text=True))
    result['verified_at']=datetime.now(UTC).isoformat()
    root=Path(__file__).resolve().parents[1]
    (root/'evidence/storage-runtime-readonly.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))

if __name__=='__main__':main()
