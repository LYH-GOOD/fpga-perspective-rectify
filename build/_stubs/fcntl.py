"""本机自检用的 fcntl 桩：板上是真模块，Windows 没有。"""
import errno
LOCK_EX = 2
LOCK_NB = 4
LOCK_UN = 8
LOCK_SH = 1
F_SETFL = 4
F_GETFL = 3
O_NONBLOCK = 2048
def flock(fd, op): return 0
def ioctl(fd, req, arg=0): return 0
def fcntl(fd, cmd, arg=0): return 0
