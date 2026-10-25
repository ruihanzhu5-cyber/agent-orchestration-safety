"""Inspect provider readiness offline; never reads credentials or sends requests."""
import argparse
import json
from pathlib import Path
from trustfork.runtime.dynamic.common import read_json,DynamicError,write_json
from trustfork.runtime.dynamic.schema import validate_bindings
from trustfork.runtime.dynamic.provider import resolve_provider


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bindings',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();config=read_json(a.bindings)
    result=validate_bindings(config,formal=False);errors={}
    for alias in ('gpt4o','deepseekflash'):
        try:resolve_provider(config,alias)
        except DynamicError as e:errors[alias]=e.record()
    report={'mode':config['mode'],'real_api_enabled':config['real_api_enabled'],'binding_check':result,
        'provider_errors':errors,'execution_limits_configured':config.get('execution_limits') is not None,
        'credentials_read':False,'requests_sent':0,'formal_ready':False}
    write_json(a.out,report);print(json.dumps(report,indent=2))


if __name__=='__main__':main()
