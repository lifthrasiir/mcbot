# -*- encoding: utf-8 -*-
# 사용 방법: 여러분의 서버에 특화된 설정을 만드려면 이 파일을 "mcbot_config.py"로 복사한 후 수정하면 됩니다.

# 플레이어 로그인 시 보여줄 환영 메시지.
welcome_messages = [
    {'text': '', 'extra': [{'text': 'example', 'color': 'green'}, ' 마인크래프트 서버에 오신 것을 환영합니다.']},
    {'text': '유용한 링크: ', 'color': 'gray', 'extra': [{'text': '지도 보기', 'color': 'aqua', 'underlined': True, 'clickEvent': {'action': 'open_url', 'value': 'http://example.com/overview/'}, 'hoverEvent': {'action': 'show_text', 'value': 'http://example.com/overview/'}}]},
    {'text': '', 'color': 'gray', 'extra': [{'text': 'irc.example.com #example', 'color':'white'}, ' ', {'text': 'IRC 채널', 'color': 'gold'}, '에도 와보세요.']},
    {'text': '채팅 입력시 ', 'color': 'gray', 'extra': [{'text': '--', 'color':'gold'}, '을 앞에 붙이면 두벌식, ', {'text': '---', 'color':'gold'}, '을 앞에 붙이면 세벌식이 적용됩니다. (영타를 한글로 변환)']},
    {'text': '', 'color': 'gray', 'extra': [{'text': '중요 공지: ', 'color': 'red', 'bold': True}, '아직 자기소개를 추가하지 않은 분께서는 ', {'text': '!set intro', 'color': 'white'}, ' 명령으로 자기 소개를 추가해 주세요!']},
]

# 게시판 등이 있을 경우 사용할 RSS 모니터링 옵션.
# 전체를 None으로 설정할 경우 사용하지 않음.
rss_watcher = None

# 예제:
# rss_watcher = {
#   'url': 'http://bbs.mearie.org/mc/index.rss',
#   'check_interval': 3,
# }
