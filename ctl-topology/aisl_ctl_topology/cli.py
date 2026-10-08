from __future__ import annotations

import argparse

from .builder import build_topology
from .gateway import AislCtlGateway
from .output import write_csv, write_json, write_mermaid


def main(argv: list[str] | None = None) -> int:
    p=argparse.ArgumentParser(prog='aisl-ctl-topology',description='Compose CTL topology from pinned, published AISL revisions')
    p.add_argument('command',choices=['build'])
    p.add_argument('--aisl-base-url',required=True)
    p.add_argument('--revision',action='append',required=True,help='system_id=revision_id, repeat for each published system')
    p.add_argument('--output-json',required=True)
    p.add_argument('--output-csv',required=True)
    p.add_argument('--output-mermaid',required=True)
    args=p.parse_args(argv)
    refs=[]
    for value in args.revision:
        if '=' not in value or not all(part.strip() for part in value.split('=',1)):
            p.error('each --revision must be system_id=revision_id')
        refs.append(tuple(value.split('=',1)))
    gateway=AislCtlGateway(args.aisl_base_url)
    try:
        data=build_topology([gateway.load_revision(system,revision) for system,revision in refs])
    finally:
        gateway.close()
    write_json(data,args.output_json);write_csv(data,args.output_csv);write_mermaid(data,args.output_mermaid)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
