"""Provision only the fixed, isolated test endpoints; never loads .env."""
import asyncio
import asyncpg
from minio import Minio

async def main():
    conn = await asyncpg.connect('postgresql://phylo_test:phylo_test@127.0.0.1:55432/postgres')
    try:
        if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname='phylo_e2e_test'"):
            await conn.execute('CREATE DATABASE phylo_e2e_test')
    finally:
        await conn.close()
    client = Minio('127.0.0.1:59000', access_key='phylo_test', secret_key='phylo_test_secret', secure=False)
    for bucket in ['phylo-tests', 'phylo-test-datasets', 'phylo-test-artifacts']:
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)

asyncio.run(main())
