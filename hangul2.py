# encoding: utf8

# CS322 Project 1: 한글입력기 오토마타 구현
#
# 작성자 : 20050145 김준기

# 주요 특징
# - 두벌식 자판배열 구현 (일부 다르게 동작하는 부분은 있음. 예: ㄱㅅ != ㄳ)
# - 초성 연타를 이용한 쌍자음 입력 가능
#   (단, 앞글자의 받침과 합성 가능한 경우는 쌍자음이 분리됨, 예: 업써->없서)
# - 최광무 교수님의 2.5벌식 겹모음 입력 가능 (예: ㅏ+ㅣ=ㅐ)
# - 조합이 완성되지 않은 글자도 일반 윈도우 환경처럼 낱자로 표시 (예: ㅋㅋㅋ)

# TODO: wrap the global definitions with a namespace

# 이 프로그램에서는 고유한 내부 한글코드로 먼저 조합한 후 출력할 때 변환한다.
# 내부 한글 코드는 Unicode 5.0 Compatibility Jamo 영역을 사용한다.
# 아래의 세 tuple은 프로그램 코드에서 직접 이용하지는 않으나 참고로 적어둔 것이다.
choseongs = (0, 1, 3, 6, 7, 8, 16, 17, 18, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29)
joongseongs = (30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50)
jongseongs = (0, 1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 19, 20, 21, 22, 23, 25, 26, 27, 28, 29)

# 두벌식 키배열
keymap2 = {
	'r': 0, 'R': 1, # ㄱ, ㄲ
	's': 3, 'S': 3, # ㄴ
	'e': 6, 'E': 7, # ㄷ, ㄸ
	'f': 8, 'F': 8, # ㄹ
	'a': 16, 'A': 16, # ㅁ
	'q': 17, 'Q': 18, # ㅂ, ㅃ
	't': 20, 'T': 21, # ㅅ, ㅆ
	'd': 22, 'D': 22, # ㅇ
	'w': 23, 'W': 24, # ㅈ, ㅉ
	'c': 25, 'C': 25, # ㅊ
	'z': 26, 'Z': 26, # ㅋ
	'x': 27, 'X': 27, # ㅌ
	'v': 28, 'V': 28, # ㅍ
	'g': 29, 'G': 29, # ㅎ
	'k': 30, 'K': 30, # ㅏ
	'i': 32, 'I': 32, # ㅑ
	'j': 34, 'J': 34, # ㅓ
	'u': 36, 'U': 36, # ㅕ
	'h': 38, 'H': 38, # ㅗ
	'y': 42, 'Y': 42, # ㅛ
	'n': 43, 'N': 43, # ㅜ
	'b': 47, 'B': 47, # ㅠ
	'm': 48, 'M': 48, # ㅡ
	'l': 50, 'L': 50, # ㅣ
	'o': 31, 'O': 33, # ㅐ, ㅒ
	'p': 35, 'P': 37, # ㅔ, ㅖ
}

# Automaton의 state들
START = 0
CHOSEONG = 10
CHOSEONG2 = 12
JOONGSEONG = 30
JOONGSEONG2 = 32
JONGSEONG = 50
JONGSEONG2 = 52
FINISH = 90		# CHOSEONG*에서 초성을 입력하거나, JOONGSEONG*태에서 모음을 입력한 경우
FINISH2 = 92	# JOONGSEONG 또는 JONGSEONG* 상태에서 모음을 입력한 경우

import codecs
from io import StringIO

# 보조 함수
def choose_index(key, array):
	"""array에서 key를 찾아 그 index를 반환한다."""
	i = 0
	for k in array:
		if key == k:
			return i
		i += 1
	return None

def choose(key, array, array2):
	"""array에서 key를 찾아 그 index에 해당하는 array2의 원소를 반환한다."""
	i = 0
	for k in array:
		if key == k:
			return array2[i]
		i += 1
	return None

def conv2unicode(queue):
	"""6칸의 tuple 혹은 list을 받아서 실제 unicode 문자로 변환한다. (초성용 2칸, 중성용 2칸, 종성용 2칸)
초성이나 모음만 단독으로 있는 경우에는 compatibility jamo 영역을 사용하여 정상적으로 출력되게 한다."""
	jamo_only = False
	has_jongseong = False
	c1, c2, c3 = -1, -1, -1
	
	q = []
	for i in range(6):
		q.append (queue[i])
	
	## 자음 처리
	#  쌍자음 연타 처리
	if q[0] == 0 and q[1] == 0:
		q[0], q[1] = 1, -1
	if q[0] == 6 and q[1] == 6:
		q[0], q[1] = 7, -1
	if q[0] == 17 and q[1] == 17:
		q[0], q[1] = 18, -1
	if q[0] == 20 and q[1] == 20:
		q[0], q[1] = 21, -1
	if q[0] == 23 and q[1] == 23:
		q[0], q[1] = 24, -1

	c1 = q[0]

	## 모음 처리
	#  합성 모음 처리
	if q[2] == 38:
		t = choose(q[3], (30, 31, 50), (39, 40, 41))
		if t != None:
			q[2], q[3] = t, -1
	if q[2] == 43:
		t = choose(q[3], (34, 35, 50), (44, 45, 46))
		if t != None:
			q[2], q[3] = t, -1
	if q[3] == 50:
		t = choose(q[2], (48, 30, 32, 34, 36), (49, 31, 33, 35, 37))
		if t != None:
			q[2], q[3] = t, -1

	c2 = q[2]

	## 받침 처리
	if q[4] != -1:
		has_jongseong = True
	# 합성 받침 처리
	if q[4] == 0:
		t = choose(q[5], (0, 20), (1, 2))
		if t != None:
			q[4], q[5] = t, -1
	if q[4] == 3:
		t = choose(q[5], (23, 29), (4, 5))
		if t != None:
			q[4], q[5] = t, -1
	if q[4] == 8:
		t = choose(q[5], (0, 16, 17, 20, 27, 28, 29), (9, 10, 11, 12, 13, 14, 15))
		if t != None:
			q[4], q[5] = t, -1
	if q[4] == 17 and q[5] == 20:
		q[4], q[5] = 19, -1
	if q[4] == 20 and q[5] == 20:
		q[4], q[5] = 21, -1
	
	c3 = q[4]

	## 단독 자소 처리
	if q[0] != -1 and q[2] == -1: # 자음만 있는 경우
		if has_jongseong:
			return ''
		c1 = q[0]
		jamo_only = True
	if q[0] == -1 and q[2] != -1: # 모음만 있는 경우
		if has_jongseong:
			return ''
		c1 = q[2]
		jamo_only = True

	## 최종 코드 생성
	if jamo_only:
		return chr(0x3131 + c1)
	else:
		c1 = choose_index(c1, (0, 1, 3, 6, 7, 8, 16, 17, 18, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29))
		c2 = c2 - 30
		c3 = choose(c3, (-1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25 ,26 ,27, 28, 29),
 					    (0, 1, 2, 3, 4, 5, 6, 7, 0, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 0, 18, 19, 20, 21, 22, 0, 23, 24, 25, 26, 27))
		if c1 == None or c2 == -31 or c3 == None:
			return ''
		return chr(0xAC00 + c1 * 588 + c2 * 28 + c3)

class H2Automaton(object):
	"""한글 두벌식 오토마타 클래스"""

	def __init__(self):
		self._init_queue()
		self.state = START
	
	def _init_queue(self):
		self.q = [-1, -1, -1, -1, -1, -1]

	@staticmethod
	def _is_choseong_pair(k1, k2):
		"""겹초성이 가능한지 검사한다."""
		choseong_pairs = (
			(0, 0), (6, 6), (17, 17), (20, 20), (23, 23), # ㄲ,ㄸ,ㅃ,ㅆ,ㅉ
		)
		for x in choseong_pairs:
			if x == (k1, k2):
				return True
		return False
	
	@staticmethod
	def _is_joongseong_pair(k1, k2):
		"""겹중성이 가능한지 검사한다."""
		joongseong_pairs = (
			(30, 50), (32, 50), (34,50), (36,50), # ㅐ,ㅒ,ㅔ,ㅖ
			(38, 30), (38, 31), (38, 50), # ㅘ,ㅙ,ㅚ
			(43, 34), (43, 35), (43, 50), # ㅝ,ㅞ,ㅟ
			(48, 50), # ㅢ
		)
		for x in joongseong_pairs:
			if x == (k1, k2):
				return True
		return False
	
	@staticmethod
	def _is_jongseong_pair(k1, k2):
		"""겹종성이 가능한지 검사한다."""
		jongseong_pairs = (
			(0, 0), (0, 20), # ㄲ,ㄳ
			(3, 23), (3, 29), # ㄵ,ㄶ
			(8, 0), (8, 16), (8, 17), (8, 20), (8, 27), (8, 28), (8, 29), # ㄺ,ㄻ,ㄼ,ㄽ,ㄾ,ㄿ,ㅀ,
			(17, 20), (20, 20), # ㅄ,ㅆ
		)
		for x in jongseong_pairs:
			if x == (k1, k2):
				return True
		return False
	
	def has_empty_queue(self):
		"""현재 합성 queue가 비어있는지 검사한다."""
		if [-1, -1, -1, -1, -1, -1] == self.q:
			return True
		return False
	
	def is_hangul(self, a):
		"""지정한 문자가 두벌식 자판 배열의 한글키 영역인지 검사한다."""
		try:
			k = keymap2[a]
		except:
			return False
		return True
	
	def transit(self, a):
		"""실제 알파벳을 입력받아 동작하는 transition function."""
	
		output = ''

		# Input check
		try:
			k = keymap2[a] # 입력된 키를 내부 한글 코드(Unicode compatibility Jamo)로 변환
		except:
			self.flush()
			return a
		is_vowel = (k >= 30 and k <= 50)							# 모음이라면 true
		is_consonant = (k >= 0 and k <= 29)							# 자음이라면 true
		can_be_jongseong = is_consonant and not (k in (7, 18, 24))	# 종성이 될 수 있는지 여부
		
		# State Transition
		old_state = self.state
		if self.state == START: # 오토마타의 시작
			if is_consonant:
				self.state = CHOSEONG
			else:
				self.state = JOONGSEONG
		elif self.state == CHOSEONG:
			if is_vowel:
				self.state = JOONGSEONG
			elif self._is_choseong_pair(self.q[0], k):
				self.state = CHOSEONG2
			else:
				self.state = FINISH
		elif self.state == CHOSEONG2:
			if is_vowel:
				self.state = JOONGSEONG
			else:
				self.state = FINISH
		elif self.state == JOONGSEONG:
			if can_be_jongseong:
				self.state = JONGSEONG
			elif self._is_joongseong_pair(self.q[2], k):
				self.state = JOONGSEONG2
			elif is_vowel:
				self.state = FINISH2
			else:
				self.state = FINISH
		elif self.state == JOONGSEONG2:
			if can_be_jongseong:
				self.state = JONGSEONG
			elif is_vowel:
				self.state = FINISH2
			else:
				self.state = FINISH
		elif self.state == JONGSEONG:
			if is_consonant and self._is_jongseong_pair(self.q[4], k):
				self.state = JONGSEONG2
			elif is_vowel:
				self.state = FINISH2
			else:
				self.state = FINISH
		elif self.state == JONGSEONG2:
			if is_vowel:
				self.state = FINISH2
			else:
				self.state = FINISH

		# 초성/중성/종성 별로 코드를 저장하고 적절한 출력 및 넘김 처리를 한다.
		i = choose(self.state, (CHOSEONG, CHOSEONG2, JOONGSEONG, JOONGSEONG2, JONGSEONG, JONGSEONG2), (0, 1, 2, 3, 4, 5))
		if i != None:
			self.q[i] = k
		if self.state == FINISH:

			output = conv2unicode(self.q)	# 글자 합성

			self._init_queue()
			self.q[0] = k
			self.state = CHOSEONG

		elif self.state == FINISH2:

			prev_key = self.q[4]
			self.q[4] = -1
			if self.q[5] != -1: # 겹받침 쪼개기
				self.q[4] = prev_key
				prev_key = self.q[5]
				self.q[5] = -1

			output = conv2unicode(self.q)	# 글자 합성

			self._init_queue()
			self.q[0] = prev_key
			self.q[2] = k
			self.state = JOONGSEONG

		return output
	
	def flush(self):
		"""조합 중인 글자의 조합을 강제로 끝낸다."""
		output = ''
		if not self.has_empty_queue():
			output = conv2unicode(self.q)
		self._init_queue()
		self.state = START
		return output

def to_hangul2(src):
	result = StringIO()
	automaton = H2Automaton()
	for a in src:
		# 한글자씩 읽으며 automata 작동 
		if automaton.is_hangul(a):
			result.write(automaton.transit(a))
		else:
			# 한글이 아닌 다른 글자일 경우 그대로 표시
			result.write(automaton.flush())
			result.write(a)
	# 문자열 끝에서 조합 중인 상태일 수 있으므로 그 상태에서 강제로 finish
	result.write(automaton.flush())
	return result.getvalue()

class Codec_AchimHangul2(codecs.Codec):

    BASECODEC = 'utf-8' # fallback codec of decoder

    # Unicode to key stroke
    def encode(self, data, errors='strict'):
        raise NotImplementedError()

    # key stroke to Unicode
    def decode(self, data, errors='strict'):
        if errors not in ('strict', 'ignore', 'replace'):
            raise ValueError("unknown error handling")

        if isinstance(data, str):
            s = data
        else:
            s = str(data, self.BASECODEC, errors)
        r = to_hangul2(s)
        return (r, len(r))

# vim: set ts=4 sts=4 sw=4 noet tw=120 fenc=utf8
