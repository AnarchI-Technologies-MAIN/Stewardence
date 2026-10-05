"""Bounded private synthetic object probe; no app deployment/customer mutation."""
import json,shlex,subprocess
from pathlib import Path
from datetime import datetime,UTC
from preserve_source import SSH
from inspect_storage_runtime import PROGRAM as INSPECT

PROGRAM=INSPECT[:INSPECT.index("result={'backend'")]+r'''
import uuid,hashlib,httpx
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from botocore.exceptions import ClientError
c=boto3.client('s3',endpoint_url=settings.REPORTS_BUCKET_ENDPOINT,region_name=settings.REPORTS_BUCKET_REGION,
 aws_access_key_id=settings.REPORTS_BUCKET_ACCESS_KEY_ID,aws_secret_access_key=settings.REPORTS_BUCKET_SECRET_ACCESS_KEY,
 config=Config(connect_timeout=10,read_timeout=10,retries={'max_attempts':1},s3={'addressing_style':settings.REPORTS_BUCKET_URL_STYLE}))
bucket=settings.REPORTS_BUCKET_NAME
prefix='qualification/core-hardening/'+uuid.uuid4().hex+'/'
keys=[prefix+'conditional.pdf',prefix+'race.pdf']
one=b'%PDF-1.4\nsynthetic-private-qualification-one\n%%EOF'
two=b'%PDF-1.4\nsynthetic-private-qualification-two\n%%EOF'
result={'synthetic_objects_only':True,'customer_objects_modified':False,'credential_material_printed':False,
 'production_source_services_modified':False,'cleanup_confirmed':False}
try:
 c.put_object(Bucket=bucket,Key=keys[0],Body=one,ContentType='application/pdf',ACL='private',IfNoneMatch='*')
 rejected=False
 try:c.put_object(Bucket=bucket,Key=keys[0],Body=two,ContentType='application/pdf',ACL='private',IfNoneMatch='*')
 except ClientError as e:rejected=e.response.get('ResponseMetadata',{}).get('HTTPStatusCode') in (409,412)
 actual=c.get_object(Bucket=bucket,Key=keys[0])['Body'].read()
 result['existing_conditional_rejected']=rejected
 result['original_content_preserved']=actual==one
 url=c.generate_presigned_url('get_object',Params={'Bucket':bucket,'Key':keys[0]},ExpiresIn=30).split('?',1)[0]
 result['anonymous_object_status']=httpx.get(url,follow_redirects=False,timeout=10).status_code
 barrier=Barrier(2)
 def publish(content):
  barrier.wait()
  try:
   c.put_object(Bucket=bucket,Key=keys[1],Body=content,ContentType='application/pdf',ACL='private',IfNoneMatch='*')
   return {'accepted':True,'digest':hashlib.sha256(content).hexdigest()}
  except ClientError as e:return {'accepted':False,'status':e.response.get('ResponseMetadata',{}).get('HTTPStatusCode')}
 with ThreadPoolExecutor(max_workers=2) as pool:attempts=list(pool.map(publish,[one,two]))
 result['concurrent_publish_results']=attempts
 winner=c.get_object(Bucket=bucket,Key=keys[1])['Body'].read()
 result['single_winner_verified']=sum(x['accepted'] for x in attempts)==1 and any(x.get('digest')==hashlib.sha256(winner).hexdigest() for x in attempts if x['accepted'])
except Exception as e:result['probe_error_type']=type(e).__name__
finally:
 for key in keys:
  c.delete_object(Bucket=bucket,Key=key)
 result['cleanup_confirmed']=not c.list_objects_v2(Bucket=bucket,Prefix=prefix,MaxKeys=3).get('Contents')
result['conditional_storage_qualified']=all(result.get(k) is True for k in
 ('existing_conditional_rejected','original_content_preserved','single_winner_verified','cleanup_confirmed')) and result.get('anonymous_object_status') in (403,404)
print(json.dumps(result))
'''

def main():
    command='sudo -n docker exec stewardence-web /app/.venv/bin/python -c '+shlex.quote(PROGRAM)
    result=json.loads(subprocess.check_output(SSH+[command],timeout=90,text=True))
    result['verified_at']=datetime.now(UTC).isoformat()
    root=Path(__file__).resolve().parents[1]
    (root/'evidence/spaces-conditional-qualification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))
    return 0 if result['conditional_storage_qualified'] else 1

if __name__=='__main__':raise SystemExit(main())
