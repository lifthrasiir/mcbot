#! /usr/bin/env python3.4
# coding=utf-8

TICK = 20
TIMEOUT = 20

import sys
import re
import os, os.path
import asyncio
import time
from datetime import datetime, timedelta
import sqlite3
import urllib.parse, urllib.request
from xml.etree import cElementTree as ET
from contextlib import contextmanager

import hangul, hangul2
import death
import mcutil
try:
    import mcbot_config as config
except ImportError:
    import mcbot_defconfig as config

if __name__ != '__main__':
    import bot # recursive, but only called in the handler

DB = sqlite3.connect(os.path.join(os.path.dirname(__file__), 'db', 'kaede.db'))
DB.row_factory = sqlite3.Row
# Database 버전 체크
try:
    with open('db.version', 'r') as f:
        db_ver = int(f.read().strip())
except (IOError, ValueError):
    db_ver = 0

@contextmanager
def transaction():
    try:  
        yield DB
    except Exception:
        DB.rollback()
        raise 
    else: 
        DB.commit()

if db_ver == 0:
    DB.executescript('''
        create table if not exists users(
            mcid text not null primary key,
            ircnick text,
            status integer not null,
            intro text);
    ''')
    with transaction():
        # last_login은 SQLite의 datetime('now') 함수를 이용해 UTC 기준으로 저장된다.
        DB.executescript('''
            alter table users add playtime integer default 0;
            alter table users add last_login text;
        ''')
    db_ver = 1
    with open('db.version', 'w') as f:
        f.write(str(db_ver))
# 미래에 db에 추가되는 필드가 있으면 새로운 elif cluase를 추가한다.

STATUS_BLOCKED = -1
STATUS_INVITED = 0
STATUS_WHITELISTED = 1
STATUS_KITRECEIVED = 2

class RSSWatcher(object):

    def __init__(self, url):
        self.orig_url = url
        self.url = urllib.parse.urlsplit(url)
        self.prev_articles = None
        self.is_updating = False

    @asyncio.coroutine
    def get_articles(self):
        reader, writer = yield from asyncio.open_connection(self.url.hostname, 80)
        query = 'GET {url.path} HTTP/1.0\r\n' \
                'Host: {url.hostname}\r\n\r\n'.format(url=self.url)
        writer.write(query.encode('latin1'))
        response = yield from reader.read()
        reader.feed_eof()
        writer.close()
        header, body = response.split(b'\r\n\r\n', 1)
        header_lines = header.decode('utf8').split('\r\n')
        proto, status, msg = header_lines[0].split(' ', 2)
        assert proto.startswith('HTTP/1')
        if status != '200':
            raise RuntimeError('The URL {0} returned error: {1} {2}'.format(self.orig_url, status, msg))
        headers = {k: v for k, v in (item.split(': ') for item in header_lines[1:])}
        # TODO: replace above with aiohttp?
        # TODO: use proper encoding from headers['Content-Type']
        tree = ET.fromstring(body.decode('utf8'))
        articles = {}
        for item in tree.findall('./channel/item'):
            title = item.find('title').text
            nreplies = None
            m = re.search(r'^(.*?) \(([0-9]+)\)$', title) # sanitize for kareha
            if m:
                title = m.group(1)
                nreplies = int(m.group(2))
            guid = item.find('guid').text
            link = item.find('link').text
            articles[guid] = (link, title, nreplies)
        return articles

    @asyncio.coroutine
    def update(self):
        articles = yield from self.get_articles()
        added = []
        updated = []
        if self.prev_articles is None:
            # return empty lists because this is an initial check-up.
            return added, updated
        for guid, (link, title, nreplies) in articles.items():
            if guid not in self.prev_articles:
                added.append((link, title, nreplies))
            else:
                prevlink, prevtitle, prevnreplies = self.prev_articles[guid]
                if nreplies != prevnreplies:
                    updated.append((link, title, (nreplies or 0) - (prevnreplies or 0)))
        self.prev_articles = articles
        return added, updated


def say(s):
    if s: bot.say(bot.CHANNEL, s if isinstance(s, str) else str(s))

def mcsay(s):
    if s:
        if isinstance(s, dict):
            bot.send_to_mc('tellraw', "@a", s)
        else:
            bot.send_to_mc('tellraw', "@a", {"text": "", "extra": [{"text": s}]})

def escape_for_like(s, esc):
    return s.replace(esc, esc+esc).replace('_', esc+'_').replace('%', esc+'%')

def bold(ismc, s):
    if ismc: return '\247l%s\247r\2476' % s
    else: return '\002%s\002' % s

def readable_timedelta(td):
    if isinstance(td, timedelta):
        seconds = td.seconds
    else:
        seconds = int(td)
    periods = [
        ('년',   60*60*24*365),
        ('월',   60*60*24*30),
        ('일',   60*60*24),
        ('시간', 60*60),
        ('분',   60),
        ('초',   1)
    ]
    pieces = []
    for period_name, period_seconds in periods:
        if seconds >= period_seconds:
            period_value, seconds = divmod(seconds, period_seconds)
            pieces.append('%s%s' % (period_value, period_name))
    if len(pieces) == 0:
        return '0' + periods[-1][0]
    return ' '.join(pieces)

def get_user(ismc, nick, create=True):
    col = ('mcid' if ismc else 'ircnick')
    c = DB.execute('select * from users where %s like ? escape ? limit 1;' % col, (escape_for_like(nick, '|'), '|'))
    row = c.fetchone()
    if not row and ismc and create:
        status = STATUS_WHITELISTED
        DB.execute('insert into users(mcid,status) values(?,?);', (nick, status))
        row = {'mcid': nick, 'ircnick': None, 'status': status, 'intro': None, 'playtime': 0}
    return row

def to_ircnick(mcid):
    c = DB.execute('select ircnick from users where mcid like ? escape ? limit 1;', (escape_for_like(mcid, '|'), '|'))
    row = c.fetchone()
    nick = row['ircnick'] if row else None
    if nick and len(nick) > 1:
        return nick[:1] + '·' + nick[1:] # no beep on irc
    else:
        return nick

def cmd(ismc, nick, cmd, args):
    reply = mcsay if ismc else say
    cmd = cmd.lower()

    if cmd == 'help' or cmd == 'commands':
        reply('명령 목록: !commands, !players (!p), !who (!w), !set, !time (!t), !kit')
        return True

    if cmd == 'players' or cmd == 'p' or cmd == 'ㅔ':
        if ismc:
            reply('%s, 이 명령은 마인크래프트 안에서는 사용할 수 없습니다.' % nick)
        else:
            bot.is_players = True
            bot.send_to_mc('list')
        return True

    if cmd == 'whois' or cmd == 'who' or cmd == 'w' or cmd == 'ㅈ':
        if len(args) != 1:
            reply('사용법: !who <마인크래프트 아이디 또는 IRC 닉>')
            return True

        escaped = escape_for_like(args[0], '|')
        c = DB.execute('select * from users where mcid like ? escape ?;', (escaped, '|'))
        row = c.fetchone()
        if not row:
            c = DB.execute('select * from users where ircnick like ? escape ?;', (escaped, '|'))
            row = c.fetchone()
            if not row:
                reply('%s, 해당하는 사용자가 없습니다.' % nick)
                return True

        reply('사용자 정보: 마인크래프트 %s' % bold(ismc, row['mcid']) +
              (' / IRC %s' % bold(ismc, row['ircnick']) if row['ircnick'] else '') +
              (' / 총 플레이 시간 %s' % bold(ismc, readable_timedelta(row['playtime']))) +
              (' | 소개: %s' % row['intro'] if row['intro'] else ''))
        return True

    if cmd == 'set':
        key = ''
        if len(args) >= 2: key = args[0]

        if key == 'ircnick':
            if ismc:
                with transaction():
                    u = get_user(ismc, nick, create=True)
                    if u: DB.execute('update users set ircnick=? where mcid=?;', (args[1], u['mcid']))
                reply('%s, IRC 닉을 설정했습니다.' % nick)
            else:
                reply('%s, 이 명령은 마인크래프트 밖에서는 사용할 수 없습니다.' % nick)
        elif key == 'intro':
            intro = ' '.join(args[1:]) # 공백따위...
            with transaction():
                u = get_user(ismc, nick, create=True)
                if u: DB.execute('update users set intro=? where mcid=?;', (intro, u['mcid']))
            if u:
                reply('%s, 자기 소개를 설정했습니다.' % nick)
            else:
                reply('%s, 이 명령을 처음 사용할 때는 마인크래프트 안에서 사용해야 합니다.' % nick)
        else:
            reply('사용법: !set {ircnick|intro} <값>')

        return True

    if cmd == 'time' or cmd == 't' or cmd == 'ㅅ':
        leveldat = mcutil.parse_level_dat(bot.WORLDPATH)
        delta = leveldat['*LastUpdatedBefore']
        # 6000이 실제로는 정오니까 보정이 필요. 그리고 날짜는 1일째부터 시작하므로 그것도 보정.
        days, timeofday = divmod(leveldat['DayTime'] + int(delta * 20) + 30000, 24000)
        minutes = timeofday * 1440 / 24000
        reply('%d일째 %02d:%02d (%d초 전 갱신)' % (days, minutes/60, minutes%60, delta))
        return True

    if cmd == 'kit':
        if not ismc:
            reply('%s, 이 명령은 마인크래프트 밖에서는 사용할 수 없습니다.' % nick)
        else:
            u = get_user(ismc, nick)
            if not u or u['status'] < STATUS_WHITELISTED:
                reply('%s, !set 명령을 한 번 이상 써야 합니다.' % nick)
            elif u['status'] == STATUS_KITRECEIVED:
                reply('%s, 이미 기본 아이템을 받았으면 다시 받을 수 없습니다. 필요하다면 관리자를 요청하세요.' % nick)
            else:
                bot.send_to_mc('give', u['mcid'], '256') # iron shovel
                bot.send_to_mc('give', u['mcid'], '257') # iron pickaxe
                bot.send_to_mc('give', u['mcid'], '258') # iron axe
                bot.send_to_mc('give', u['mcid'], '292') # iron hoe
                bot.send_to_mc('give', u['mcid'], '267') # iron sword
                bot.send_to_mc('give', u['mcid'], '50', '64') # 64x torch
                bot.send_to_mc('give', u['mcid'], '297', '64') # 64x bread
                bot.send_to_mc('give', u['mcid'], '328') # minecart
                bot.send_to_mc('give', u['mcid'], '355') # bed
                with transaction():
                    DB.execute('update users set status=? where mcid=?;', (STATUS_KITRECEIVED, u['mcid']))
                reply('%s, 기본 아이템을 보내 드렸습니다. 만약 이상이 있다면 관리자에게 요청해 주세요.' % nick)
        return True

class BotHandler(bot.Handler):
    def __init__(self):
        self.codec2 = hangul2.Codec_AchimHangul2()
        self.codec3 = hangul.Codec_Hangul3()

    def on_info(self, msg):
        print('[INFO]', msg)
        return True

    def on_warning(self, msg):
        print('[WARNING]', msg)
        return True

    def on_exception(self, line):
        print('[EXCEPT]', line)
        return True

    def on_death(self, mcid, why):
        msg = death.msg_i18n(why)
        if msg:
            say('** %s%s' % (to_ircnick(mcid) or mcid, msg))
            return True
        else:
            return False

    def on_list(self, cur, mcidlist):
        if not bot.is_players:
            return False
        if cur == '0':
            say('* 아무도 접속해 있지 않습니다')
        else:
            mcidlist = mcidlist.split(', ')
            mcidlist = [to_ircnick(mcid) or mcid for mcid in mcidlist] # XXX 비효율적임
            say('* %s명이 접속해 있습니다: %s' % (cur, ', '.join(mcidlist)))
        bot.is_players = False
        return True

    def on_login(self, mcid, ip, entityid, coord):
        for msg in config.welcome_messages:
            bot.send_to_mc('tellraw', mcid, msg)
        say('*** %s님이 마인크래프트에 접속하셨습니다.' % (to_ircnick(mcid) or mcid))
        with transaction():
            DB.execute("update users set last_login=datetime('now') where mcid=?;", (mcid,))

    def on_logout(self, mcid, reason):
        tdiff = None
        with transaction():
            c = DB.execute('select last_login from users where mcid=?', (mcid,))
            row = c.fetchone()
            if row:
                if row['last_login'] is None:
                    # 이 경우는 기존 사용자가 로그인 중인 상태에서 봇을 업데이트한 경우.
                    # 언제 로그인했는지 알 수 없으므로 일단 0으로 초기화한다.
                    tdiff = timedelta(seconds=0)
                else:
                    now = datetime.utcnow()
                    last_login = datetime.strptime(row['last_login'], "%Y-%m-%d %H:%M:%S")
                    tdiff = now - last_login
                DB.execute("update users set playtime = playtime + ? where mcid=?;", (tdiff.seconds, mcid))
        if tdiff:
            say('*** %s님이 마인크래프트에서 나가셨습니다. (플레이 시간: %s)' % (to_ircnick(mcid) or mcid, readable_timedelta(tdiff)))
        else:
            say('*** %s님이 마인크래프트에서 나가셨습니다.' % (to_ircnick(mcid) or mcid))

    def on_pubmsg(self, mcid, text):
        print('[CHAT]', '<%s>' % mcid, text)

        parts = text.split('--')
        for i in range(1, len(parts), 2):
            if parts[i].startswith('-'):
                parts[i], _ = self.codec3.decode(parts[i][1:])
            else:
                parts[i], _ = self.codec2.decode(parts[i])
        converted = ''.join(parts)

        if converted.strip():
            # 명령처럼 보이면 그걸 우선시함
            if converted.startswith('!'):
                args = converted[1:].split()
                if args:
                    if cmd(True, mcid, args[0], args[1:]): return True

            # IRC와 (한글 변환이 이루어졌을 경우) 마인크래프트에 재출력
            if converted != text:
                bot.send_to_mc('tellraw', '@a', {'text': '', 'extra': [
                    {'text': '<%s> ' % mcid, 'color': 'gold'},
                    {'text': converted}
                ]})
            say('<%s> %s' % (to_ircnick(mcid) or mcid, converted))
        return True

    def on_spubmsg(self, text):
        print('[CHAT]', '<<', text)
        return True

    def on_sprivmsg(self, target, text):
        print('[CHAT]', '%s<<' % target, text)
        return True


def getnick(source):
    try:
        nick = source.split('!')[0]
        if nick == bot.NICK: return None
        return nick
    except Exception:
        return None

if config.rss_watcher:
    RSS = RSSWatcher(config.rss_watcher['url'])
else:
    RSS = None

@asyncio.coroutine
def update_rss_if_needed():
    global RSS
    if RSS is None:
        return None
    if RSS.is_updating:
        return None
    RSS.is_updating = True
    interval = config.rss_watcher['check_interval']
    while True:
        try:
            added, updated = yield from RSS.update()
        except Exception:
            import traceback
            traceback.print_exc()
            yield from asyncio.sleep(interval)
            interval = min(300, interval * 4)
        else:
            break
    RSS.is_updating = False
    print('RSSWatcher: added {0} articles, updated {1} articles.'.format(len(added), len(updated)))

    def sayboth(msg, title, link):
        say('## %s: \002%s\002 @ %s' % (msg, title, link))
        bot.send_to_mc('say', '\2472## %s: \247a%s\2472 @ %s' % (msg, title, link))
    for link, title, nreplies in added:
        sayboth('새 글이 올라왔습니다', title, link)
    for link, title, nnewreplies in updated:
        repliestext = '%d개의 ' % nnewreplies if nnewreplies > 1 else ''
        sayboth(repliestext + '새 답글이 올라왔습니다', title, link)


@asyncio.coroutine
def idle():
    # A timer function.
    yield from update_rss_if_needed()

def handle(line):
    handler = BotHandler()
    result = handler.on_line(line)
    if result is None:
        print('*** unhandled: %s' % line)

def msg(channel, source, msg):
    wascmd = False
    if msg.startswith('!'):
        args = msg[1:].split()
        if args:
            wascmd = cmd(False, getnick(source), args[0], args[1:])

    if not wascmd:
        nick = getnick(source)
        if nick and '\001' not in msg: # no CTCP yet
            bot.send_to_mc('tellraw', '@a', {'text': '', 'extra': [
                {'text': '[IRC] ', 'color': 'gold'},
                {'text': '<%s> %s' % (nick, msg.replace('\247', '')), 'color': 'white'}
            ]})

def line(command, source, param, message):
    if command == 'join':
        nick = getnick(source)
        if nick: bot.send_to_mc('tellraw', '@a', {'text': '', 'extra': [
            {'text': '[IRC] %s님이 입장하셨습니다.' % nick, 'color': 'gold'}
        ]})
    elif command == 'part':
        nick = getnick(source)
        if nick: bot.send_to_mc('tellraw', '@a', {'text': '', 'extra': [
            {'text': '[IRC] %s님이 나가셨습니다.' % nick, 'color': 'gold'}
        ]})

def welcome(channel):
    pass

