"""Operator recovery using the scheduler's OS lock and append-only review API."""
import argparse
from pathlib import Path
from application.local_life import open_persisted_engine


class NoGeneration:
    provider='operator-recovery'
    kind='no-generation'
    def complete(self,*args,**kwargs):raise RuntimeError('Recovery must not generate content')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--job',required=True)
    args=parser.parse_args()
    engine=open_persisted_engine(Path(__file__).resolve().parents[2]/'data/life','local-life-v1',NoGeneration())
    with engine.worker():
        receipt=engine.recover_blocked('work-skill-recovery:'+args.job,args.job,
            'Work skill deployment: retry old blocked observation after fixing verified control evidence identity; retain original rejected attempts')
    print(receipt['replacement_job_id'])


if __name__=='__main__':main()
