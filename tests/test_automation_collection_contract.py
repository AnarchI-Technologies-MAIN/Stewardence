from dataclasses import replace
from datetime import datetime,UTC
from uuid import uuid4
import pytest
from apps.jobs.contracts import BranchProfile
from apps.jobs.automation_contracts import CollectionRequest,CollectionResult,ProviderReadOperation


def request():
    return CollectionRequest(uuid4(),uuid4(),ProviderReadOperation.XERO_ACCOUNTS,BranchProfile.BUSINESS,1,uuid4(),datetime.now(UTC))


@pytest.mark.parametrize('field',['organization_id','connection_id','operation','credential_generation','nonce'])
def test_cross_scope_stale_generation_or_replay_response_is_rejected(field):
    r=request()
    result=CollectionResult(r.organization_id,r.connection_id,r.operation,r.credential_generation,r.nonce,uuid4(),'collected','partial')
    wrong={'organization_id':uuid4(),'connection_id':uuid4(),'operation':ProviderReadOperation.MICROSOFT_ORGANIZATION,
        'credential_generation':2,'nonce':uuid4()}[field]
    with pytest.raises(ValueError): replace(result,**{field:wrong}).admit_for(r)


def test_unavailable_collection_preserves_unknown_and_cannot_forge_evidence():
    r=request()
    result=CollectionResult(r.organization_id,r.connection_id,r.operation,1,r.nonce,None,'unavailable','unknown')
    assert result.admit_for(r).coverage=='unknown'
    with pytest.raises(ValueError): replace(result,artifact_receipt_id=uuid4()).admit_for(r)
    with pytest.raises(ValueError): replace(result,status='collected').admit_for(r)


def test_writes_urls_and_boolean_generation_are_not_admitted():
    r=request()
    with pytest.raises(ValueError): replace(r,operation='xero.invoice.create')
    with pytest.raises(ValueError): replace(r,connection_id='https://credential:secret@example.invalid/')
    with pytest.raises(ValueError): replace(r,credential_generation=True)
    result=CollectionResult(r.organization_id,r.connection_id,r.operation,1,r.nonce,None,'unavailable','unknown')
    with pytest.raises(ValueError): replace(result,credential_generation=True)
    with pytest.raises(ValueError): replace(result,operation=r.operation.value)
    with pytest.raises(ValueError): replace(result,coverage='known_scope').admit_for(r)
