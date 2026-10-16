"""Read the running life service without opening or modifying its database."""
import argparse
import json
from urllib.request import urlopen


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8000)
    args=parser.parse_args()
    if not 1<=args.port<=65535:parser.error('invalid local port')
    with urlopen(f'http://127.0.0.1:{args.port}/life-system/status',timeout=20) as response:
        status=json.load(response)
    fields=('status','revision','place','place_name','activity','sleep','scheduler',
            'daily_agenda','coarse_execution','media_recommendations')
    print(json.dumps({k:status[k] for k in fields if k in status},ensure_ascii=True,indent=2))


if __name__=='__main__':main()
