# -*- coding: utf-8 -*-

import re

deathmsg = {
    '^was squashed by a falling anvil$': u'님이 모루에 깔려 사망하셨습니다.',
    '^was pricked to death$': u'님이 바늘에 찔려 사망하셨습니다.',
    '^walked into a cactus while trying to escape (.+)$': u'님이 %s로부터의 도망치다 선인장에 찔려 사망하셨습니다.',
    '^was shot by arrow$': u'님이 화살에 맞아 사망하셨습니다.',
    '^drowned$': u'님이 익사하셨습니다.',
    '^blew up$': u'님이 빵 터지셨습니다.',
    '^was blown up by creeper$': u'님이 크리퍼에 의해 펑 터지셨습니다.',
    '^hit the ground too hard$': u'님이 추락사 하셨습니다.',
    '^fell off a ladder$': u'님이 사다리에서 추락하셨습니다.',
    '^fell off some vines$': u'님이 덩굴에서 추락하셨습니다.',
    '^fell out of the water$': u'님이 물에서 추락하셨습니다.',
    '^fell from a high place$': u'님이 높은 곳에서 추락하셨습니다.',
    '^fell into a patch of fire$': u'님이 불구덩이로 추락하셨습니다.',
    '^fell into a patch of cacti$': u'님이 선인장 위로 추락하셨습니다.',
    '^went up in flames$': u'님이 화염에 휩싸여 사망하셨습니다.',
    '^burned to death$': u'님이 불에 타 죽으셨습니다.',
    '^was burnt to a crisp whilst fighting (.+)$': u'님이 %s와 싸우다 불에 타 소각되셨습니다.',
    '^walked into a fire whilst fighting (.+)$': u'님이 %s와 결투를 벌이다 제 발로 불에 걸어 들어가셨습니다.',
    '^was blown from a high place$': u'님이 가스트가 쏜 파이어볼에 맞고 떨어지셨습니다.',
    '^was slain by (.+)$': u'님이 %s에게 살해당하셨습니다',
    '^was shot by (.+)$': u'님이 %s에 의해 공기를 가르며 맞아 죽으셨습니다',
    '^was fireballed by (.+)$': u'님이 %s이 쏜 파이어볼에 맞아 죽으셨습니다.',
    '^was killed by (.+)$': u'님이 %s에게 죽임을 당하셨습니다.',
    '^got finished off by (.+) using (.+)$': u'님이 %s에게 %s으로 깔끔하게 방법 당하셨습니다.',
    '^was slain by (.+) using (.+)$': u'님이 %s에게 %s으로 살해당하셨습니다.',
    '^tried to swim in lava$': u'님이 열탕에서 목욕을 즐기셨습니다.',
    '^tried to swim in lava while trying to escape (.+)$': u'님이 %s로부터 도망치다 용암에 빠지셨습니다.',
    '^died$': u'님이 죽으셨습니다.',
    '^got finished off by (.+) using (.+)$': u'님이 %s님에게 %s로 방법 당하셨습니다.',
    '^was slain by (.+) using (.+)$': u'님이 %s님에게 %s로 살해당하셨습니다.',
    '^was was shot by (.+)$': u'님이 %s님이 쏜 화살에 맞아 사망하셨습니다.',
    '^was killed by (.+)$': u'님이 %s님이 던진 포션에 맞아 사망하셨습니다.',
    '^was killed by magic$': u'님이 마법에 의해 사망하셨습니다.',
    '^starved to death$': u'님이 배가 고파서 사망하셨습니다.',
    '^suffocated in a wall$': u'님이 9와 3/4 승강장에 가려다 벽에 껴 질식사 하셨습니다.',
    '^was killed while trying to hurt (.+)$': u'님이 %s에게 피해를 입히려다 방법당하셨습니다.',
    '^fell out of the world$': u'님이 세상 밖으로 떨어지셨습니다.',
    '^fell from a high place and fell out of the world$': u'님이 지구를 관통하셨습니다.',
    '^was knocked into the void by (.+)$': u'님이 %s님에 의해 자유를 찾으셨습니다.',
    '^withered away$': u'님이 위더스럽게 되셨습니다.',
}

deathmsg_re = {}
for key in deathmsg:
    deathmsg_re[re.compile(key)] = deathmsg[key]

def msg_i18n(why):
    for key in deathmsg_re:
        m = key.search(why)
        if m:
            return deathmsg_re[key] % m.groups()
    return False
