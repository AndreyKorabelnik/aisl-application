"""CLI read-only adapter for GLM function/tool calls."""
from __future__ import annotations

import argparse
import json
import os
import sys

from .catalog import tool_definitions
from .gateway import Gateway
from .tools import DataMartsTools


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='aisldm')
    parser.add_argument('--base-url', default=os.getenv('AISL_BASE_URL', 'http://127.0.0.1:8080'))
    parser.add_argument('--system')
    parser.add_argument('--revision')
    parser.add_argument('--repo-id')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('tools-json')
    for name in ('search_objects', 'get_object_details', 'find_change_locations', 'get_dependencies',
                 'get_attribute_lineage', 'get_calculation_logic', 'get_evidence'):
        p = commands.add_parser(name)
        if name == 'search_objects':
            p.add_argument('--query', required=True)
            p.add_argument('--limit', type=int, default=30)
            p.add_argument('--no-fuzzy', action='store_true')
        elif name == 'get_calculation_logic':
            p.add_argument('--query-id', required=True)
            p.add_argument('--scope-id')
        else:
            p.add_argument('--relation', required=True)
            if name not in ('get_object_details',):
                p.add_argument('--column')
    args = parser.parse_args(argv)
    if args.command == 'tools-json':
        print(json.dumps(tool_definitions(), ensure_ascii=False, indent=2))
        return 0
    if not args.system or not args.revision:
        parser.error('--system and --revision are required for all research operations')
    tools = DataMartsTools(Gateway(args.base_url, args.system, args.revision))
    try:
        if args.command == 'search_objects':
            result = tools.search_objects(query=args.query, limit=args.limit, include_fuzzy=not args.no_fuzzy)
        elif args.command == 'get_object_details':
            result = tools.get_object_details(relation=args.relation)
        elif args.command == 'get_calculation_logic':
            result = tools.get_calculation_logic(query_id=args.query_id, repo_id=args.repo_id or '', scope_id=args.scope_id)
        else:
            kw = {'relation': args.relation, 'repo_id': args.repo_id}
            if args.column:
                kw['column'] = args.column
            result = getattr(tools, args.command)(**kw)
        print(json.dumps({'system_id': args.system, 'revision_id': args.revision,
                          'tool': args.command, 'result': result}, ensure_ascii=False, indent=2, default=str))
        return 0
    except Exception as exc:
        print(json.dumps({'error': f'{type(exc).__name__}: {exc}', 'tool': args.command}, ensure_ascii=False), file=sys.stderr)
        return 2
    finally:
        tools.close()


if __name__ == '__main__':
    raise SystemExit(main())
