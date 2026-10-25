"""Source-locked case mapping and generated Docker contexts."""
import argparse
from pathlib import Path

from trustfork.runtime.dynamic.case_loader import build_catalog, materialize_case
from trustfork.runtime.dynamic.common import repo_root, write_json,read_json,digest,DynamicError


def preserve_readiness(catalog,previous):
    """Static materialization cannot erase or invent measured runtime evidence."""
    result={}
    if set(previous)-set(catalog):raise DynamicError('readiness_case_drift','Unexpected prior case IDs')
    for key,case in catalog.items():
        prior=previous.get(key,{})
        for field,expected in [('deployed_asset_hash',case['deployed_asset_hash']),
                ('source_revision',case['source_revision']),('source_card_sha256',case['scenario_card_sha256']),
                ('metadata_sha256',case['metadata_sha256'])]:
            if field in prior and prior[field]!=expected:raise DynamicError('readiness_source_drift',key+':'+field)
        record={**case['readiness'],**prior}
        for field in ('mapped','assets','public_packet'):record[field]=case['readiness'][field]
        result[key]=record
    return result


def verify_frozen_mapping(path,value):
    if path.exists() and digest(read_json(path))!=digest(value):
        raise DynamicError('frozen_mapping_drift','Refuse to replace a frozen source catalog/errata mapping')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--all-cases', action='store_true', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root = repo_root()
    catalog, errata = build_catalog(root)
    for name,value in [('cases.json',catalog),('source_errata.json',errata)]:
        verify_frozen_mapping(root/'trustfork/config/dynamic'/name,value)
    readiness_path=root/'trustfork/config/dynamic/case_readiness.json'
    readiness=preserve_readiness(catalog,read_json(readiness_path) if readiness_path.exists() else {})
    write_json(root / 'trustfork/config/dynamic/cases.json', catalog)
    write_json(root / 'trustfork/config/dynamic/source_errata.json', errata)
    write_json(readiness_path, readiness)
    args.out.mkdir(parents=True, exist_ok=True)
    for key, case in catalog.items():
        if not case['errors']:
            materialize_case(case, args.out / key)
    write_json(args.out / 'mapping.json', {'mapped': len(catalog), 'blocked': {k: v['errors'] for k, v in catalog.items() if v['errors']}})
    print(f"Mapped {len(catalog)} original cases; blocked={sum(bool(c['errors']) for c in catalog.values())}")


if __name__ == '__main__':
    main()
