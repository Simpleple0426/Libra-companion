"""Read-only smoke check through canonical tool execution; no cookie/content output."""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace

from life_prototype.clock import RealClock
from life_prototype.douban import Douban
from life_prototype.quote_sources import Sources
from life_prototype.resource_library import ROOT, library


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--quotes',action='store_true')
    args = parser.parse_args()
    checks = []
    with tempfile.TemporaryDirectory(prefix='libra-content-tools-') as temporary:
        path = Path(temporary)/'cache.sqlite3'
        @contextmanager
        def connect():
            db = sqlite3.connect(path)
            try:
                with db: yield db
            finally: db.close()
        with connect() as db:
            db.execute('CREATE TABLE life_evidence(category TEXT,id TEXT,body TEXT,PRIMARY KEY(category,id))')
        client = Douban(SimpleNamespace(store=SimpleNamespace(connect=connect),clock=RealClock()))
        for operation, parameters in [('detail',{'id':'1292052'}),('reviews',{'id':'1292052','count':2})]:
            try:
                result = client.call(operation,**parameters)
                checks.append({'tool':'movies.'+operation,'ok':bool(result),
                               **({'runtime_options':len(result['duration_options'])} if operation=='detail' else {'items':len(result)})})
            except Exception as exc:
                checks.append({'tool':'movies.'+operation,'ok':False,'error_type':type(exc).__name__})
        if args.quotes:
            resources = library()
            movie = next(iter(resources['movies'].values()))
            books = list(resources['books'].values())
            works = [dict(movie,kind='watching')]
            if books:
                book = dict(books[0],kind='reading')
                from life_prototype.quote_sources import normalize,author_name
                for item in json.loads((ROOT/'libra/quote_sources.json').read_text(encoding='utf8'))['books']:
                    if normalize(book['title'])==normalize(item['title']) and author_name(book.get('author',''))==item['author_match']:
                        book.update(douban_book_id=item['douban_book_id'],original_title=item['original_title'])
                works.append(book)
            for work in works:
                try:
                    result = Sources().collect(work)
                    checks.append({'tool':'quotes.collect','kind':work['kind'],'ok':bool(result),'items':len(result)})
                except Exception as exc:
                    checks.append({'tool':'quotes.collect','kind':work['kind'],'ok':False,'error_type':type(exc).__name__})
    print(json.dumps(checks,ensure_ascii=False,indent=2))
    return 0 if all(row['ok'] for row in checks) else 1


if __name__=='__main__': raise SystemExit(main())
