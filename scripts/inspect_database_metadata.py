"""Read migration and role metadata only; no customer records or credentials."""
import json
import shlex
import subprocess
from datetime import datetime, UTC
from pathlib import Path
from preserve_source import SSH

ROOT = Path(__file__).resolve().parents[1]
PROGRAM = '''
import django,json
django.setup()
from django.db import connection,transaction
with transaction.atomic():
 with connection.cursor() as c:
  c.execute('SET TRANSACTION READ ONLY')
  c.execute('SELECT app,name FROM django_migrations ORDER BY app,name')
  migrations=c.fetchall()
  c.execute("SELECT rolname,rolsuper,rolbypassrls,rolcanlogin FROM pg_roles WHERE rolname LIKE 'agentledger_%' ORDER BY rolname")
  roles=c.fetchall()
  c.execute("SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class JOIN pg_namespace n ON n.oid=relnamespace WHERE n.nspname='public' AND relkind='r' AND relrowsecurity ORDER BY relname")
  rls=c.fetchall()
print(json.dumps({'migrations':migrations,'roles':roles,'rls_tables':rls}))
'''

def main():
    command='sudo -n docker exec stewardence-web /app/.venv/bin/python -c '+shlex.quote(PROGRAM)
    result=subprocess.run(SSH+[command],capture_output=True,text=True)
    if result.returncode:
        raise SystemExit('Read-only database metadata inspection failed; details suppressed.')
    data=json.loads(result.stdout)
    data['verified_at']=datetime.now(UTC).isoformat()
    (ROOT/'evidence/runtime-database-metadata.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
    print(json.dumps({'applied_migrations':len(data['migrations']),'roles':data['roles'],
                      'rls_tables':len(data['rls_tables'])}))

if __name__ == '__main__':
    main()
