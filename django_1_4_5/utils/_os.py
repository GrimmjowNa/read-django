""" @author: Nick.Na

    本文件主要与底层文件路径相关
    - abspathu: 返回绝对路径
    - safe_join： 路径拼接
    - rmtree_errorhandler： 为 shutil.rmtree 提供的回调函数

"""

import os
import stat
from os.path import join, normcase, normpath, abspath, isabs, sep
from django.utils.encoding import force_unicode

try:
    WindowsError = WindowsError
except NameError:
    class WindowsError(Exception):
        pass


# Define our own abspath function that can handle joining
# unicode paths to a current working directory that has non-ASCII
# characters in it.  This isn't necessary on Windows since the
# Windows version of abspath handles this correctly.  The Windows
# abspath also handles drive letters differently than the pure
# Python implementation, so it's best not to replace it.
""" @author: Nick.Na

    os.name:
        - 'posix': linux
        - 'nt': windows
        - 'java' java虚拟机

    理解normpath: 清除多余的分隔符或者相对路径部分

    例子:
    os.getcwdu() # 执行路径
    # 结果  u'/home/nick/read-django'

    path = join(os.getcwdu(), 'a')
    # 结果  u'/home/nick/read-django/a'

    path = join(os.getcwdu(), '../a')
    # 结果  u'/home/nick/read-django/../a'

    os.path.isdir(path)
    # 创建'/home/nick/a'文件夹后返回 True
    # u'/home/nick/read-django/../a' 是一个合法路径

    normpath(path)
    # 结果  u'/home/nick/a'

    normpath('/home///nick')
    # 结果  u'/home/nick'

    normpath('/home/nick/Djangó')
    # 结果  '/home/nick/Djang\xc3\xb3'
"""
if os.name == 'nt':
    abspathu = abspath
else:
    def abspathu(path):
        """
        Version of os.path.abspath that uses the unicode representation
        of the current working directory, thus avoiding a UnicodeDecodeError
        in join when the cwd has non-ASCII characters.
        """
        if not isabs(path):
            path = join(os.getcwdu(), path)
        return normpath(path)

""" @author: Nick.Na

    理解函数不确定的参数
    理解解包

    传入一个或多个路径名, 返回一个绝对路径, 生成的路径必须在base路径下
    如果执行 safe_join('static', '../js')
    将会抛出 ValueError

"""
def safe_join(base, *paths):
    """
    Joins one or more path components to the base path component intelligently.
    Returns a normalized, absolute version of the final path.

    The final path must be located inside of the base path component (otherwise
    a ValueError is raised).
    """
    base = force_unicode(base)
    paths = [force_unicode(p) for p in paths]
    final_path = abspathu(join(base, *paths))
    base_path = abspathu(base)
    base_path_len = len(base_path)
    # Ensure final_path starts with base_path (using normcase to ensure we
    # don't false-negative on case insensitive operating systems like Windows)
    # and that the next character after the final path is os.sep (or nothing,
    # in which case final_path must be equal to base_path).
    if not normcase(final_path).startswith(normcase(base_path)) \
       or final_path[base_path_len:base_path_len+1] not in ('', sep):
        raise ValueError('The joined path (%s) is located outside of the base '
                         'path component (%s)' % (final_path, base_path))
    return final_path

""" @author: Nick.Na

    了解 shutil-- High-level file operations 是一种高层次的文件操作工具
        类似于高级API，而且主要强大之处在于其对文件的复制与删除操作更是比较支持好。

    shutil.rmtree(path[, ignore_errors[, onerror]]) 递归的去删除文件
     - ignore_errors
       - True: 删除中过程的错误将会被忽略
       - False: 通过指定onerror处理错误信息， 没有指定onerror则抛出异常
     - onerror 带三个参数(func, path, exc_info)
       - func: os.listdir, os.remove, or os.rmdir;
       - path: 导致出错的路径
       - exc_info: sys.exc_info()返回的元组

     理解 sys.exc_info()
     例子:
         try:
             1/0
         except:
             print sys.exc_info()

    结果： (<type 'exceptions.ZeroDivisionError'>, ZeroDivisionError('integer division or modulo by zero',), <traceback object at 0x7fbea84d1e60>)
        - type (异常类别)value
        - (异常说明，可带参数)
        -  traceback (traceback对象，包含更丰富的信息)


    理解 os.stat() 系统调用时用来返回相关文件的系统状态信息的。
    os.stat("/home/nick")
    结果： posix.stat_result(
            st_mode=16877,  # 权限模式
            st_ino=4849666, # inode number
            st_dev=2055,    # device
            st_nlink=73,    # number of hard links
            st_uid=1000,    # 所有用户的user id
            st_gid=1000,    # 所有用户的group id
            st_size=4096,   # 文件的大小，以位为单位
            st_atime=1545364911, #文件最后访问时间
            st_mtime=1545358537, #文件最后修改时间
            st_ctime=1545358537  #文件创建时间
         )

     这里的 rmtree_errorhandler 就是为onerror指定的值
     用法 shutil.rmtree(path_to_remove, onerror=rmtree_errorhandler)

     如果不是 WindowsError 或者 'Access is denied'不在异常信息中， 抛出异常

     os.chmod(path, stat.S_IREAD) 修改文件权限
      - stat.S_IREAD: windows下设为只读
      - stat.S_IWRITE: windows下取消只读

"""
def rmtree_errorhandler(func, path, exc_info):
    """
    On Windows, some files are read-only (e.g. in in .svn dirs), so when
    rmtree() tries to remove them, an exception is thrown.
    We catch that here, remove the read-only attribute, and hopefully
    continue without problems.
    """
    exctype, value = exc_info[:2]
    # lookin for a windows error
    if exctype is not WindowsError or 'Access is denied' not in str(value):
        raise
    # file type should currently be read only
    if ((os.stat(path).st_mode & stat.S_IREAD) != stat.S_IREAD):
        raise
    # convert to read/write
    os.chmod(path, stat.S_IWRITE)
    # use the original function to repeat the operation
    func(path)

