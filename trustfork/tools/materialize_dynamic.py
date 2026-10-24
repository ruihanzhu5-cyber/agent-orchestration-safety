"""Source-locked case mapping and generated Docker contexts."""
import argparse
from pathlib import Path

from trustfork.runtime.dynamic.case_loader import build_catalog, materialize_case
from trustfork.runtime.dynamic.common import repo_root, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--all-cases', action='store_true', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root = repo_root()
    catalog, errata = build_catalog(root)
    write_json(root / 'trustfork/config/dynamic/cases.json', catalog)
    write_json(root / 'trustfork/config/dynamic/source_errata.json', errata)
    write_json(root / 'trustfork/config/dynamic/case_readiness.json', {k: v['readiness'] for k, v in catalog.items()})
    args.out.mkdir(parents=True, exist_ok=True)
    for key, case in catalog.items():
        if not case['errors']:
            materialize_case(case, args.out / key)
    write_json(args.out / 'mapping.json', {'mapped': len(catalog), 'blocked': {k: v['errors'] for k, v in catalog.items() if v['errors']}})
    print(f"Mapped {len(catalog)} original cases; blocked={sum(bool(c['errors']) for c in catalog.values())}")


if __name__ == '__main__':
    main()
