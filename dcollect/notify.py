import asyncio

import httpx

import dcollect.model as model
import dcollect.mq as mq

NOTIFY_TOPIC = "dcollect-notify-v1"


class Notify:
    def __init__(self, http_client: httpx.AsyncClient, mq: mq.MQ):
        self.http_client = http_client
        self.mq = mq

    async def setup(self):
        self.notify_id = await self.mq.subscribe(NOTIFY_TOPIC, self.on_notify)

    async def on_notify(self, msg):
        entity = msg.data.decode()
        await self.notify_watchers(entity)

    async def send_notification(self, url: str, entity: str):
        body = {"entity": entity}
        resp = await self.http_client.post(url=url, json=body)
        return resp.status_code == 200

    async def notify_watcher(self, entity: str, url: str, version: int):
        if await self.send_notification(url, entity):
            model.update_watch(entity, url, version)

    async def notify_watchers(self, entity: str):
        update_promises = []
        async for (url, version) in model.get_trailing_watches_for_entity(entity):
            update_promises.append(self.notify_watcher(entity, url, version))
            await asyncio.gather(*update_promises)

    async def schedule(self, entity: str):
        entity = entity.encode("utf-8")
        await self.mq.publish(NOTIFY_TOPIC, entity)
