#coding:utf-8
import logging; logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(name)s:%(levelname)s: %(message)s")

import asyncio, os, json, time
from datetime import datetime

from aiohttp import web
# FileSystemLoader是文件系统加载器，用来加载模板路径
from jinja2 import Environment, FileSystemLoader
import orm
from models import User, Blog, Comment
from coroweb import add_routes, add_static
from handlers import cookie2user, COOKIE_NAME
import handlers

__author__ = 'Eric Lee'

def init_jinja2(app, **kw):
    logging.info('init jinja2...')
    options = dict(
        autoescape = kw.get('autoescape', True),
        block_start_string = kw.get('block_start_string', '{%'),
        block_end_string = kw.get('block_end_string', '%}'),
        variable_start_string = kw.get('variable_start_string', '{{'),
        variable_end_string = kw.get('variable_end_string', '}}'),
        auto_reload = kw.get('auto_reload', True)
    )
    # 模板的位置
    path = kw.get('path', None)
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
    logging.info('set jinja2 template path: %s' % path)
    # Environment是jinjia2中的一个核心类，它的实例用来保存配置、全局对象以及模板文件的路径
    env = Environment(loader=FileSystemLoader(path), **options)
    # filters: 一个字典描述的filters过滤器集合, 如果非模板被加载的时候, 可以安全的添加或较早的移除.
    filters = kw.get('filters', None)
    if filters is not None:
        for name, f in filters.items():
            env.filters[name] = f
    # 所有的一切是为了给app添加__templating__字段
    # 前面将jinja2的环境配置都赋值给env了，这里再把env存入app的dict中，这样app就知道要到哪儿去找模板，怎么解析模板。
    app['__templating__'] = env

# 这个函数的作用就是当有http请求的时候，通过logging.info输出请求的信息，其中包括请求的方法和路径
@asyncio.coroutine
def logger_factory(app, handler):
    @asyncio.coroutine
    def logger(request):
        logging.info('Request: %s %s ' % (request.method, request.path))
        return (yield from  handler(request))
    return logger

# auth认证拦截器
@asyncio.coroutine
def auth_factory(app, handler):
    @asyncio.coroutine
    def auth(request):
        logging.info('check user: %s %s' % (request.method, request.path))
        request.__user__ = None
        cookie_str = request.cookies.get(COOKIE_NAME)
        if cookie_str:
            user = yield from cookie2user(cookie_str)
            print(user)
            if user:
                logging.info('set current user: %s' % user.email)
                request.__user__ = user
        if request.path.startswith('/manage/') and (request.__user__ is None or not request.__user__.admin):
            return web.HTTPFound('/signin')
        return (yield from handler(request))
    return auth

@asyncio.coroutine
def data_factory(app, handler):
    @asyncio.coroutine
    def parse_data(request):
        if request.method == 'POST':
            if request.content_type.startswith('application/json'):
                request.__data__ = yield from request.json()
                logging.info('request json: %s' % str(request.__data__))
            elif request.content_type.startswith('application/x-www-form-urlencoded'):
                request.__data__ = yield from request.post()
                logging.info('request from : %s ' % str(request.__data__))
        return (yield from handler(request))
    return parse_data

# 请求对象request的处理工序流水线先后依次是：
#     	logger_factory->auth_factory->response_factory->RequestHandler().__call__->get或post->handler
# 对应的响应对象response的处理工序流水线先后依次是:
# 由handler构造出要返回的具体对象
# 然后在这个返回的对象上加上'__method__'和'__route__'属性，以标识别这个对象并使接下来的程序容易处理
# RequestHandler目的就是从请求对象request的请求content中获取必要的参数，调用URL处理函数,然后把结果返回给response_factory
# response_factory在拿到经过处理后的对象，经过一系列类型判断，构造出正确web.Response对象，以正确的方式返回给客户端
# 在这个过程中，只关心handler的处理，其他的都走统一通道，如果需要差异化处理，就在通道中选择适合的地方添加处理代码。
# 注：在response_factory中应用了jinja2来渲染模板文件
@asyncio.coroutine
def response_factory(app, handler):
    @asyncio.coroutine
    def response(request):
        logging.info('Response handler : %s...' % handler)
        # app.router.add_route(method, path, RequestHandler(app, fn))
        # 从 handlers 的每个函数返回的值(这里的 handler是 RequestHandler（app, fn）)
        # 调用 handler(request) 就是 __call__(self, request)
        # fn 就是 handlers 里面对应的函数
        r = yield from handler(request)
        logging.info('Response result = %s' % r)
        if isinstance(r, web.StreamResponse):
            return r
        if isinstance(r, bytes):
            resp = web.Response(body=r)
            resp.content_type = 'application/octet-stream'
            return resp
        if isinstance(r, str):
            if r.startswith('redirect:'):
                return web.HTTPFound(r[9:])
            resp = web.Response(body=r.encode('utf-8'))
            resp.content_type = 'text/html;charset=utf-8'
            return resp
        if isinstance(r, dict):
            template = r.get('__template__')
            if template is None:
                # dumps:dict转化成str格式
                resp = web.Response(body=json.dumps(r, ensure_ascii=False, default=lambda o:o.__dict__).encode('utf-8'))
                resp.content_type = 'text/html;charset=utf-8'
                return resp
            else:
                r['__user__'] = request.__user__
                resp = web.Response(body=app['__templating__'].get_template(template).render(**r).encode('utf-8'))
                resp.content_type = 'text/html;charset=utf-8'
                return resp
        if isinstance(r, int) and 600>r >= 100:
            return web.Response(r)
        if isinstance(r, tuple) and len(r) == 2:
            status_code, description = r
            if isinstance(status_code, int) and 600>status_code>=100:
                return web.Response(status=status_code, text=str(description))
        #default
        resp = web.Response(body=str(r).encode('utf-8'))
        resp.content_type = 'text/plain;charset=utf-8'
        return resp
    return response

def datetime_filter(t):
    delta = int(time.time() - t)
    if delta < 60:
        return u'1分钟前'
    if delta < 3600:
        return u'%s分钟前' % (delta // 60) # 整除
    if delta < 86400:
        return u'%s小时前' % (delta // 3600)
    if delta < 604800:
        return u'%s天前' % (delta // 86400)
    dt = datetime.fromtimestamp(t)
    return u'%s年%s月%s日' % (dt.year, dt.month, dt.day)

#def index(requset):
#   return web.Response(content_type='text/html', body=b'<h1>Awesome</h1>')

@asyncio.coroutine
def init(loop):
    # 连接 ORM
    yield from orm.create_pool(loop=loop,user='root', password='', db='awesome')
    # summary = "Try something new," \
    #           " lead to the new life."
    #
    # blogs = [
    #     Blog(id='1', user_id='1',user_name='Test Blog', user_image='about:blank', name='11', content='B1', summary=summary, created_at=time.time() - 120),
    #     Blog(id='2', user_id='2',user_name='Something New', user_image='about:blank', name='22',content='B2', summary=summary, created_at=time.time() - 3600),
    #     Blog(id='3', user_id='3',user_name='Learn Swift',user_image='about:blank',  name='33', content='B3', summary=summary, created_at=time.time() - 7200)
    # ]
    # for blog in blogs:
    #     yield from blog.save()

    # 创建Web服务器实例app，也就是aiohttp.web.Application类的实例，该实例的作用是处理URL、HTTP协议
    app = web.Application(loop=loop, middlewares=[logger_factory, auth_factory, response_factory])
    # 为 app 添加 __templating__ 参数
    init_jinja2(app, filters=dict(datetime=datetime_filter))
    # url处理函数， 对 aiohttp 的http 响应进行处理
    add_routes(app, 'handlers')
    # app.router.add_route('GET', '/', index)#增加协程,异步io
    add_static(app)
    srv = yield from loop.create_server(app.make_handler(), '127.0.0.1', 9000)
    logging.info('server start at http://127.0.0.1:9000...')
    return srv #返回服务器

# loop为Eventloop用来处理HTTP请求
# 异步io事件的句柄, 创建协程
loop = asyncio.get_event_loop() #寻找@asyncio.coroutine后里面的异步io事件
loop.run_until_complete(init(loop))
loop.run_forever() # 知道调用stop()或认为中断

# asyncio:  异步 IO 模块创建服务协程，监听相应端口
# aiohttp:  异步 Web 开发框架，处理 HTTP 请求，构建并返回 HTTP 响应