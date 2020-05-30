import asyncio
import hashlib
from typing import Any, Dict, List, Optional, Tuple

import httpx
import orjson
from fastapi import BackgroundTasks, FastAPI, Response
from fastapi.responses import ORJSONResponse
from pydantic import BaseModel

import dcollect.cas as cas
import dcollect.model as model
from dcollect.mq import MQ
from dcollect.notify import Notify
from dcollect.util import guess_media_type, now, pointer_as_str

app = FastAPI()

http_client = httpx.AsyncClient()
notify = Notify(http_client)


@app.on_event("startup")
async def startup():
    await model.setup()


@app.on_event("shutdown")
async def shutdown():
    await http_client.aclose()
    await model.teardown()


class StoreRequest(BaseModel):
    entity: str
    version: Optional[int] = None
    data: Dict[str, Any]


class WatchRequest(BaseModel):
    url: str


class UnwatchRequest(BaseModel):
    url: str


class WatchMultipleItem(BaseModel):
    entity: str
    url: str


class WatchMultipleRequest(BaseModel):
    to_watch: List[WatchMultipleItem]


async def read_versioned(entity):
    ptr = await model.get_latest_pointer(entity)
    if ptr is None:
        return None
    data = await model.get_ca(ptr)
    return data


@app.get("/entity/{entity}")
async def read_item(entity: str):
    data = await read_versioned(entity)
    if data is None:
        return Response(status_code=404)
    return Response(data, media_type=guess_media_type(data))


@app.get("/entity/{entity}/history", response_class=ORJSONResponse)
async def read_item_history(entity: str):
    history = [
        {"vsn": vsn, "pointer": pointer_as_str(pointer)}
        async for (vsn, pointer) in model.get_history(entity)
    ]
    return {"history": history}


async def internal_ingest(
    entity: str, version: Optional[int], data: Dict[str, Any]
) -> Tuple[bytes, int]:
    if version is None:
        version = now()
    pointer = await cas.store(data)
    await model.store_vsn(entity, version, pointer)
    return pointer, version


@app.post("/entity/{entity}/watch")
async def watch(entity: str, watch_request: WatchRequest):
    await model.watch_store(entity, watch_request.url)


@app.post("/watchMultiple")
async def watchMultiple(watch_multiple: WatchMultipleRequest):
    for x in watch_multiple.to_watch:
        await model.watch_store(x.entity, x.url)


@app.post("/unwatchMultiple")
async def unwatchMultiple(unwatch_multiple: WatchMultipleRequest):
    for x in unwatch_multiple.to_watch:
        await model.watch_delete(x.entity, x.url)


@app.post("/entity/{entity}/unwatch")
async def unwatch(entity: str, unwatch_request: UnwatchRequest):
    await model.watch_delete(entity, unwatch_request.url)


@app.post("/entity/{entity}", response_class=ORJSONResponse)
async def ingest(entity: str, data: Dict[str, Any], background_tasks: BackgroundTasks):
    (pointer, version) = await internal_ingest(entity, None, data)
    background_tasks.add_task(notify.notify_watchers, entity=entity)
    return {"version": version, "pointer": pointer_as_str(pointer)}


@app.get("/healthz", response_class=ORJSONResponse)
def healthz():
    return {"health": True}


@app.get("/readyz", response_class=ORJSONResponse)
def readyz():
    return {"ready": True}
