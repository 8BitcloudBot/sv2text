"""
ABogus 签名生成器 — 适配自 TikTokDownloader
为抖音 Web API 请求生成 a_bogus 签名参数。
"""

from random import choice, randint, random
from re import compile
from time import time
from urllib.parse import quote, urlencode

from gmssl import func, sm3


class ABogus:
    __filter = compile(r"%([0-9A-F]{2})")
    __arguments = [0, 1, 14]
    __ua_key = "\u0000\u0001\u000e"
    __end_string = "cus"
    __reg = [
        1937774191, 1226093241, 388252375, 3666478592,
        2842636476, 372324522, 3817729613, 2969243214,
    ]
    __str = {
        "s0": "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=",
        "s1": "Dkdpgh4ZKsQB80/Mfvw36XI1R25+WUAlEi7NLboqYTOPuzmFjJnryx9HVGcaStCe=",
        "s2": "Dkdpgh4ZKsQB80/Mfvw36XI1R25-WUAlEi7NLboqYTOPuzmFjJnryx9HVGcaStCe=",
        "s3": "ckdp1h4ZKsUB80/Mfvw36XIgR25+WQAlEi7NLboqYTOPuzmFjJnryx9HVGDaStCe",
        "s4": "Dkdpgh2ZmsQB80/MfvV36XI1R45-WUAlEixNLwoqYTOPuzKFjJnry79HbGcaStCe",
    }

    def __init__(self, user_agent: str, platform: str = "MacIntel"):
        self.chunk = []
        self.size = 0
        self.reg = self.__reg[:]
        self.ua_code = self.__char_code(
            self.__generate_result(
                self.__rc4_encrypt(user_agent, self.__ua_key),
                "s3",
            )
        )
        self.browser = self.__generate_browser_info(platform)
        self.browser_len = len(self.browser)
        self.browser_code = self.__char_code(self.browser)

    # ─── public ──────────────────────────────────────────────────────
    def get_value(self, url_params: dict | str, method: str = "GET") -> str:
        s1 = self.__generate_string_1()
        s2 = self.__generate_string_2(
            urlencode(url_params, quote_via=quote)
            if isinstance(url_params, dict) else url_params,
            method,
        )
        return self.__generate_result(s1 + s2, "s4")

    # ─── internal helpers ────────────────────────────────────────────
    @classmethod
    def __generate_string_1(cls):
        return (
            cls.__from_char_code(*cls.__random_list_1())
            + cls.__from_char_code(*cls.__random_list_2())
            + cls.__from_char_code(*cls.__random_list_3())
        )

    def __generate_string_2(self, url_params: str, method: str = "GET") -> str:
        start_time = int(time() * 1000)
        end_time = start_time + randint(4, 8)
        params_array = self.__sm3_to_array(
            self.__sm3_to_array(url_params + self.__end_string)
        )
        method_array = self.__sm3_to_array(
            self.__sm3_to_array(method + self.__end_string)
        )
        a = self.__list_4(
            (end_time >> 24) & 255,
            params_array[21], self.ua_code[23],
            (end_time >> 16) & 255,
            params_array[22], self.ua_code[24],
            (end_time >> 8) & 255, (end_time >> 0) & 255,
            (start_time >> 24) & 255, (start_time >> 16) & 255,
            (start_time >> 8) & 255, (start_time >> 0) & 255,
            method_array[21], method_array[22],
            int(end_time / 256 / 256 / 256 / 256) >> 0,
            int(start_time / 256 / 256 / 256 / 256) >> 0,
            self.browser_len,
        )
        a.extend(self.browser_code)
        a.append(self.__end_check_num(a))
        return self.__rc4_encrypt(self.__from_char_code(*a), "y")

    @classmethod
    def __from_char_code(cls, *args):
        return "".join(chr(code) for code in args)

    @classmethod
    def __char_code(cls, s):
        return [ord(char) for char in s]

    @classmethod
    def __end_check_num(cls, a):
        r = 0
        for i in a:
            r ^= i
        return r

    @classmethod
    def __random_list_1(cls, r=None, a=170, b=85, c=45):
        r = r or (random() * 10000)
        v = [r, int(r) & 255, int(r) >> 8]
        s = v[1] & b | 1
        v.append(s)
        s = v[1] & c | 2
        v.append(s)
        s = v[2] & b | 5
        v.append(s)
        s = v[2] & c | (c & a)
        v.append(s)
        return v[-4:]

    @classmethod
    def __random_list_2(cls, r=None, a=170, b=85):
        r = r or (random() * 10000)
        v = [r, int(r) & 255, int(r) >> 8]
        s = v[1] & b | 1
        v.append(s)
        s = v[1] & 0
        v.append(s)
        s = v[2] & b
        v.append(s)
        s = v[2] & 0
        v.append(s)
        return v[-4:]

    @classmethod
    def __random_list_3(cls, r=None, a=170, b=85):
        r = r or (random() * 10000)
        v = [r, int(r) & 255, int(r) >> 8]
        s = v[1] & b | 1
        v.append(s)
        s = v[1] & 0
        v.append(s)
        s = v[2] & b | 5
        v.append(s)
        s = v[2] & 0
        v.append(s)
        return v[-4:]

    @staticmethod
    def __list_4(a, b, c, d, e, f, g, h, i, j, k, m, n, o, p, q, r):
        return [
            44, a, 0, 0, 0, 0, 24, b, n, 0, c, d, 0, 0, 0, 1, 0, 239,
            e, o, f, g, 0, 0, 0, 0, h, 0, 0, 14, i, j, 0, k, m, 3, p,
            1, q, 1, r, 0, 0, 0,
        ]

    @classmethod
    def __rc4_encrypt(cls, plaintext, key):
        s = list(range(256))
        j = 0
        for i in range(256):
            j = (j + s[i] + ord(key[i % len(key)])) % 256
            s[i], s[j] = s[j], s[i]
        i = j = 0
        cipher = []
        for k in range(len(plaintext)):
            i = (i + 1) % 256
            j = (j + s[i]) % 256
            s[i], s[j] = s[j], s[i]
            t = (s[i] + s[j]) % 256
            cipher.append(chr(s[t] ^ ord(plaintext[k])))
        return "".join(cipher)

    @classmethod
    def __sm3_to_array(cls, data):
        if isinstance(data, str):
            b = data.encode("utf-8")
        else:
            b = bytes(data)
        h = sm3.sm3_hash(func.bytes_to_list(b))
        return [int(h[i:i + 2], 16) for i in range(0, len(h), 2)]

    @classmethod
    def __generate_browser_info(cls, platform="MacIntel"):
        inner_width = randint(1280, 1920)
        inner_height = randint(720, 1080)
        outer_width = randint(inner_width, 1920)
        outer_height = randint(inner_height, 1080)
        screen_y = choice((0, 30))
        return "|".join(str(i) for i in [
            inner_width, inner_height, outer_width, outer_height,
            0, screen_y, 0, 0, outer_width, outer_height,
            outer_width, outer_height, inner_width, inner_height,
            24, 24, platform,
        ])

    @classmethod
    def __generate_result(cls, s, e="s4"):
        r = []
        for i in range(0, len(s), 3):
            if i + 2 < len(s):
                n = (ord(s[i]) << 16) | (ord(s[i + 1]) << 8) | ord(s[i + 2])
            elif i + 1 < len(s):
                n = (ord(s[i]) << 16) | (ord(s[i + 1]) << 8)
            else:
                n = ord(s[i]) << 16
            for j, k in zip(range(18, -1, -6), (0xFC0000, 0x03F000, 0x0FC0, 0x3F)):
                if j == 6 and i + 1 >= len(s):
                    break
                if j == 0 and i + 2 >= len(s):
                    break
                r.append(cls.__str[e][(n & k) >> j])
        r.append("=" * ((4 - len(r) % 4) % 4))
        return "".join(r)
