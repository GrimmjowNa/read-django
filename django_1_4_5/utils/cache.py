"""
This module contains helper functions for controlling caching. It does so by
managing the "Vary" header of responses. It includes functions to patch the
header of response objects directly and decorators that change functions to do
that header-patching themselves.

For information on the Vary header, see:

    http://www.w3.org/Protocols/rfc2616/rfc2616-sec14.html#sec14.44

Essentially, the "Vary" HTTP header defines which headers a cache should take
into account when building its cache key. Requests with the same path but
different header content for headers named in "Vary" need to get different
cache keys to prevent delivery of wrong content.

An example: i18n middleware would need to distinguish caches by the
"Accept-language" header.
"""

"""author: Nick.Na

    该模块包括用于控制缓存的辅助函数。
    它通过这样做管理response header的‘Vary’的响应报头实现缓存控制。
    包含直接修改response header的函数和装饰器
"""
import hashlib
import re
import time

from django.conf import settings
from django.core.cache import get_cache
from django.utils.encoding import smart_str, iri_to_uri, force_unicode
from django.utils.http import http_date
from django.utils.timezone import get_current_timezone_name
from django.utils.translation import get_language

cc_delim_re = re.compile(r'\s*,\s*')

"""@author Nick.Na

    服务器可以在响应中使用的标准 Cache-Control 指令
        Cache-control: must-revalidate
        Cache-control: no-cache
        Cache-control: no-store
        Cache-control: no-transform
        Cache-control: public
        Cache-control: private
        Cache-control: proxy-revalidate
        Cache-Control: max-age=<seconds>
        Cache-control: s-maxage=<seconds>

    用法示例：

        response Cache-Control: s-maxage=300, public, max-age=100

        patch_cache_control(response, no_cache=True, no_store=True, must_revalidate=True, max_age=100)

        將kwargs中的key，value追加到response的Cache-Control中
    
    注释:
        此函数通过向其添加关键字参数来追加Cache-Control标头。格式转换如下：

            - 所有关键字参数名称都将变为小写，下划线将转换为连字符。
            - 如果参数的值为True（完全为True，而不仅仅是true值），则只将参数名称添加到标题中。
            - 其它参数调用str（）之后再添加 。

"""
def patch_cache_control(response, **kwargs):
    """
    This function patches the Cache-Control header by adding all
    keyword arguments to it. The transformation is as follows:

    * All keyword parameter names are turned to lowercase, and underscores
      are converted to hyphens.
    * If the value of a parameter is True (exactly True, not just a
      true value), only the parameter name is added to the header.
    * All other parameters are added with their value, after applying
      str() to it.
    """
    def dictitem(s):
        t = s.split('=', 1)
        if len(t) > 1:
            return (t[0].lower(), t[1])
        else:
            return (t[0].lower(), True)

    def dictvalue(t):
        if t[1] is True:
            return t[0]
        else:
            return t[0] + '=' + smart_str(t[1])

    """@Nick.Na

        将response中的Cache-Control转为dict
        示例：
            's-maxage=300, public, max-age=0'
            => ['s-maxage=300', 'public', 'max-age=0']
            => {'max-age': '0', 'public': True, 's-maxage': '300'}

    """
    if response.has_header('Cache-Control'):
        cc = cc_delim_re.split(response['Cache-Control'])
        cc = dict([dictitem(el) for el in cc])
    else:
        cc = {}

    # If there's already a max-age header but we're being asked to set a new
    # max-age, use the minimum of the two ages. In practice this happens when
    # a decorator and a piece of middleware both operate on a given view.
    if 'max-age' in cc and 'max_age' in kwargs:
        kwargs['max_age'] = min(cc['max-age'], kwargs['max_age'])

    # Allow overriding private caching and vice versa
    if 'private' in cc and 'public' in kwargs:
        del cc['private']
    elif 'public' in cc and 'private' in kwargs:
        del cc['public']

    """@author: Nick.Na

        將kwargs中的`_`替換成`-`,拼接出新的`Cache-Control`字符串
    """

    for (k, v) in kwargs.items():
        cc[k.replace('_', '-')] = v
    cc = ', '.join([dictvalue(el) for el in cc.items()])
    response['Cache-Control'] = cc

"""@author: Nick.Na

    从响应Cache-Control标头返回max-age作为整数（如果未找到或不是整数，则返回None）
"""
def get_max_age(response):
    """
    Returns the max-age from the response Cache-Control header as an integer
    (or ``None`` if it wasn't found or wasn't an integer.
    """
    if not response.has_header('Cache-Control'):
        return
    cc = dict([_to_tuple(el) for el in
        cc_delim_re.split(response['Cache-Control'])])
    if 'max-age' in cc:
        try:
            return int(cc['max-age'])
        except (ValueError, TypeError):
            pass

"""@author: Nick.Na

    ETag:
        第一次发起HTTP请求时
            服务器会返回一个Etag到客戶端
            ETag由服务器生成
        第二次发起同一个请求时，客户端会同时发送一个If-None-Match
            If-None-Match 它的值就是Etag的值（此处由发起请求的客户端来设置）

        服务器会比对这个客服端发送过来的Etag是否与服务器的相同

            如果相同，就将If-None-Match的值设为false，返回状态为304，客户端继续使用本地缓存
            不解析服务器返回的数据（这种场景服务器也不返回数据，因为服务器的数据没有变化）

    Etag的优先级高于Last-Modified
"""
def _set_response_etag(response):
    response['ETag'] = '"%s"' % hashlib.md5(response.content).hexdigest()
    return response

"""@author Nick.Na

    为response header中ETag, Last-Modified, Expires设置默认值
    向给定的HttpResponse对象添加一些有用的标头： 
        - ETag
        - Last-Modified
        - Expires
        - Cache-Control
    仅在尚未设置的情况下添加每个标头。
"""
def patch_response_headers(response, cache_timeout=None):
    """
    Adds some useful headers to the given HttpResponse object:
        ETag, Last-Modified, Expires and Cache-Control

    Each header is only added if it isn't already set.

    cache_timeout is in seconds. The CACHE_MIDDLEWARE_SECONDS setting is used
    by default.
    """
    if cache_timeout is None:
        cache_timeout = settings.CACHE_MIDDLEWARE_SECONDS
    if cache_timeout < 0:
        cache_timeout = 0 # Can't have max-age negative
    if settings.USE_ETAGS and not response.has_header('ETag'):
        if hasattr(response, 'render') and callable(response.render):
            response.add_post_render_callback(_set_response_etag)
        else:
            response = _set_response_etag(response)
    if not response.has_header('Last-Modified'):
        response['Last-Modified'] = http_date()
    if not response.has_header('Expires'):
        response['Expires'] = http_date(time.time() + cache_timeout)
    patch_cache_control(response, max_age=cache_timeout)

"""@author Nick.Na

    向响应添加标头永远不应缓存页面
"""
def add_never_cache_headers(response):
    """
    Adds headers to a response to indicate that a page should never be cached.
    """
    patch_response_headers(response, cache_timeout=-1)

"""Aauthor Nick.Na

    理解Vary

        HTTP response HTTP 中的Vary用于内容协商。
        Vary中有User-Agent，那么即使相同的请求，如果用户使用IE打开了一个页面，再用Firefox打开这个页面的时候，
        代理/客户端会认为这是不同的页面，如果Vary中没有User-Agent，那么代理/客户端缓存会认为是相同的页面，
        直接给用户返回缓存的内容，而不会再去web服务器请求相应的页面。
        如果Vary变量比较多，相应的增加了缓存的容量。

    示例：
        Vary: Accept-Language, Cookie
        Vary: Accept-Encoding

    用法：
        添加或者更新Response对象header中的Vary值。 参数newheaders是一个list，包含header名称。
        Response中已有的值不会被移除。
"""
def patch_vary_headers(response, newheaders):
    """
    Adds (or updates) the "Vary" header in the given HttpResponse object.
    newheaders is a list of header names that should be in "Vary". Existing
    headers in "Vary" aren't removed.
    """
    # Note that we need to keep the original order intact, because cache
    # implementations may rely on the order of the Vary contents in, say,
    # computing an MD5 hash.
    if response.has_header('Vary'):
        vary_headers = cc_delim_re.split(response['Vary'])
    else:
        vary_headers = []
    # Use .lower() here so we treat headers as case-insensitive.
    existing_headers = set([header.lower() for header in vary_headers])
    additional_headers = [newheader for newheader in newheaders
                          if newheader.lower() not in existing_headers]
    response['Vary'] = ', '.join(vary_headers + additional_headers)

"""@author Nick.Na

    判断vary中是否存在给定的header值
"""
def has_vary_header(response, header_query):
    """
    Checks to see if the response has a given header name in its Vary header.
    """
    if not response.has_header('Vary'):
        return False
    vary_headers = cc_delim_re.split(response['Vary'])
    existing_headers = set([header.lower() for header in vary_headers])
    return header_query.lower() in existing_headers

def _i18n_cache_key_suffix(request, cache_key):
    """If necessary, adds the current locale or time zone to the cache key."""
    if settings.USE_I18N or settings.USE_L10N:
        # first check if LocaleMiddleware or another middleware added
        # LANGUAGE_CODE to request, then fall back to the active language
        # which in turn can also fall back to settings.LANGUAGE_CODE
        cache_key += '.%s' % getattr(request, 'LANGUAGE_CODE', get_language())
    if settings.USE_TZ:
        # The datetime module doesn't restrict the output of tzname().
        # Windows is known to use non-standard, locale-dependant names.
        # User-defined tzinfo classes may return absolutely anything.
        # Hence this paranoid conversion to create a valid cache key.
        tz_name = force_unicode(get_current_timezone_name(), errors='ignore')
        cache_key += '.%s' % tz_name.encode('ascii', 'ignore').replace(' ', '_')
    return cache_key

def _generate_cache_key(request, method, headerlist, key_prefix):
    """Returns a cache key from the headers given in the header list."""
    ctx = hashlib.md5()
    for header in headerlist:
        value = request.META.get(header, None)
        if value is not None:
            ctx.update(value)
    path = hashlib.md5(iri_to_uri(request.get_full_path()))
    cache_key = 'views.decorators.cache.cache_page.%s.%s.%s.%s' % (
        key_prefix, method, path.hexdigest(), ctx.hexdigest())
    return _i18n_cache_key_suffix(request, cache_key)

def _generate_cache_header_key(key_prefix, request):
    """Returns a cache key for the header cache."""
    path = hashlib.md5(iri_to_uri(request.get_full_path()))
    cache_key = 'views.decorators.cache.cache_header.%s.%s' % (
        key_prefix, path.hexdigest())
    return _i18n_cache_key_suffix(request, cache_key)

"""@author Nick.Na

    根据请求路径返回缓存键。它可以用在请求阶段，因为它从全局路径注册表中提取要考虑的headerlist，并使用这些标头来构建要检查的缓存密钥。
    如果没有存储headerlist，则需要重建页面，函数返回None。

    主要用于： Cache middleware.
        检查请求的page是否在cache中，如果在则返回cache的版本

    代码解析
        - 调用_generate_cache_header_key生成cache_key，主要依据： url, key_prefix, 语言, 时区
        - 根据生成的cache_key获取headerlist
        - 调用_generate_cache_key生成response对应的key 依据headerlist  method，headerlist，key_prefix，语言，时区
    
    一个请求会在缓存服务中缓存两个key，
        - views.decorators.cache.cache_header 对应headerlist(结合vary_on_headers使用)
        - views.decorators.cache.cache_page   对应response的内容。
"""
def get_cache_key(request, key_prefix=None, method='GET', cache=None):
    """
    Returns a cache key based on the request path and query. It can be used
    in the request phase because it pulls the list of headers to take into
    account from the global path registry and uses those to build a cache key
    to check against.

    If there is no headerlist stored, the page needs to be rebuilt, so this
    function returns None.
    """
    if key_prefix is None:
        key_prefix = settings.CACHE_MIDDLEWARE_KEY_PREFIX
    cache_key = _generate_cache_header_key(key_prefix, request)
    if cache is None:
        cache = get_cache(settings.CACHE_MIDDLEWARE_ALIAS)
    headerlist = cache.get(cache_key, None)
    if headerlist is not None:
        return _generate_cache_key(request, method, headerlist, key_prefix)
    else:
        return None

"""@author Nick.Na

    了解响应对象的某些请求路径要考虑的headers。
    它将这些headers存储在全局路径注册表中，以便以后访问该路径将知道在不构建响应对象本身的情况下要考虑哪些headers。
    headers在响应的Varyheaders中命名，但我们希望阻止响应生成。

    用于生成缓存密钥的headers列表与页面本身存储在同一缓存中。
    如果某些数据从缓存中失效，意味着我们必须构建响应一次以获取Vary头，在headers列表中使用cache key。
"""
def learn_cache_key(request, response, cache_timeout=None, key_prefix=None, cache=None):
    """
    Learns what headers to take into account for some request path from the
    response object. It stores those headers in a global path registry so that
    later access to that path will know what headers to take into account
    without building the response object itself. The headers are named in the
    Vary header of the response, but we want to prevent response generation.

    The list of headers to use for cache key generation is stored in the same
    cache as the pages themselves. If the cache ages some data out of the
    cache, this just means that we have to build the response once to get at
    the Vary header and so at the list of headers to use for the cache key.
    """
    if key_prefix is None:
        key_prefix = settings.CACHE_MIDDLEWARE_KEY_PREFIX
    if cache_timeout is None:
        cache_timeout = settings.CACHE_MIDDLEWARE_SECONDS
    cache_key = _generate_cache_header_key(key_prefix, request)
    if cache is None:
        cache = get_cache(settings.CACHE_MIDDLEWARE_ALIAS)
    if response.has_header('Vary'):
        headerlist = ['HTTP_'+header.upper().replace('-', '_')
                      for header in cc_delim_re.split(response['Vary'])]
        cache.set(cache_key, headerlist, cache_timeout)
        return _generate_cache_key(request, request.method, headerlist, key_prefix)
    else:
        # if there is no Vary header, we still need a cache key
        # for the request.get_full_path()
        cache.set(cache_key, [], cache_timeout)
        return _generate_cache_key(request, request.method, [], key_prefix)


def _to_tuple(s):
    t = s.split('=',1)
    if len(t) == 2:
        return t[0].lower(), t[1]
    return t[0].lower(), True
