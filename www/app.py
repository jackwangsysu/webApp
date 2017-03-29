#coding:utf-8
import logging; logging.basicConfig(level=logging.INFO)

import asyncio, os, json, time
from datetime import datetime

from aiohttp import web

def index(requset):
    return web.Response(content_type='text/html', body=b'<h1>Awesome</h1>')

@asyncio.coroutine
def init(loop):
    app = web.Application(loop=loop)
    app.router.add_route('GET', '/', index)#增加协程,异步io
    srv = yield from loop.create_server(app.make_handler(), '127.0.0.1', 9000)
    logging.info('server start at http://127.0.0.1:9000...')
    return srv #返回服务器

loop = asyncio.get_event_loop() #寻找@asyncio.coroutine后里面的异步io事件
loop.run_until_complete(init(loop))
loop.run_forever()
