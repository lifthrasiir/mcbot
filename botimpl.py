# coding=utf-8

TICK = 30
TIMEOUT = 20

import sys
import re
import os
import os.path
import time
import sqlite3
import urllib2
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
DB.executescript('''
    create table if not exists users(
        mcid text not null primary key,
        ircnick text,
        status integer not null,
        intro text);
''')

STATUS_BLOCKED = -1
STATUS_INVITED = 0
STATUS_WHITELISTED = 1
STATUS_KITRECEIVED = 2

@contextmanager
def transaction():
    try:  
        yield DB
    except Exception:
        DB.rollback()
        raise 
    else: 
        DB.commit()

class RSSWatcher(object):
    def __init__(self, url):
        self.url = url
        self.prevtitles = self.get_titles()

    def get_titles(self):
        tree = ET.fromstring(urllib2.urlopen(self.url, timeout=1).read())
        titles = {}
        for item in tree.findall('./channel/item'):
            title = item.find('title').text
            nreplies = None
            m = re.search(ur'^(.*?) \(([0-9]+)\)$', title) # sanitize for kareha
            if m:
                title = m.group(1)
                nreplies = int(m.group(2))
            guid = item.find('guid').text
            link = item.find('link').text
            titles[guid] = (link, title, nreplies)
        return titles

    def update(self):
        titles = self.get_titles()
        added = []
        updated = []
        for guid, (link, title, nreplies) in titles.items():
            if guid not in self.prevtitles:
                added.append((link, title, nreplies))
            else:
                prevlink, prevtitle, prevnreplies = self.prevtitles[guid]
                if nreplies != prevnreplies:
                    updated.append((link, title, (nreplies or 0) - (prevnreplies or 0)))
        self.prevtitles = titles
        return added, updated


def say(s):
    if s: bot.say(bot.CHANNEL, s.encode('utf-8'))

def mcsay(s):
    if s: bot.pipe.say(u'\2476%s' % s)

def escape_for_like(s, esc):
    return s.replace(esc, esc+esc).replace(u'_', esc+u'_').replace(u'%', esc+u'%')

def bold(ismc, s):
    if ismc: return u'\247l%s\247r\2476' % s
    else: return u'\002%s\002' % s

def get_user(ismc, nick, create=True):
    col = ('mcid' if ismc else 'ircnick')
    c = DB.execute('select * from users where %s like ? escape ? limit 1;' % col, (escape_for_like(nick, u'|'), u'|'))
    row = c.fetchone()
    if not row and ismc and create:
        status = STATUS_WHITELISTED
        DB.execute('insert into users(mcid,status) values(?,?);', (nick, status))
        row = {u'mcid': nick, u'ircnick': None, u'status': status, u'intro': None}
    return row

def to_ircnick(mcid):
    c = DB.execute('select ircnick from users where mcid like ? escape ? limit 1;', (escape_for_like(mcid, u'|'), u'|'))
    row = c.fetchone()
    nick = row['ircnick'] if row else None
    if nick and len(nick) > 1:
        return nick[:1] + u'·' + nick[1:] # no beep on irc
    else:
        return nick

def cmd(ismc, nick, cmd, args):
    reply = mcsay if ismc else say

    if cmd == 'help' or cmd == 'commands':
        reply(u'명령 목록: !commands, !players (!p), !who (!w), !set, !time (!t), !kit')
        return True

    if cmd == 'players' or cmd == 'p':
        if ismc:
            reply(u'%s, 이 명령은 마인크래프트 안에서는 사용할 수 없습니다.' % nick)
        else:
            bot.is_players = True
            bot.pipe.send('list')
        return True

    if cmd == 'whois' or cmd == 'who' or cmd == 'w':
        if len(args) != 1:
            reply(u'사용법: !who <마인크래프트 아이디 또는 IRC 닉>')
            return True

        escaped = escape_for_like(args[0], u'|')
        c = DB.execute('select * from users where mcid like ? escape ?;', (escaped, u'|'))
        row = c.fetchone()
        if not row:
            c = DB.execute('select * from users where ircnick like ? escape ?;', (escaped, u'|'))
            row = c.fetchone()
            if not row:
                reply(u'%s, 해당하는 사용자가 없습니다.' % nick)
                return True

        reply(u'사용자 정보: 마인크래프트 %s' % bold(ismc, row['mcid']) +
              (u' / IRC %s' % bold(ismc, row['ircnick']) if row['ircnick'] else u'') +
              (u' | 소개: %s' % row['intro'] if row['intro'] else u''))
        return True

    if cmd == 'set':
        key = ''
        if len(args) >= 2: key = args[0]

        if key == 'ircnick':
            if ismc:
                with transaction():
                    u = get_user(ismc, nick, create=True)
                    if u: DB.execute('update users set ircnick=? where mcid=?;', (args[1], u['mcid']))
                reply(u'%s, IRC 닉을 설정했습니다.' % nick)
            else:
                reply(u'%s, 이 명령은 마인크래프트 밖에서는 사용할 수 없습니다.' % nick)
        elif key == 'intro':
            intro = u' '.join(args[1:]) # 공백따위...
            with transaction():
                u = get_user(ismc, nick, create=True)
                if u: DB.execute('update users set intro=? where mcid=?;', (intro, u['mcid']))
            if u:
                reply(u'%s, 자기 소개를 설정했습니다.' % nick)
            else:
                reply(u'%s, 이 명령을 처음 사용할 때는 마인크래프트 안에서 사용해야 합니다.' % nick)
        else:
            reply(u'사용법: !set {ircnick|intro} <값>')

        return True

    if cmd == 'time' or cmd == 't':
        leveldat = mcutil.parse_level_dat(bot.WORLDPATH)
        delta = leveldat['*LastUpdatedBefore']
        # 6000이 실제로는 정오니까 보정이 필요. 그리고 날짜는 1일째부터 시작하므로 그것도 보정.
        days, timeofday = divmod(leveldat['DayTime'] + int(delta * 20) + 30000, 24000)
        minutes = timeofday * 1440 / 24000
        reply(u'%d일째 %02d:%02d (%d초 전 갱신)' % (days, minutes/60, minutes%60, delta))
        return True

    if cmd == 'kit':
        if not ismc:
            reply(u'%s, 이 명령은 마인크래프트 밖에서는 사용할 수 없습니다.' % nick)
        else:
            u = get_user(ismc, nick)
            if not u or u['status'] < STATUS_WHITELISTED:
                reply(u'%s, !set 명령을 한 번 이상 써야 합니다.' % nick)
            elif u['status'] == STATUS_KITRECEIVED:
                reply(u'%s, 이미 기본 아이템을 받았으면 다시 받을 수 없습니다. 필요하다면 관리자를 요청하세요.' % nick)
            else:
                bot.pipe.give(u['mcid'], '256') # iron shovel
                bot.pipe.give(u['mcid'], '257') # iron pickaxe
                bot.pipe.give(u['mcid'], '258') # iron axe
                bot.pipe.give(u['mcid'], '292') # iron hoe
                bot.pipe.give(u['mcid'], '267') # iron sword
                bot.pipe.give(u['mcid'], '50', '64') # 64x torch
                bot.pipe.give(u['mcid'], '297', '64') # 64x bread
                bot.pipe.give(u['mcid'], '328') # minecart
                bot.pipe.give(u['mcid'], '355') # bed
                with transaction():
                    DB.execute('update users set status=? where mcid=?;', (STATUS_KITRECEIVED, u['mcid']))
                reply(u'%s, 기본 아이템을 보내 드렸습니다. 만약 이상이 있다면 관리자에게 요청해 주세요.' % nick)
        return True

class BotHandler(bot.Handler):
    def __init__(self, pipe):
        self.pipe = pipe
        self.codec2 = hangul2.Codec_AchimHangul2()
        self.codec3 = hangul.Codec_Hangul3()

    def __getattr__(self, name):
        return getattr(self.pipe, name)

    def on_info(self, msg):
        print '[INFO]', msg
        return True

    def on_warning(self, msg):
        print '[WARNING]', msg
        return True

    def on_exception(self, line):
        print '[EXCEPT]', line
        return True

    def on_death(self, mcid, why):
        msg = death.msg_i18n(why)
        if msg:
            say(u'** %s%s' % (to_ircnick(mcid) or mcid, msg))
            return True
        else:
            return False

    def on_list(self, cur, mcidlist):
        if not bot.is_players:
            return False
        if cur == '0':
            say(u'* 아무도 접속해 있지 않습니다')
        else:
            mcidlist = mcidlist.split(', ')
            mcidlist = [to_ircnick(mcid) or mcid for mcid in mcidlist] # XXX 비효율적임
            say(u'* %s명이 접속해 있습니다: %s' % (cur, ', '.join(mcidlist)))
        bot.is_players = False
        return True

    def on_login(self, nick, ip, entityid, coord):
        for msg in config.welcome_messages:
            self.tell(nick, msg)
        say(u'*** %s님이 마인크래프트에 접속하셨습니다.' % nick)

    def on_logout(self, mcid, reason):
        say(u'*** %s님이 마인크래프트에서 나가셨습니다.' % (to_ircnick(mcid) or mcid))

    def on_pubmsg(self, mcid, text):
        print '[CHAT]', '<%s>' % mcid, text

        parts = text.split('--')
        for i in xrange(1, len(parts), 2):
            if parts[i].startswith('-'):
                parts[i], _ = self.codec3.decode(parts[i][1:])
            else:
                parts[i], _ = self.codec2.decode(parts[i])
        converted = u''.join(parts)

        if converted.strip():
            # 명령처럼 보이면 그걸 우선시함
            if converted.startswith('!'):
                args = converted[1:].split()
                if args:
                    if cmd(True, mcid, args[0], args[1:]): return True

            # IRC와 (한글 변환이 이루어졌을 경우) 마인크래프트에 재출력
            if converted != text:
                self.say(u'\2477<%s>\247r %s' % (mcid, converted))
            say(u'<%s> %s' % (to_ircnick(mcid) or mcid, converted))
        return True

    def on_spubmsg(self, text):
        print '[CHAT]', '<<', text
        return True

    def on_sprivmsg(self, target, text):
        print '[CHAT]', '%s<<' % target, text
        return True


def getnick(source):
    try:
        nick = source.split('!')[0].decode('utf-8', 'replace')
        if nick.encode('utf-8') == bot.NICK: return None
        return nick
    except Exception:
        return None

if config.rss_watcher:
    RSS = RSSWatcher(config.rss_watcher['url'])
else:
    RSS = None

LAST_RSS = time.time()
def update_rss_if_needed():
    global RSS, LAST_RSS
    if RSS is None:
        return
    now = time.time()
    interval = config.rss_watcher['check_interval']
    if now - LAST_RSS < interval: return
    try:
        added, updated = RSS.update()
    except Exception:
        import traceback
        traceback.print_exc()
        LAST_RSS = now + (interval * 4) # 에러가 났을 경우 딜레이를 좀 더 길게 준다.
        return
    else:
        LAST_RSS = now

    def sayboth(msg, title, link):
        say(u'## %s: \002%s\002 @ %s' % (msg, title, link))
        bot.pipe.say(u'\2472## %s: \247a%s\2472 @ %s' % (msg, title, link))
    for link, title, nreplies in added:
        sayboth(u'새 글이 올라왔습니다', title, link)
    for link, title, nnewreplies in updated:
        repliestext = u'%d개의 ' % nnewreplies if nnewreplies > 1 else u''
        sayboth(repliestext + u'새 답글이 올라왔습니다', title, link)

def everytime():
    update_rss_if_needed()

def idle():
    everytime()

def handle(line):
    handler = BotHandler(bot.pipe)
    result = handler.on_line(line)
    if result is None:
        print '*** unhandled: %s' % line

    everytime()

def msg(channel, source, msg):
    msg = msg.decode('utf-8', 'replace')
    wascmd = False
    if msg.startswith('!'):
        args = msg[1:].split()
        if args:
            wascmd = cmd(False, getnick(source), args[0], args[1:])

    if not wascmd:
        nick = getnick(source)
        if nick and '\001' not in msg: # no CTCP yet
            bot.pipe.say(u'\2476[IRC] <%s>\247e %s' % (nick, msg.replace(u'\247', u'')))

    everytime()

def line(command, source, param, message):
    if command == 'join':
        nick = getnick(source)
        if nick: bot.pipe.say(u'\2476[IRC] %s님이 입장하셨습니다.' % nick)
    elif command == 'part':
        nick = getnick(source)
        if nick: bot.pipe.say(u'\2476[IRC] %s님이 나가셨습니다.' % nick)

    everytime()

def welcome(channel):
    pass

