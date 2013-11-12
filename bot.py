#!/usr/env/bin python
# coding=utf-8

from __future__ import print_function
import sys
import re
import select
import socket
import time
import signal
import traceback
import zmq

if len(sys.argv) < 8:
    print('Usage: python %s <host> <port> <nick> <channel> <readsock> <writesock> <worldpath>' % sys.argv[0], file=sys.stderr)
    print('  First 4 arguments specify IRC connection; next 2 arguments specify 0proxy socket paths; the last specifies a path to MC world.')
    print('  Example: irc.ozinger.org 6670 mybot mychannel ipc:///var/run/mcbot/read ipc:///var/run/mcbot/write /var/run/minecraft/world', file=sys.stderr)
    raise SystemExit(1)

LINEPARSE = re.compile("^(:(?P<prefix>[^ ]+) +)?(?P<command>[^ ]+)(?P<param>( +[^:][^ ]*)*)(?: +:(?P<message>.*))?$")

s = socket.create_connection((sys.argv[1], sys.argv[2]))
NICK = sys.argv[3]
CHANNEL = sys.argv[4]

def send(l, silent=False):
    s.send('%s\r\n' % l.replace('\r','').replace('\n','').replace('\0',''))
    if not silent: print('>>', l)

def halt(msg='그럼 이만!'):
    send('QUIT :%s' % msg);
    s.close()
    pipe.say(u'\2474점검을 위해 봇을 잠시 내립니다.')
    raise SystemExit
signal.signal(signal.SIGINT, lambda sig, frame: halt())
signal.signal(signal.SIGTERM, lambda sig, frame: halt())

def say(to, msg):
    send('PRIVMSG %s :%s' % (to, msg))

class ExecutionTimedOut(Exception): pass

def sayerr(to):
    ty, exc, tb = sys.exc_info()
    if to and ty != ExecutionTimedOut:
        say(to, '\00304!ERROR! %s (%s)' % (ty, exc))
    traceback.print_exception(ty, exc, tb)

def safeexec(to, f, args=(), kwargs={}):
    def alarm(sig, frame):
        #for i in dir(frame):
        #    if i.startswith('f_'): print i, repr(getattr(frame,i))[:120]
        raise ExecutionTimedOut('execution timed out')
    try:
        try:
            signal.signal(signal.SIGALRM, alarm)
            signal.alarm(botimpl.TIMEOUT)
            f(*args, **kwargs)
        except Exception:
            sayerr(to)
        finally:
            signal.signal(signal.SIGALRM, signal.SIG_DFL)
            signal.alarm(0)
    except ExecutionTimedOut:
        signal.signal(signal.SIGALRM, signal.SIG_DFL)
        signal.alarm(0)


LIST_FLAG = False
class Handler(object):
    LOG_REX = re.compile(r'^\[\d\d:\d\d:\d\d\] \[Server thread\/([A-Z]+)\]\: (.*)$') 
    IGN_REX = re.compile(r'^(?:\d+ recipes|\d+ achievements|Closing listening thread)$')
    EXC_REX = re.compile(r'^(?:[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+: .*|\tat .*)$')
    LIST_HEADER_REX = re.compile(r'^There are (\d+)/\d+ players online:$')
    LOGIN_REX = re.compile(ur'^([^\[]+)\[[^/]*/(.+?):\d+\] logged in with entity id (\d+) at \((-?\d+\.\d+), (-?\d+\.\d+), (-?\d+\.\d+)\)$')
    LOGOUT_REX = re.compile(ur'^([^ ]+) lost connection: (.*)$')
    PUBMSG_REX = re.compile(ur'^<([^>]+)> (.*)$')
    SPUBMSG_REX = re.compile(ur'^\[Server\] (.*)$')
    SPRIVMSG_REX = re.compile(ur'^You whisper to ([^:]+): (.*)$')
    DEATH_REX = re.compile(r'^([^\[ ]+) (.+)$')

    def on_info(self, msg): pass
    def on_warning(self, msg): pass
    def on_exception(self, line): pass

    def on_death(self, nick, how): pass
    def on_list(self, cur, nicklist): pass
    def on_login(self, nick, ip, entityid, (x,y,z)): pass
    def on_logout(self, nick, reason): pass
    def on_pubmsg(self, nick, text): pass
    def on_spubmsg(self, text): pass
    def on_sprivmsg(self, target, text): pass

    def on_log(self, level, msg):
        if level == 'INFO':
            m = self.LOGIN_REX.search(msg)
            if m:
                coord = float(m.group(4)), float(m.group(5)), float(m.group(6))
                return self.on_login(m.group(1), m.group(2), int(m.group(3)), coord) or self.on_info(msg)
            m = self.LOGOUT_REX.search(msg)
            if m:
                return self.on_logout(m.group(1), m.group(2)) or self.on_info(msg)
            m = self.PUBMSG_REX.search(msg)
            if m:
                return self.on_pubmsg(m.group(1), m.group(2)) or self.on_info(msg)
            m = self.SPUBMSG_REX.search(msg)
            if m:
                return self.on_spubmsg(m.group(1)) or self.on_info(msg)
            m = self.SPRIVMSG_REX.search(msg)
            if m:
                return self.on_sprivmsg(m.group(1), m.group(2)) or self.on_info(msg)
            global LIST_FLAG
            m = self.LIST_HEADER_REX.search(msg)
            if m:
                LIST_FLAG = m.group(1)
                return self.on_info(msg)
            if LIST_FLAG:
                cur = LIST_FLAG
                LIST_FLAG = False
                return self.on_list(cur, msg) or self.on_info(msg)
            m = self.DEATH_REX.search(msg)
            if m:
                return self.on_death(m.group(1), m.group(2)) or self.on_info(msg)
            return self.on_info(msg)
        elif level == 'WARNING':
            return self.on_warning(msg)

    def on_line(self, line):
        m = self.LOG_REX.search(line)
        if m: return self.on_log(m.group(1), m.group(2).decode('utf-8', 'replace'))
        if self.EXC_REX.search(line): return self.on_exception(line)
        if self.IGN_REX.search(line): return True

is_players = False

class Pipe(object):
    def __init__(self, read, write):
        self.context = zmq.Context()
        self.inpath = read
        self.outpath = write
        self._stdin = self._stdout = None

    @property
    def stdin(self):
        if not self._stdin:
            self._stdin = self.context.socket(zmq.SUB)
            self._stdin.connect(self.inpath)
            self._stdin.setsockopt(zmq.SUBSCRIBE, '')
        return self._stdin

    @property
    def stdout(self):
        if not self._stdout:
            self._stdout = self.context.socket(zmq.REQ)
            self._stdout.connect(self.outpath)
        return self._stdout

    def send(self, *args):
        line = ' '.join(arg.encode('utf-8') if isinstance(arg, unicode) else arg for arg in args)
        self.stdout.send(line)
        msg = self.stdout.recv()
        assert msg == ''

    def recv(self):
        return self.stdin.recv()

    def __getattr__(self, name):
        def wrapper(*args): return self.send(name, *args)
        return wrapper

pipe = Pipe(read=sys.argv[5], write=sys.argv[6])
assert pipe.stdin and pipe.stdout

WORLDPATH = sys.argv[7]


def update_excepthook(pipe):
    origexcepthook = sys.excepthook
    def excepthook(ty, exc, tb):
        pipe.say(u'\2474봇 종료: %s %s' % (ty.__name__, str(exc)[:100]))
        return origexcepthook(ty, exc, tb)
    sys.excepthook = excepthook

def loop(pipe):
    poller = zmq.Poller()
    poller.register(pipe.stdin, zmq.POLLIN)
    poller.register(s, zmq.POLLIN)

    send('USER kaede kaede ruree.net :Furutani Kaede')
    send('NICK %s' % NICK)
    nexttime = time.time() + botimpl.TICK
    while True:
        line = ''
        while not line.endswith('\r\n'):
            ch = s.recv(1)
            if ch == '': break
            line += ch
        line = line.rstrip('\r\n')
        m = LINEPARSE.match(line)
        if m:
            prefix = m.group('prefix') or ''
            command = m.group('command').lower()
            param = (m.group('param') or '').split() or ['']
            message = m.group('message') or ''
            if command == 'ping':
                send('PONG :%s' % message, silent=True)
            else:
                print('<<', line)
                if command == '001': # welcome
                    send('JOIN %s' % CHANNEL)
                #elif command == 'invite' and len(param) > 0 and message:
                #    send('JOIN %s' % message)
                #    safeexec(None, getattr(botimpl, 'welcome', None), (message,))
                elif command == 'privmsg' and len(param) > 0 and param[0].startswith('#'):
                    if ''.join(message.split()).lower() in ('%s,reload' % NICK, '%s:reload' % NICK):
                        safeexec(param[0], reload, (botimpl,))
                        say(param[0], '재기동했습니다.')
                        # safeguard
                        if not isinstance(getattr(botimpl, 'TICK', None), int):
                            botimpl.TICK = 10
                        if not isinstance(getattr(botimpl, 'TIMEOUT', None), int):
                            botimpl.TIMEOUT = 5
                    else:
                        safeexec(param[0], getattr(botimpl, 'msg', None), (param[0], prefix, message))
                else:
                    safeexec(None, getattr(botimpl, 'line', None), (command, prefix, param, message))

        while True:
            result = poller.poll(max(0, nexttime - time.time()) * 1000) # msec!
            if result:
                if any(f is pipe.stdin for f, ev in result):
                    line = pipe.recv()
                    safeexec(None, getattr(botimpl, 'handle', None), (line,))
                    continue
                break
            if nexttime < time.time(): nexttime = time.time() + botimpl.TICK
            safeexec(None, getattr(botimpl, 'idle', None))

if __name__ == '__main__':
    sys.modules['bot'] = sys.modules['__main__']
    import botimpl # requires certain APIs

    update_excepthook(pipe)
    loop(pipe)

