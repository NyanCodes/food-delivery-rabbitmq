"""Purge demo queues and clear order data between rehearsals."""

import sys
from urllib.parse import quote

import requests

from app import config, db, logs, store

log = logs.setup("reset")


def purge_queues() -> None:
    for queue in [*config.QUEUES, config.DLQ]:
        url = f"{config.RABBIT_HTTP}/api/queues/%2F/{quote(queue, safe='')}/contents"
        response = requests.delete(
            url,
            auth=(config.RABBIT_USER, config.RABBIT_PASS),
            timeout=10,
        )
        if response.status_code not in (204, 404):
            response.raise_for_status()
        log.info("purged %s", queue)


def main() -> int:
    try:
        purge_queues()
        store.truncate_all()
        db.close()
    except Exception:
        log.exception("reset failed")
        return 1
    log.info("queues and order tables are empty")
    return 0


if __name__ == "__main__":
    sys.exit(main())
