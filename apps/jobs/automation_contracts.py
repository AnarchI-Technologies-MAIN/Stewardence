"""Disabled Automation collection seam, ready for adversarial adapter work.

No credential, raw financial payload, URL or write operation crosses this port.
An interface and passing admission tests do not establish a shipped collector.
"""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol
from uuid import UUID
from .contracts import BranchProfile


class ProviderReadOperation(str,Enum):
    QUICKBOOKS_COMPANY='quickbooks.sandbox.company_info'
    QUICKBOOKS_PROFIT_LOSS='quickbooks.sandbox.profit_loss'
    MICROSOFT_ORGANIZATION='microsoft.organization'
    MICROSOFT_PERMISSIONS='microsoft.permission_inventory'
    XERO_ACCOUNTS='xero.demo.accounts'
    XERO_PROFIT_LOSS='xero.demo.profit_loss'


@dataclass(frozen=True)
class CollectionRequest:
    organization_id:UUID
    connection_id:UUID
    operation:ProviderReadOperation
    branch_profile:BranchProfile
    credential_generation:int
    nonce:UUID
    requested_at:datetime

    def __post_init__(self):
        if not all(isinstance(v,UUID) for v in (self.organization_id,self.connection_id,self.nonce)):
            raise ValueError('Typed scoped collection identities required')
        if not isinstance(self.operation,ProviderReadOperation) or not isinstance(self.branch_profile,BranchProfile):
            raise ValueError('Registered read operation and invariant required')
        if type(self.credential_generation) is not int or self.credential_generation<1:
            raise ValueError('Positive credential generation required')
        if not isinstance(self.requested_at,datetime) or self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError('Collection time requires timezone')


@dataclass(frozen=True)
class CollectionResult:
    organization_id:UUID
    connection_id:UUID
    operation:ProviderReadOperation
    credential_generation:int
    nonce:UUID
    artifact_receipt_id:UUID|None
    status:str
    coverage:str

    def __post_init__(self):
        if not all(isinstance(v,UUID) for v in (self.organization_id,self.connection_id,self.nonce)):
            raise ValueError('Typed scoped response identities required')
        if not isinstance(self.operation,ProviderReadOperation) or type(self.credential_generation) is not int or self.credential_generation<1:
            raise ValueError('Registered response operation and generation required')
        if self.artifact_receipt_id is not None and not isinstance(self.artifact_receipt_id,UUID):
            raise ValueError('Typed artifact receipt required')

    def admit_for(self,request:CollectionRequest):
        if any(getattr(self,key)!=getattr(request,key) for key in
            ('organization_id','connection_id','operation','credential_generation','nonce')):
            raise ValueError('Collection response binding failed')
        if self.status not in {'collected','partial','unavailable','revoked'} or self.coverage not in {'partial','known_scope','unknown'}:
            raise ValueError('Unsupported collection outcome')
        if self.status in {'collected','partial'} and not isinstance(self.artifact_receipt_id,UUID):
            raise ValueError('Collected evidence requires a resolvable receipt')
        if self.status in {'unavailable','revoked'} and self.artifact_receipt_id is not None:
            raise ValueError('Unavailable collection cannot claim new evidence')
        if self.status in {'unavailable','revoked'} and self.coverage!='unknown':
            raise ValueError('Unavailable collection coverage is unknown')
        if self.status=='partial' and self.coverage=='known_scope':
            raise ValueError('Partial collection cannot claim complete known scope')
        return self


class AutomationCollectorPort(Protocol):
    """Broker implements authentication, scope, replay/nonce and generation checks.

    Returned artifact references still require tenant/integrity/retention admission
    in the shared deterministic pipeline; UUID shape is not authority.
    """
    def collect(self,request:CollectionRequest)->CollectionResult: ...
