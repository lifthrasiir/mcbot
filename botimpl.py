# coding=utf-8

TICK = 30
TIMEOUT = 20

import sys
import re
import hangul, hangul2
import death

if __name__ != '__main__':
    import bot # recursive, but only called in the handler


def say(s):
    if s: bot.say(bot.CHANNEL, s.encode('utf-8'))

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
        if converted != text and converted.strip():
            self.say(u'\2477<%s>\247r %s' % (nick, converted))

        if converted.strip(): say(u'<%s> %s' % (nick, converted))
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
    if msg == '!players':
        bot.is_players = True
        bot.pipe.send('list')
        return
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

