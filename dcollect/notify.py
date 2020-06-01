import asyncio
import logging

import httpx

from dcollect.model import Model
from dcollect.mq import MQ

NOTIFY_TOPIC = "dcollect-notify-v1"

logger = logging.getLogger("dcollect.notify")


class Notify:
    mq: MQ
    http_client: httpx.AsyncClient
    model: Model

    def __init__(self, http_client: httpx.AsyncClient, mq: MQ, model: Model):
        self.model = model
        self.http_client = http_client
        self.mq = mq

    async def setup(self) -> None:
        self.notify_id = await self.mq.subscribe(NOTIFY_TOPIC, self.on_notify)

    async def on_notify(self, msg) -> None:
        entity = msg.data.decode()
        try:
            await self.notify_watchers(entity)
        except Exception as ex:
            logger.error("Failed notifying", exc_info=True)
        else:
            await self.mq.ack(msg)

    async def send_notification(self, url: str, entity: str) -> bool:
        body = {"entity": entity}
        resp = await self.http_client.post(url=url, json=body)
        return resp.status_code == 200

    async def notify_watcher(self, entity: str, url: str, version: int) -> None:
        if await self.send_notification(url, entity):
            self.model.update_watch(entity, url, version)

    async def notify_watchers(self, entity: str) -> None:
        update_promises = []
        async for (url, version) in self.model.get_trailing_watches_for_entity(entity):
            update_promises.append(self.notify_watcher(entity, url, version))
            await asyncio.gather(*update_promises)

    async def schedule(self, entity: str) -> None:
        await self.mq.publish(NOTIFY_TOPIC, entity.encode("utf-8"))
