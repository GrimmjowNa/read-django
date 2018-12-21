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

    通过 os.stat(filename).st_mtime 存在全局变量_mtimes中
    检测到文件修改后，重置_mtimes， 并返回True

    sys.modules 全局字典，该字典是python启动后就加载在内存中。
        每当程序员导入新的模块，sys.modules将自动记录该模块。
        当第二次再导入该模块时，python会直接到字典中查找，从而加快了程序运行的速度。
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

"""@author: Nick.Na
    了解 termios:

        该模块提供了一个用于tty I/O控制的POSIX调用的接口。它仅适用于那些支持在安装期间配置的POSIX termios风格tty I/O控制的Unix版本。
        
        该模块中的所有函数都将文件描述符fd作为其第一个参数。
        - 这可以是整数文件描述符，如sys.stdin.fileno()返回的文件描述符
        - 也可以是文件对象，如sys.stdin本身。

        该模块还定义了使用此处提供的功能所需的所有常量;

    功能：

        termios.tcgetattr(fd)
            
            返回包含文件描述符fd的tty属性的列表
            如下所示：[iflag，oflag，cflag，lflag，ispeed，ospeed，cc]
            其中cc是tty特殊字符的列表（每个长度为1的字符串， 索引为VMIN和VTIME的项目，这些项目在定义这些字段时是整数）。
            必须使用termios模块中定义的符号常量来完成cc数组中标志和速度的解释以及索引。

        termios.tcsetattr(fd, when, attributes)
        
            从属性设置文件描述符fd的tty属性，这是一个像tcgetattr() 返回的属性的列表。
            when参数确定属性何时发生更改：
                TCSANOW立即更改，
                TCSADRAIN在传输所有排队输出后更改，
                或TCSAFLUSH在传输所有排队输出并丢弃所有排队输入后更改。

        termios.tcsendbreak(fd, duration)

            发送文件描述符fd中断。零持续时间发送一个中断0.25 -0.5秒; 非零持续时间具有系统依赖性意义。

        termios.tcdrain(fd)

            等到写入文件描述符fd的 所有输出都被发送完毕。

        termios.tcflush(fd, queue)

            丢弃文件描述符fd上的排队数据。
            队列选择器指定哪个队列：输入队列的TCIFLUSH，输出队列的TCOFLUSH或两个队列的TCIOFLUSH。

        termios.tcflow(fd, action)

            在文件描述符fd上挂起或恢复输入或输出。该操作参数可以是TCOOFF暂停输出，TCOON重启输出，TCIOFF暂停输入，或TCION重新启动输入。

    理解 signal
        signal包的核心是使用signal.signal()函数来预设(register)信号处理函数

            signal.signal(sig, handler) 

            功能：按照handler制定的信号处理方案处理函数

            参数：

            sig：拟需处理的信号，处理信号只针对这一种信号起作用sig

            hander：信号处理方案

                在信号基础里提到，进程可以无视信号、可采取默认操作、还可自定义操作；当handler为下列函数时，将有如下操作：

                SIG_IGN：信号被无视（ignore）或忽略

                SIG_DFL：进程采用默认（default）行为处理

            function：handler为一个函数名时，进程采用自定义函数处理

            *SIGSTOP SIGKILL不能处理，只能采用
    代码解析：

        fd = sys.stdin         # 获取标准输入的文件对象
        if fd.isatty():        # 检测文件是否连接到终端设备，如果是返回 True，否则返回 False
            attr_list = termios.tcgetattr(fd)             # 获取标准输入(终端)的设置
            if not attr_list[3] & termios.ECHO:
                attr_list[3] |= termios.ECHO              # 开启回显(输入会被显示)
                if hasattr(signal, 'SIGTTOU'):
                    old_handler = signal.signal(signal.SIGTTOU, signal.SIG_IGN)
                else:
                    old_handler = None
                termios.tcsetattr(fd, termios.TCSANOW, attr_list)   # 使设置生效
                if old_handler is not None:
                    signal.signal(signal.SIGTTOU, old_handler)
"""
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
    sys.exit(n)
    功能：执行到主程序末尾，解释器自动退出，但是如果需要中途退出程序，可以调用sys.exit函数，
         带有一个可选的整数参数返回给调用它的程序，
         表示你可以在主程序中捕获对sys.exit的调用。
         （0是正常退出，其他为异常）
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

"""@author: Nick.Na

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
