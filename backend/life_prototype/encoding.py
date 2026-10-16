"""Replaceable encoders. Lexical fallback is never labelled semantic.

Cached ONNX inference is isolated in a bounded, network-disabled child process.
No production runtime, database or generative CLI is imported by that child.
"""
from collections import Counter
import hashlib
from importlib.metadata import version
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import os

from .config import canonical, digest


def lexical(text):
    words=re.findall(r'[a-z0-9_]+|[\u4e00-\u9fff]',text.lower())
    c=Counter(words+[words[i]+'|'+words[i+1] for i in range(len(words)-1)])
    # Explicit vocabulary expansion, not a claim of semantic embeddings.
    for concept, alternatives in {
        'movie': ('电影', '影片', '观影', '看片'),
        'reading': ('读书', '阅读', '看书'),
        'exercise': ('运动', '锻炼', '健身'),
        'dining': ('吃饭', '用餐', '进餐'),
        'work': ('上班', '工作', '办公'),
        'sleep': ('睡觉', '入睡', '睡眠'),
        'walk': ('散步', '走走', '漫步'),
        'appointment': ('约定', '预约', '约好'),
    }.items():
        if any(term in text for term in alternatives):
            c['concept:' + concept] += 2
    n=math.sqrt(sum(v*v for v in c.values())) or 1
    return {k:v/n for k,v in c.items()}


class LexicalEncoder:
    descriptor={'mode':'lexical','model':'character-word-bigram','version':'2-vocabulary','dimensions':'sparse'}
    def encode(self,texts):return [lexical(t) for t in texts]


def cached_descriptor(path):
    path=Path(path).resolve()
    names=['config.json','model_optimized.onnx','special_tokens_map.json','tokenizer.json','tokenizer_config.json']
    if not all((path/n).is_file() for n in names):raise ValueError('complete existing local model required; no download')
    hashes={n:hashlib.sha256((path/n).read_bytes()).hexdigest() for n in names}
    return {'mode':'semantic','model':'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
        'version':digest(hashes),'dimensions':384,'files_sha256':hashes,'model_path':str(path),
        'fastembed_version':version('fastembed'),'onnxruntime_version':version('onnxruntime'),
        'pooling':'installed_fastembed_mean_normalized','network':'disabled_local_files_only'}


def validate_vectors(vectors,count,dimension):
    if len(vectors)!=count:raise ValueError('encoder count mismatch')
    output=[]
    for v in vectors:
        if len(v)!=dimension or any(not isinstance(x,(int,float)) or not math.isfinite(x) for x in v):
            raise ValueError('invalid encoder dimensions or numbers')
        norm=math.sqrt(sum(x*x for x in v))
        if not norm:raise ValueError('zero encoder vector')
        output.append([float(x)/norm for x in v])
    return output


class CachedLocalEncoder:
    def __init__(self,descriptor,timeout=120):
        if cached_descriptor(descriptor['model_path'])!=descriptor:raise ValueError('encoder file/runtime version changed')
        self.descriptor=descriptor;self.timeout=timeout
    def encode(self,texts):
        env={**os.environ,'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','HF_HUB_DISABLE_TELEMETRY':'1'}
        result=subprocess.run([sys.executable,'-X','utf8','-m','life_prototype.embedding_worker'],
            input=canonical({'descriptor':self.descriptor,'texts':texts}),text=True,encoding='utf8',
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,cwd=Path(__file__).resolve().parents[1],
            timeout=self.timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:raise RuntimeError('local encoder failed: '+result.stderr[-1500:])
        return validate_vectors(json.loads(result.stdout),len(texts),self.descriptor['dimensions'])


def similarity(a,b):
    if isinstance(a,dict):return sum(x*b.get(k,0) for k,x in a.items())
    if len(a)!=len(b):raise ValueError('mixed encoder dimensions')
    return sum(x*y for x,y in zip(a,b))
