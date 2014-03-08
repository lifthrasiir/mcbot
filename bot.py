#!/usr/env/bin python3.4
# coding=utf-8

import sys
import imp
import re
import functools
import collections
import argparse
import asyncio
import socket
import json
import signal
import traceback
import zmq

LINEPARSE = re.compile("^(:(?P<prefix>[^ ]+) +)?(?P<command>[^ ]+)(?P<param>( +[^:][^ ]*)*)(?: +:(?P<message>.*))?$")
IRC_ADDR = None
NICK     = None
PASSWORD = None
CHANNEL  = None
MC_READ_SOCK, MC_WRITE_SOCK = None, None
WORLDPATH = None

send_to_mc  = None  # initialized in mc_init
send_to_irc = None  # initialized in irc_loop_coro

def say(to, msg):
    if send_to_irc is not None and callable(send_to_irc):
        send_to_irc('PRIVMSG %s :%s' % (to, msg))
    else:
        raise Exception('Unexpected timing to call send_to_irc()')

def sayerr(to):
    ty, exc, tb = sys.exc_info()
    if to and ty != TimeoutError:
        say(to, '\00304!ERROR! %s (%s)' % (ty, exc))
    traceback.print_exception(ty, exc, tb)

def halt(msg='그럼 이만!'):
    send_to_irc('QUIT :%s' % msg);
    send_to_mc('tellraw', '@a', {'text': '[mcbot] 점검을 위해 봇을 잠시 내립니다.', 'color': 'red'})
    raise SystemExit

def async_do(future, func, args, kwargs):
    try:
        ret = func(*args, **kwargs)
    except Exception as exc:
        # TODO: sayerr(to)
        future.set_exception(exc)
    else:
        future.set_result(ret)

def safeexec(to, f, args=(), kwargs=None):
    # TODO: This does not restrict the duration of execution as expected.
    #       The primary reason is that coroutine-ignorant blocking cannot
    #       be handled by the asyncio package.
    # TODO: On *NIX systems we can use SIGARLAM as before.
    #       But how to do the same thing with Windows?
    fut = asyncio.Future()
    if kwargs is None: kwargs = {}
    loop = asyncio.get_event_loop()
    loop.call_soon(async_do, fut, f, args, kwargs)
    try:
        asyncio.async(asyncio.wait_for(fut, botimpl.TIMEOUT))
    except TimeoutError:
        raise


LIST_FLAG = False
class Handler(object):
    LOG_REX = re.compile(br'^\[\d\d:\d\d:\d\d\] \[Server thread\/([A-Z]+)\]\: (.*)$') 
    IGN_REX = re.compile(br'^(?:\d+ recipes|\d+ achievements|Closing listening thread)$')
    EXC_REX = re.compile(br'^(?:[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+: .*|\tat .*)$')
    LIST_HEADER_REX = re.compile(r'^There are (\d+)/\d+ players online:$')
    LOGIN_REX = re.compile(r'^([^\[]+)\[[^/]*/(.+?):\d+\] logged in with entity id (\d+) at \((-?\d+\.\d+), (-?\d+\.\d+), (-?\d+\.\d+)\)$')
    LOGOUT_REX = re.compile(r'^([^ ]+) lost connection: (.*)$')
    PUBMSG_REX = re.compile(r'^<([^>]+)> (.*)$')
    SPUBMSG_REX = re.compile(r'^\[Server\] (.*)$')
    SPRIVMSG_REX = re.compile(r'^You whisper to ([^:]+): (.*)$')
    DEATH_REX = re.compile(r'^([^\[ ]+) (.+)$')

    def on_info(self, msg): pass
    def on_warning(self, msg): pass
    def on_exception(self, line): pass

    def on_death(self, nick, how): pass
    def on_list(self, cur, nicklist): pass
    def on_login(self, nick, ip, entityid, coord): pass
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
        if m: return self.on_log(m.group(1).decode('ascii'), m.group(2).decode('utf8', 'replace'))
        if self.EXC_REX.search(line): return self.on_exception(line)
        if self.IGN_REX.search(line): return True

is_players = False


#def update_excepthook(pipe):
#    origexcepthook = sys.excepthook
#    def excepthook(ty, exc, tb):
#        send_to_mc('tellraw', '@a', {'text': '[mcbot] 봇 종료: %s %s' % (ty.__name__, str(exc)[:100]), 'color': 'red'})
#        return origexcepthook(ty, exc, tb)
#    sys.excepthook = excepthook

class AsyncZMQSocketReader:
    # A minimal recv-only adapter of a ZMQ socket.
    # Ref: https://github.com/fafhrd91/pyzmqtulip/blob/master/zmqtulip/core.py

    _loop = None
    _sock = None
    _sockfd = None

    def __init__(self, context, sock, loop=None):
        if loop is None:
            loop = asyncio.get_event_loop()
        self._loop = loop
        self._sock = sock
        self._sockfd = sock.getsockopt(zmq.FD)

    @asyncio.coroutine
    def recv(self, flags=0, copy=True, track=False):
        if flags & zmq.NOBLOCK:
            return sock.recv(flags, copy, track)
        flags |= zmq.NOBLOCK
        try:
            return zmq.Socket.recv(self._sock, flags, copy, track)
        except zmq.ZMQError as e:
            if e.errno != zmq.EAGAIN:
                raise
        fut = asyncio.Future(loop=self._loop)
        self._recv(fut, False, flags, copy, track)
        return (yield from fut)

    def _recv(self, fut, registered, *args):
        if registered:
            self._loop.remove_reader(self._sockfd)
        if fut.cancelled():
            return
        try:
            data = self._sock.recv(*args)
        except zmq.ZMQError as exc:
            if exc.errno != zmq.EAGAIN:
                fut.set_exception(exc)
                return
            self._loop.add_reader(self._sockfd, self._recv, fut, True, *args)
        except Exception as exc:
            fut.set_exception(exc)
        else:
            fut.set_result(data)

def mc_init(read_path, write_path):
    context = zmq.Context()
    _stdin = context.socket(zmq.SUB)
    _stdin.connect(read_path)
    _stdin.setsockopt(zmq.SUBSCRIBE, b'')
    wrapped_stdin = AsyncZMQSocketReader(context, _stdin)
    _stdout = context.socket(zmq.REQ)
    _stdout.connect(write_path)
    def _send(*args):
        def conv2str(arg):
            if isinstance(arg, dict) or isinstance(arg, list):  # for raw JSON messages
                return json.dumps(arg)
            elif isinstance(arg, str):
                return arg
            else:
                return str(arg)
        line = ' '.join(conv2str(arg) for arg in args)
        _stdout.send(line.encode('utf-8'))
        msg = _stdout.recv()
        assert msg == b''
    return _send, wrapped_stdin

@asyncio.coroutine
def mc_loop_coro(wrapped_stdin):
    while True:
        line = yield from wrapped_stdin.recv()
        if not line:
            print('Connection to the Minecraft server is lost.', file=sys.stderr)
            say(CHANNEL, '마인크래프트 서버와의 연결이 유실되었습니다. 관리자에게 문의하세요.')
        safeexec(None, getattr(botimpl, 'handle', None), (line,))

@asyncio.coroutine
def irc_loop_coro(irc_host, irc_port, *args, **kwargs):
    while True:
        irc_reader, irc_writer = yield from asyncio.open_connection(irc_host, irc_port, *args, **kwargs)
        def _send_to_irc(line, silent=False):
            msg = '%s\r\n' % line.replace('\r','').replace('\n','').replace('\0','')
            irc_writer.write(msg.encode('utf8'))
            if not silent: print('>>', line)
        global send_to_irc
        send_to_irc = _send_to_irc
        if PASSWORD:
            send_to_irc('PASS {0}'.format(PASSWORD))
        send_to_irc('USER {0} {1} {2} :mcbot'.format(NICK, socket.gethostname(), socket.getfqdn()))
        send_to_irc('NICK {0}'.format(NICK))
        send_to_mc('tellraw', '@a', {
            'text': '[mcbot] IRC 서버에 연결하였습니다.', 'color': 'green'
        })
        while True:
            # TODO: check if the other side has closed the connection.
            try:
                line = yield from irc_reader.readline()
            except EOFError:
                print("Connection to the IRC server is lost.", file=sys.stderr)
                send_to_mc('tellraw', '@a', {
                    'text': '[mcbot] IRC 서버와의 연결이 예기치 못하게 끊어졌습니다. 10초 후 다시 연결을 시도합니다.', 'color': 'red'
                })
                break
            if not line:
                print("Connection to the IRC server is closed.", file=sys.stderr)
                send_to_mc('tellraw', '@a', {
                    'text': '[mcbot] IRC 서버와의 연결이 끊어졌습니다. 10초 후 다시 연결을 시도합니다.', 'color': 'red'
                })
                break
            line = line.rstrip().decode('utf8')
            m = LINEPARSE.match(line)
            if m:
                prefix = m.group('prefix') or ''
                command = m.group('command').lower()
                param = (m.group('param') or '').split() or ['']
                message = m.group('message') or ''
                if command == 'ping':
                    send_to_irc('PONG :%s' % message, silent=True)
                else:
                    print('<<', line)
                    if command == '001':  # welcome
                        send_to_irc('JOIN %s' % CHANNEL)
                    #elif command == 'invite' and len(param) > 0 and message:
                    #    send_to_irc('JOIN %s' % message)
                    #    yield from safeexec(None, getattr(botimpl, 'welcome', None), (message,))
                    elif command == 'privmsg' and len(param) > 0 and param[0].startswith('#') and param[0] == CHANNEL:
                        if ''.join(message.split()).lower() in ('%s,reload' % NICK, '%s:reload' % NICK):
                            safeexec(param[0], imp.reload, (botimpl,))
                            say(param[0], '재기동했습니다.')
                            # A safe-guard for TICK & TIMEOUT values.
                            if not isinstance(getattr(botimpl, 'TICK', None), int):
                                botimpl.TICK = 10
                            if not isinstance(getattr(botimpl, 'TIMEOUT', None), int):
                                botimpl.TIMEOUT = 5
                        else:
                            safeexec(param[0], getattr(botimpl, 'msg', None), (param[0], prefix, message))
                    else:
                        safeexec(None, getattr(botimpl, 'line', None), (command, prefix, param, message))
        # We restart the IRC connection from here.
        yield from asyncio.sleep(10)

@asyncio.coroutine
def tick_coro():
    while True:
        yield from asyncio.sleep(botimpl.TICK)
        safeexec(None, getattr(botimpl, 'idle', None))

def main(args):
    loop = asyncio.get_event_loop()

    # Initialize zmq first.
    # This step is not a coroutine.
    global send_to_mc
    send_to_mc, wrapped_stdin = mc_init(MC_READ_SOCK, MC_WRITE_SOCK)   

    # Schedule the coroutines.
    ssl = args.use_ssl
    asyncio.async(mc_loop_coro(wrapped_stdin))
    asyncio.async(irc_loop_coro(IRC_ADDR[0], IRC_ADDR[1],
                                ssl=ssl, server_hostname=IRC_ADDR[0] if ssl else None))
    asyncio.async(tick_coro())

    # Let it serve!
    try:
        loop.run_forever()
    except (KeyboardInterrupt, SystemExit):
        print('Exit.')
    finally:
        loop.close()

if __name__ == '__main__':
    sys.modules['bot'] = sys.modules['__main__']
    import botimpl  # requires certain APIs

    argparser = argparse.ArgumentParser(
        description='A Minecraft-IRC mediator bot with some user management features.',
        epilog='Argument example: irc.ozinger.org 6670 mybot \'\' mychannel '
               'ipc:///var/run/mcbot/read ipc:///var/run/mcbot/write /var/run/minecraft/world',
    )
    argparser.add_argument('host',
                           help='set the IRC server\'s hostname.')
    argparser.add_argument('port', type=int,
                           help='set the IRC server\'s port number.')
    argparser.add_argument('nick',
                           help='set the IRC nickname to use.')
    argparser.add_argument('password',
                           help='set the IRC server password. If not required, '
                                'set this as an empty string.')
    argparser.add_argument('channel',
                           help='set the IRC channel to join. Do not prefix  Only messages from this channel '
                                'will be broadcasted to the Minecraft server.')
    argparser.add_argument('readsock',
                           help='set the 0proxy\'s read socket path. '
                                '(e.g., ip:///var/run/mcbot/read.sock)')
    argparser.add_argument('writesock',
                           help='set the 0proxy\'s write socket path.')
    argparser.add_argument('worldpath',
                           help='specify the path to Minecraft world.')
    argparser.add_argument('--ssl', dest='use_ssl', action='store_true', default=False,
                           help='use SSL when connecting to the IRC server.')
    args = argparser.parse_args()

    # Legacy global variables; but some are necessary for reference from botimpl.py.
    IRC_ADDR = (args.host, args.port)
    NICK = args.nick
    PASSWORD = args.password
    CHANNEL = args.channel
    MC_READ_SOCK, MC_WRITE_SOCK = args.readsock, args.writesock
    WORLDPATH = args.worldpath

    signal.signal(signal.SIGINT, lambda sig, frame: halt())
    signal.signal(signal.SIGTERM, lambda sig, frame: halt())

    print("Minecraft Bot starts!")
    main(args)
