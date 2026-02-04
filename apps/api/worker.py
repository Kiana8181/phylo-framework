#!/usr/bin/env python
"""RQ Worker entry point."""

import os
import sys
from rq import Worker, Queue, Connection
from redis import Redis

from apps.api.config import REDIS_URL, RQ_QUEUE_NAME
from apps.api.workers.queue import redis_conn, default_queue

if __name__ == "__main__":
    with Connection(redis_conn):
        worker = Worker([default_queue])
        worker.work()

