"""Versioned coordination interface; intentionally incompatible with pre-wait sessions."""
from .common import digest,file_hash
from pathlib import Path
VERSION='explicit-wait-v1'
def coordination_identity():
 return {'version':VERSION,'runtime_implementation_hashes':{name:file_hash(Path(__file__).with_name(name)) for name in ('scheduler.py','delegations.py','mailbox.py','membership.py','turn_outcome.py','coordination_contract.py')},'tool_definitions_hash':file_hash(Path(__file__).with_name('pi_bridge.ts')),
  'wait_precedence':'Only a successful last tool_execution_end named wait_for_update may park the actor; later work or coordination tools override it.',
  'observable_changes':'recipient messages; own/Main delegation states; public membership'}
