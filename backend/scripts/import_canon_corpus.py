"""Explicit reviewed character material import; never initializes the production DB implicitly."""
import argparse
import json
from pathlib import Path
from domains.persona.character_corpus import CharacterCorpusStore

def import_corpus(database_path, root=None):
    return CharacterCorpusStore(database_path).import_directory(root)

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description='Import current reviewed character material; --root optionally selects a material JSON or legacy JSONL directory')
    parser.add_argument('--database',type=Path,required=True)
    parser.add_argument('--root',type=Path,default=None)
    args=parser.parse_args()
    print(json.dumps(import_corpus(args.database,args.root),ensure_ascii=False))
