"""One bounded local embedding batch. No network, model download or life DB."""
import json
import socket
import sys

def no_network(*args,**kwargs):raise RuntimeError('embedding worker network disabled')

def main():
    data=json.load(sys.stdin)
    socket.socket.connect=no_network
    socket.socket.connect_ex=no_network
    socket.create_connection=no_network
    from fastembed import TextEmbedding
    d=data['descriptor']
    model=TextEmbedding(model_name=d['model'],specific_model_path=d['model_path'],local_files_only=True,
        threads=2,providers=['CPUExecutionProvider'],cuda=False)
    result=[[float(x) for x in row] for row in model.embed(data['texts'])]
    print(json.dumps(result))

if __name__=='__main__':main()
