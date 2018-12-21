# Autoreloading launcher.
# Borrowed from Peter Hunt and the CherryPy project (http://www.cherrypy.org).
# Some taken from Ian Bicking's Paste (http://pythonpaste.org/).
#
# Portions copyright (c) 2004, CherryPy Team (team@cherrypy.org)
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification,
# are permitted provided that the following conditions are met:
#
#     * Redistributions of source code must retain the above copyright notice,
#       this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright notice,
#       this list of conditions and the following disclaimer in the documentation
#       and/or other materials provided with the distribution.
#     * Neither the name of the CherryPy Team nor the names of its contributors
#       may be used to endorse or promote products derived from this software
#       without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""@author: Nick.Na
    主要用于开发者模式启动服务， python manage.py runserver 代码改变时自动重新启动程序

"""

import os, sys, time, signal

try:
    import thread
except ImportError:
    import dummy_thread as thread

# This import does nothing, but it's necessary to avoid some race conditions
# in the threading module. See http://code.djangoproject.com/ticket/2330 .
try:
    import threading
except ImportError:
    pass

try:
    import termios
except ImportError:
    termios = None

RUN_RELOADER = True

_mtimes = {}
_win = (sys.platform == "win32")

"""@Nick.Na

    通过 os.stat(filename).st_mtime 存在全局变量中
"""
def code_changed():
    global _mtimes, _win
    for filename in filter(lambda v: v, map(lambda m: getattr(m, "__file__", None), sys.modules.values())):
        if filename.endswith(".pyc") or filename.endswith(".pyo"):
            filename = filename[:-1]
        if filename.endswith("$py.class"):
            filename = filename[:-9] + ".py"
        if not os.path.exists(filename):
            continue # File might be in an egg, so it can't be reloaded.
        stat = os.stat(filename)
        mtime = stat.st_mtime
        if _win:
            mtime -= stat.st_ctime
        if filename not in _mtimes:
            _mtimes[filename] = mtime
            continue
        if mtime != _mtimes[filename]:
            _mtimes = {}
            return True
    return False

def ensure_echo_on():
    if termios:
        fd = sys.stdin
        if fd.isatty():
            attr_list = termios.tcgetattr(fd)
            if not attr_list[3] & termios.ECHO:
                attr_list[3] |= termios.ECHO
                if hasattr(signal, 'SIGTTOU'):
                    old_handler = signal.signal(signal.SIGTTOU, signal.SIG_IGN)
                else:
                    old_handler = None
                termios.tcsetattr(fd, termios.TCSANOW, attr_list)
                if old_handler is not None:
                    signal.signal(signal.SIGTTOU, old_handler)

"""@author Nick.Na

    监听代码变化， 强制重启
"""
def reloader_thread():
    ensure_echo_on()
    while RUN_RELOADER:
        if code_changed():
            sys.exit(3) # force reload
        time.sleep(1)

"""@author Nick.Na

    sys.executable # python可执行文件路径
    sys.argv   # 用户输入的参数列表

    os.environ.copy() 复制一份环境变量
    设置"RUN_MAIN"为 "true"

    spawnv(mode, file, args) -> integer
    在新进程中执行程序, 以命令行参数的形式传递args中指定的参数

    - mode == P_NOWAIT  返回process的pid.
    - mode == P_WAIT    如果进程正常退出，则返回进程的退出代码；
    - 其它   返回-SIG, SIG是kill该进程信号

    这里相当于起一个子进程，执行python manage.py runserver
    并且子进程中"RUN_MAIN"='true'

    hile循环，需要注意的是while循环退出的唯一条件是exit_code!=3
    如果子进程不退出， 主进程一直在os.spawnve处等待
    如果子进程退出
        exit_code != 3 循环结束, 主进程也结束
        exit_code == 3 检测到了文件修改，重新创建子进程， 新代码生效
"""
def restart_with_reloader():
    while True:
        args = [sys.executable] + ['-W%s' % o for o in sys.warnoptions] + sys.argv
        if sys.platform == "win32":
            args = ['"%s"' % arg for arg in args]
        new_environ = os.environ.copy()
        new_environ["RUN_MAIN"] = 'true'
        exit_code = os.spawnve(os.P_WAIT, sys.executable, args, new_environ)
        if exit_code != 3:
            return exit_code

"""@author Nick.Na

    第一次执行时（主进程）
        os.environ.未设置"RUN_MAIN"
            执行 restart_with_reloader
             - 创建一个子进程
             - 子进程中"RUN_MAIN"设置为"true"
             - 子进程中再次执行python manage.py runserver
    后续执行　（restart_with_reloader方法中创建的子进程）
        reloader_thread() 监听代码变化，强制重启
"""
def python_reloader(main_func, args, kwargs):
    if os.environ.get("RUN_MAIN") == "true":
        thread.start_new_thread(main_func, args, kwargs)
        try:
            reloader_thread()
        except KeyboardInterrupt:
            pass
    else:
        try:
            exit_code = restart_with_reloader()
            if exit_code < 0:
                os.kill(os.getpid(), -exit_code)
            else:
                sys.exit(exit_code)
        except KeyboardInterrupt:
            pass

def jython_reloader(main_func, args, kwargs):
    from _systemrestart import SystemRestart
    thread.start_new_thread(main_func, args)
    while True:
        if code_changed():
            raise SystemRestart
        time.sleep(1)

"""
    针对jpython和其它python分别处理
"""
def main(main_func, args=None, kwargs=None):
    if args is None:
        args = ()
    if kwargs is None:
        kwargs = {}
    if sys.platform.startswith('java'):
        reloader = jython_reloader
    else:
        reloader = python_reloader
    reloader(main_func, args, kwargs)
