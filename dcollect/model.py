import datetime
from typing import AsyncGenerator, Awaitable, Dict, Optional, Tuple, TypedDict

import databases

DATABASE_URL = "sqlite:///./test.db"
database = databases.Database(DATABASE_URL)

SETUP_QUERIES = [
    """CREATE TABLE IF NOT EXISTS cas (hash BLOB(8) PRIMARY KEY, data BLOB) """,
    """CREATE TABLE IF NOT EXISTS vsn (entity TEXT, vsn INTEGER, pointer BLOB(8), PRIMARY KEY (entity, vsn))""",
    """CREATE TABLE IF NOT EXISTS watch (entity TEXT, url TEXT, vsn INTEGER DEFAULT 0 NOT NULL, PRIMARY KEY (entity, url))""",
]


async def cas_insert(hash_: bytes, data: bytes):
    CAS_STORE = "INSERT OR IGNORE INTO cas (hash, data) VALUES (:hash, :data)"
    await database.execute(CAS_STORE, values={"hash": hash_, "data": data})


async def get_ca(hs: bytes) -> Optional[bytes]:
    CAS_GET = "SELECT data FROM cas WHERE hash = :hash"
    res = await database.fetch_one(CAS_GET, values={"hash": hs})
    if res is None:
        return None
    (data,) = res
    return data


WATCH_STORE_QUERY = (
    "INSERT OR IGNORE INTO watch (entity, url) " + "VALUES (:entity, :url)"
)


async def watch_store(entity: str, url: str):
    await database.execute(WATCH_STORE_QUERY, values={"entity": entity, "url": url})


WATCH_DELETE_QUERY = "DELETE FROM watch WHERE entity = :entity AND url = :url"


async def watch_delete(entity: str, url: str):
    await database.execute(WATCH_DELETE_QUERY, values={"entity": entity, "url": url})


def store_vsn(entity: str, vsn: Optional[int], pointer: bytes) -> Awaitable[int]:
    STORE = (
        "INSERT OR IGNORE INTO vsn (entity, vsn, pointer) "
        + "VALUES (:entity, :vsn, :pointer)"
    )
    return database.execute(
        STORE, values={"entity": entity, "vsn": vsn, "pointer": pointer}
    )


async def get_latest_pointer(entity: str) -> Optional[bytes]:
    Q = """
    SELECT pointer
    FROM vsn
    WHERE entity = :entity
    ORDER BY vsn DESC LIMIT 1
    """
    res = await database.fetch_one(Q, values={"entity": entity})
    if res is None:
        return None
    (ptr,) = res
    return ptr


async def get_trailing_watches_for_entity(
    entity: str,
) -> AsyncGenerator[Tuple[str, int], None]:
    Q = """
    WITH latest AS
         (SELECT entity, vsn as latest_vsn FROM vsn WHERE entity = :entity ORDER BY vsn DESC LIMIT 1)
    SELECT url, latest_vsn FROM watch
    INNER JOIN latest on watch.entity = latest.entity
    WHERE latest_vsn > watch.vsn;
    """
    async for e in database.iterate(query=Q, values={"entity": entity}):
        yield (e[0], int(e[1]))


async def update_watch(entity: str, url: str, version: int):
    Q = """
    UPDATE watch SET version = :version WHERE entity = :entity AND url = :url AND version < :version
    """
    await database.execute(Q, values={"entity": entity, "url": url, "version": version})


async def get_history(entity: str) -> AsyncGenerator[Tuple[int, bytes], None]:
    Q = """
    SELECT vsn, pointer FROM vsn WHERE entity = :entity
    """
    res = database.iterate(Q, values={"entity": entity,})
    async for row in res:
        yield (row[0], row[1])


async def setup():
    await database.connect()
    for query in SETUP_QUERIES:
        await database.execute(query=query)


async def teardown():
    await database.disconnect()