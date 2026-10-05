"""Schema-only restore comparison; contains no customer rows or credentials."""

SQL = """SELECT json_build_object(
'roles',(SELECT json_agg(json_build_array(rolname,rolsuper,rolbypassrls,rolinherit) ORDER BY rolname)
 FROM pg_roles WHERE rolname IN ('agentledger_owner','agentledger_app','agentledger_worker','agentledger_billing_admission')),
'tables',(SELECT json_agg(json_build_array(n.nspname,c.relname,c.relrowsecurity,c.relforcerowsecurity,pg_get_userbyid(c.relowner),c.relacl::text) ORDER BY n.nspname,c.relname)
 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('public','app_private') AND c.relkind IN ('r','p')),
'policies',(SELECT json_agg(json_build_array(n.nspname,c.relname,p.polname,p.polcmd,p.polpermissive,
 (SELECT json_agg(CASE WHEN role=0 THEN 'PUBLIC' ELSE pg_get_userbyid(role) END ORDER BY CASE WHEN role=0 THEN 'PUBLIC' ELSE pg_get_userbyid(role) END) FROM unnest(p.polroles) role),
 pg_get_expr(p.polqual,p.polrelid),pg_get_expr(p.polwithcheck,p.polrelid)) ORDER BY n.nspname,c.relname,p.polname)
 FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('public','app_private')),
'functions',(SELECT json_agg(json_build_array(n.nspname,p.proname,pg_get_function_identity_arguments(p.oid),pg_get_userbyid(p.proowner),p.prosecdef,p.proacl::text,p.proconfig,md5(pg_get_functiondef(p.oid))) ORDER BY n.nspname,p.proname,pg_get_function_identity_arguments(p.oid))
 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname IN ('public','app_private') AND p.prokind IN ('f','p')),
'triggers',(SELECT json_agg(json_build_array(n.nspname,c.relname,t.tgname,t.tgenabled,pg_get_triggerdef(t.oid)) ORDER BY n.nspname,c.relname,t.tgname)
 FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE NOT t.tgisinternal AND n.nspname IN ('public','app_private')),
'migrations',(SELECT json_agg(json_build_array(app,name) ORDER BY app,name) FROM django_migrations));"""
