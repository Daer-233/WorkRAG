"""Backend launcher copied into Design RAG to load its isolated vector SDK."""
import argparse
import os
from pathlib import Path
import sys


def main():
    from dotenv import load_dotenv

    root = Path(__file__).resolve().parents[1]
    config = root / '.env'
    load_dotenv(config, override=False)
    os.environ['DESIGN_RAG_ENV_FILE'] = str(config)
    if os.environ.get('VECTOR_PROVIDER', 'qdrant').lower() == 'milvus':
        sdk = Path(os.environ.get('MILVUS_SDK_PATH') or root / 'data/milvus-sdk')
        if not (sdk / 'pymilvus').is_dir():
            raise RuntimeError('Milvus SDK missing; check MILVUS_SDK_PATH')
        sys.path.insert(0, str(sdk))
    sys.path.insert(0, str(root / 'apps/backend'))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8030)
    parser.add_argument('--reload', action='store_true')
    args = parser.parse_args()
    import uvicorn
    uvicorn.run('app.main:app', host=args.host, port=args.port, reload=args.reload)


if __name__ == '__main__':
    main()
