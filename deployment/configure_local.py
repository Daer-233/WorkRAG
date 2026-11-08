"""Create this machine's ignored configuration; never print credentials."""
from pathlib import Path
import secrets
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = Path('G:/docker/workrag')
DEPLOY.mkdir(parents=True, exist_ok=True)
private = DEPLOY / '.env'
if not private.exists():
    private.write_text('POSTGRES_PASSWORD='+secrets.token_urlsafe(32)+'\nLANGBOT_PLUGIN_RUNTIME_CONTROL_TOKEN='+secrets.token_urlsafe(32)+'\n', encoding='utf-8')
from dotenv import dotenv_values
password = dotenv_values(private)['POSTGRES_PASSWORD']
config = ROOT / 'instances/manuals/.env'
if not config.exists():
    values = dict(dotenv_values(ROOT / 'instances/manuals/.env.example'))
    values.update(POSTGRES_DSN=f'postgresql://manual_rag:{password}@127.0.0.1:5432/manual_rag',
                  DATA_ROOT=(ROOT/'data/manuals').as_posix(),
                  VISION_ANALYSIS_DERIVATIVE_ROOT=(ROOT/'data/manuals/vision-analysis-derivatives').as_posix(),
                  DESIGN_RAG_ASSET_SIGNING_SECRET=secrets.token_urlsafe(48),
                  EMBEDDING_MODEL_DIR='G:/docker/models/bge-m3',
                  RERANK_MODEL_DIR='G:/docker/models/bge-reranker-v2-m3',
                  EMBEDDING_BATCH_SIZE='1', EMBEDDING_REQUEST_BATCH_SIZE='1',
                  EMBEDDING_EAGER_LOAD='false',RERANK_EAGER_LOAD='false')
    config.write_text(''.join(f"{k}='{v or ''}'\n" for k,v in values.items()), encoding='utf-8')
(DEPLOY/'compose.yaml').write_text((ROOT/'deployment/compose.yaml').read_text(encoding='utf-8'), encoding='utf-8')
(DEPLOY/'.gitignore').write_text('.env\nlangbot/\n*.log\n', encoding='utf-8')
(ROOT/'data/manuals/runtime').mkdir(parents=True, exist_ok=True)
commit = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
(ROOT/'data/manuals/runtime/source-commit.txt').write_text(commit+'\n',encoding='utf-8')
print('Local configuration prepared; credentials retained in ignored files.')
