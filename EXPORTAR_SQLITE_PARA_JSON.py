from __future__ import annotations
import argparse, json, sqlite3
from pathlib import Path


def main() -> None:
    parser=argparse.ArgumentParser(description='Exporta um banco SQLite do ONE CRM para JSON por tabela.')
    parser.add_argument('database', type=Path)
    parser.add_argument('--output', type=Path, default=Path('postgres_export'))
    args=parser.parse_args()
    if not args.database.is_file(): raise SystemExit(f'Banco não encontrado: {args.database}')
    args.output.mkdir(parents=True,exist_ok=True)
    manifest={}
    with sqlite3.connect(args.database) as conn:
        conn.row_factory=sqlite3.Row
        tables=[r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        for table in tables:
            safe=''.join(c for c in table if c.isalnum() or c=='_')
            rows=[dict(r) for r in conn.execute(f'SELECT * FROM "{safe}"')]
            (args.output/f'{safe}.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
            manifest[safe]=len(rows)
    (args.output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
