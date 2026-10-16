"""Read-only live probe. Never print credentials, account records or response bodies."""
import argparse
import json
from life_prototype import weread


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--query',default='无人生还');args=parser.parse_args()
    if not weread.status()['configured']:
        print(json.dumps({'ok':False,'error':'weread_key_missing'}));return 1
    try:
        books=weread.search(args.query,3)
        if not books:
            print(json.dumps({'ok':True,'search_count':0}));return 0
        book=weread.info(books[0]['weread_id']);chapters=weread.chapters(book['weread_id'])
        print(json.dumps({'ok':True,'search_count':len(books),'book_id':book['weread_id'],
            'title':book['title'],'chapter_count':len(chapters['chapters']),
            'chapters_with_word_count':sum(type(x.get('wordCount')) is int and x['wordCount']>0 for x in chapters['chapters'])},ensure_ascii=True))
        return 0
    except Exception as exc:
        print(json.dumps({'ok':False,'error':str(exc) if isinstance(exc,weread.WeReadUnavailable) else type(exc).__name__}));return 1


if __name__=='__main__':raise SystemExit(main())
