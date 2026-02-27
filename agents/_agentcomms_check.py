import os, sys, re
from pathlib import Path
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv(Path(__file__).parents[1] / '.env', override=True)

results = []

# 1. Env
for k in ['GOOGLE_CLOUD_PROJECT', 'GOOGLE_CLOUD_LOCATION', 'LANGSMITH_API_KEY', 'PG_DSN']:
    v = os.environ.get(k, 'MISSING')
    display = re.sub(r':([^@]+)@', ':***@', v[:40]) if k == 'PG_DSN' else (v[:20] + '...' if len(v) > 20 else v)
    results.append(f'  ENV  {k}={display}')

try:
    from agents.agents import get_agent
    for a in ['researcher','builder','verifier','scribe']:
        ag = get_agent(a)
        results.append(f'  OK   {a:<12} {type(ag).__name__}')
except Exception as e:
    results.append(f'  FAIL agents: {e}')

try:
    from langchain_google_genai import ChatGoogleGenerativeAI
    llm = ChatGoogleGenerativeAI(model='gemini-2.5-flash', temperature=0,
        project=os.environ['GOOGLE_CLOUD_PROJECT'], location=os.environ['GOOGLE_CLOUD_LOCATION'])
    r = llm.invoke('reply with one word: ONLINE')
    results.append(f'  OK   gemini ping: {r.content.strip()[:40]}')
except Exception as e:
    results.append(f'  FAIL gemini: {e}')

# 4. PostgreSQL checkpointer
try:
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg_pool import ConnectionPool
    dsn = os.environ.get('PG_DSN', 'postgresql://postgres:d1204l0723@localhost:5432/postgres')
    pool = ConnectionPool(conninfo=dsn, min_size=1, max_size=4, kwargs={'autocommit': True}, open=True)
    saver = PostgresSaver(pool)
    saver.setup()
    pool.close()
    results.append('  OK   postgres checkpointer (langgraph tables ready)')
except Exception as e:
    results.append(f'  FAIL postgres: {e}')

# 5. LangSmith
try:
    from langsmith import Client
    c = Client()
    projs = [p.name for p in list(c.list_projects())[:3]]
    results.append(f'  OK   langsmith: {projs}')
except Exception as e:
    results.append(f'  FAIL langsmith: {e}')

print('=== AgentComms Status ===')
for r in results: print(r)
print('=== Done ===')
