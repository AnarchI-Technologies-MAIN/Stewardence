"""Catalog and effective-role proof for the renamed legacy issuer boundary."""

import pytest
from django.db import connections

pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")
HELPER = "app_private.issue_action_cards_schema1(uuid,uuid,uuid,uuid)"
WRAPPER = "app_private.issue_action_cards(uuid,uuid,uuid,uuid)"


def test_legacy_helper_exact_acl_and_all_provisioned_login_authority():
    with connections["default"].cursor() as cursor:
        cursor.execute(
            "SELECT r.rolname,has_function_privilege(r.oid,%s,'EXECUTE') "
            "FROM pg_roles r WHERE r.rolcanlogin AND NOT r.rolsuper "
            "ORDER BY r.rolname",
            [HELPER],
        )
        assert dict(cursor.fetchall()) == {
            "agentledger_owner": True,
            "agentledger_app": False,
            "agentledger_worker": False,
            "agentledger_billing_admission": False,
        }
        cursor.execute(
            "SELECT rolname,pg_has_role(oid,'agentledger_owner','SET'),"
            "rolcreaterole,rolbypassrls FROM pg_roles "
            "WHERE rolcanlogin AND NOT rolsuper AND rolname<>'agentledger_owner' "
            "ORDER BY rolname"
        )
        assert cursor.fetchall() == [
            ("agentledger_app", False, False, False),
            ("agentledger_billing_admission", False, False, False),
            ("agentledger_worker", False, False, False),
        ]
        cursor.execute(
            "SELECT a.grantee,a.privilege_type,a.is_grantable "
            "FROM pg_proc p CROSS JOIN LATERAL "
            "aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a "
            "WHERE p.oid=%s::regprocedure",
            [HELPER],
        )
        acl = cursor.fetchall()
        cursor.execute("SELECT oid FROM pg_roles WHERE rolname='agentledger_owner'")
        owner_oid = cursor.fetchone()[0]
    assert acl == [(owner_oid, "EXECUTE", False)]


def test_no_stored_dependency_or_procedure_body_bypasses_legacy_fence():
    with connections["default"].cursor() as cursor:
        cursor.execute(
            "SELECT %s::regprocedure::oid,%s::regprocedure::oid", [HELPER, WRAPPER]
        )
        helper_oid, wrapper_oid = cursor.fetchone()
        assert helper_oid != wrapper_oid
        cursor.execute(
            "SELECT d.classid::regclass::text,d.objid,"
            "pg_describe_object(d.classid,d.objid,d.objsubid) "
            "FROM pg_depend d WHERE d.refclassid='pg_proc'::regclass "
            "AND d.refobjid=%s ORDER BY d.classid,d.objid,d.objsubid",
            [helper_oid],
        )
        dependencies = cursor.fetchall()
        assert all(
            catalog == "pg_proc" and object_oid == wrapper_oid
            for catalog, object_oid, description in dependencies
        ), dependencies
        # PL/pgSQL textual calls need not register an OID dependency. Audit
        # procedure source separately; stored SQL/view/trigger OIDs are above.
        cursor.execute(
            "SELECT p.oid,p.oid::regprocedure::text FROM pg_proc p "
            "JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname IN ('app_private','public') "
            "AND p.prosrc LIKE '%%issue_action_cards_schema1%%' ORDER BY p.oid"
        )
        references = cursor.fetchall()
        assert references == [(wrapper_oid, WRAPPER)]
