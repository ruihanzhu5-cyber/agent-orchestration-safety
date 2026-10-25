"""Write a passive per-card inventory and per-run actual opportunity reports offline."""
import argparse,json
from pathlib import Path
from trustfork.runtime.dynamic.common import config_dir,read_json,write_json
from trustfork.scoring.risk_opportunity import case_information_inventory,build_opportunity_report
from trustfork.scoring.dynamic_pipeline import load_events
from trustfork.scoring.visibility_index import build_visibility_index


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    a.out.mkdir(parents=True,exist_ok=True)
    inventory=[case_information_inventory(c) for c in read_json(config_dir()/'cases.json').values()]
    write_json(a.out/'case_information_inventory.json',{'version':'case-information-v1','cards':inventory,'formal_ready':False})
    reports=[]
    for path in sorted(a.input.rglob('run.json')) if a.input else []:
        run=read_json(path)
        if run['run_status']!='valid_behavior':continue
        events=load_events(path.parent,run);visibility=build_visibility_index(events)
        report=build_opportunity_report(run,events,visibility)
        relative=path.relative_to(a.input).parent
        write_json(a.out/relative/'opportunity_report.json',report);reports.append({'run_id':run['run_id'],'path':relative.as_posix()})
    write_json(a.out/'index.json',{'cards':len(inventory),'runs':reports,'formal_ready':False})
    print(json.dumps({'cards':len(inventory),'runs':len(reports),'formal_ready':False}))


if __name__=='__main__':main()
