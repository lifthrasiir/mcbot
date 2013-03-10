# coding=utf-8

TICK = 30
TIMEOUT = 20

import sys
import re
import os
import sqlite3
from contextlib import contextmanager

import hangul, hangul2
import death

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

def cmd(ismc, nick, cmd, args):
    reply = mcsay if ismc else say

    if cmd == 'help' or cmd == 'commands':
        reply(u'명령 목록: !commands, !players (!p), !who (!w), !set, !kit')
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

    def on_death(self, nick, why):
        msg = death.msg_i18n(why)
        if msg:
            say(u'** %s%s' % (nick, msg))
            return True
        else:
            return False

    def on_list(self, cur, nicklist):
        if not bot.is_players:
            return False
        if cur == '0':
            say(u'* 아무도 접속해 있지 않습니다')
        else:
            say(u'* %s명이 접속해 있습니다: %s' % (cur, nicklist))
        bot.is_players = False
        return True

    def on_login(self, nick, ip, entityid, coord):
        self.tell(nick, u'\247b루리넷 마인크래프트 서버에 오신 것을 환영합니다!')
        self.tell(nick, u'\247bhttp://mc.ruree.net/ 과 irc.ozinger.org #ruree 채널에도 와 보세요.')
        self.tell(nick, u'\247b중요 공지: 서버봇이 대규모로 업데이트되었습니다. 아직 안 하신 분께서는 !set intro 명령으로 자기 소개를 추가해 주세요.')
        say(u'*** %s님이 마인크래프트에 접속하셨습니다.' % nick)

    def on_logout(self, nick, reason):
        say(u'*** %s님이 마인크래프트에서 나가셨습니다.' % nick)

    def on_pubmsg(self, nick, text):
        print '[CHAT]', '<%s>' % nick, text

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
                    if cmd(True, nick, args[0], args[1:]): return True

            # IRC와 (한글 변환이 이루어졌을 경우) 마인크래프트에 재출력
            if converted != text:
                self.say(u'\2477<%s>\247r %s' % (nick, converted))
            say(u'<%s> %s' % (nick, converted))
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

def idle():
    pass

def handle(line):
    handler = BotHandler(bot.pipe)
    result = handler.on_line(line)
    if result is None:
        print '*** unhandled: %s' % line

def msg(channel, source, msg):
    msg = msg.decode('utf-8', 'replace')
    if msg.startswith('!'):
        args = msg[1:].split()
        if args:
            if cmd(False, getnick(source), args[0], args[1:]): return

    nick = getnick(source)
    if not nick or '\001' in msg: return # no CTCP yet
    bot.pipe.say(u'\2476[IRC] <%s>\247e %s' % (nick, msg.replace(u'\247', u'')))

def line(command, source, param, message):
    if command == 'join':
        nick = getnick(source)
        if nick: bot.pipe.say(u'\2476[IRC] %s님이 입장하셨습니다.' % nick)
    elif command == 'part':
        nick = getnick(source)
        if nick: bot.pipe.say(u'\2476[IRC] %s님이 나가셨습니다.' % nick)

def welcome(channel):
    pass

