"""แท็บ "โค้ด": เขียน Exchange เป็นโค้ดที่ส่ง request เดิมได้ (Copy as curl / Python `requests` / JavaScript `fetch`)

ใช้ Exchange ใน store ซึ่งผ่าน Redaction แล้วเสมอ ค่าจริงจึงไม่มีทางอยู่ในโค้ด
header ที่ถูกซ่อนไม่ใส่ในโค้ดเลย (บอกชื่อไว้ใน comment) ส่วนค่าที่ถูกซ่อนใน URL หรือ body เหลือเป็น `••••`
"""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar
from urllib.parse import quote, urlsplit, urlunsplit

from inspector.models import CodeLanguage, CodeSnippet, HttpExchange, HttpRequest
from inspector.redactor import REDACTED

# header ที่ curl / requests / fetch ใส่ให้เอง (ใส่ซ้ำแล้วอาจผิด เช่น content-length ไม่ตรงกับ body)
CLIENT_MANAGED_HEADERS = frozenset({"host", "content-length", "accept-encoding", "connection"})
URL_SAFE_CHARACTERS = "!#$%&'()*+,/:;=?@[]~"  # คงไว้ตามเดิม ที่เหลือ (เช่น ภาษาไทย, ••••) เข้ารหัสเป็น %XX


@dataclass(frozen=True)
class ParsedJson:
    """body ที่ parse เป็น JSON ได้ (ห่อไว้เพราะ JSON `null` ก็เป็น None เหมือน "ไม่ใช่ JSON")"""

    value: object


@dataclass(frozen=True)
class CopyableRequest:
    """ส่วนของ request ที่ใส่ในโค้ดได้ เตรียมครั้งเดียวแล้วให้ทุกภาษาใช้ร่วมกัน

    สอนแนวคิด: value object — ข้อมูลที่สร้างแล้วแก้ไม่ได้ (frozen) ตัดสินใจเรื่อง "อะไรใส่ในโค้ดได้" ไว้ที่นี่ที่เดียว
    """

    method: str
    url: str
    headers: tuple[tuple[str, str], ...]
    body: str | None
    json_body: ParsedJson | None  # None = body ไม่ใช่ JSON (หรือไม่มี body)
    notes: tuple[str, ...]  # คำอธิบายที่ต้องขึ้นเป็น comment บนสุดของโค้ด

    @classmethod
    def of(cls, request: HttpRequest) -> "CopyableRequest":
        headers: list[tuple[str, str]] = []
        hidden: list[str] = []
        for name, value in request.headers.items():
            if name.startswith(":") or name.lower() in CLIENT_MANAGED_HEADERS:
                continue  # pseudo-header ของ HTTP/2 และ header ที่ตัวส่งใส่ให้เอง
            if REDACTED in value:
                hidden.append(name)
            else:
                headers.append((name, value))

        url = encode_url(request.url)
        body = request.body if request.body_kind not in ("none", "binary") else None
        notes: list[str] = []
        if hidden:
            notes.append(f"ไม่ใส่ header ที่ถูกซ่อนไว้: {', '.join(hidden)}")
        if request.body_kind == "binary":
            notes.append("body เป็น binary คัดลอกเป็นโค้ดไม่ได้")
        if REDACTED in request.url:
            notes.append(f"{REDACTED} คือค่าที่ถูกซ่อนไว้ ใน URL เขียนเป็น {encode_url(REDACTED)} ใส่ค่าของตัวเองแทนก่อนรัน")
        elif body is not None and REDACTED in body:
            notes.append(f"{REDACTED} คือค่าที่ถูกซ่อนไว้ ใส่ค่าของตัวเองแทนก่อนรัน")
        if body is not None and request.body_unscanned:
            notes.append("body นี้ไม่ได้ตรวจหาข้อมูลลับ — ตรวจเองก่อนแชร์หรือแสดงหน้าห้อง")
        return cls(
            method=request.method,
            url=url,
            headers=tuple(headers),
            body=body,
            json_body=parse_json(body) if request.body_kind == "json" else None,
            notes=tuple(notes),
        )


def encode_url(url: str) -> str:
    """เข้ารหัส path, query และ fragment เป็น %XX (host ไม่แตะ) ทุกเครื่องมือจะได้ส่ง URL เดียวกันเป๊ะ"""
    parts = urlsplit(url)
    return urlunsplit(
        parts._replace(
            path=quote(parts.path, safe=URL_SAFE_CHARACTERS),
            query=quote(parts.query, safe=URL_SAFE_CHARACTERS),
            fragment=quote(parts.fragment, safe=URL_SAFE_CHARACTERS),
        )
    )


def parse_json(body: str | None) -> ParsedJson | None:
    """parse body เป็น JSON ถ้าไม่ได้ (หรือไม่มี body) คืน None แล้วโค้ดจะส่ง body เป็นข้อความตามเดิม"""
    if body is None:
        return None
    try:
        return ParsedJson(json.loads(body))
    except ValueError:
        return None


class CodeWriter(ABC):
    """เขียน CopyableRequest เป็นโค้ดภาษาหนึ่ง

    สอนแนวคิด: polymorphism — ทุกภาษาเรียกผ่าน `snippet()` เหมือนกัน แต่ละ subclass เขียน `code()` ในแบบของตัวเอง
    เพิ่มภาษาใหม่ = เพิ่ม subclass หนึ่งตัวใน WRITERS ไม่ต้องแก้ที่อื่น
    """

    language: ClassVar[CodeLanguage]
    label: ClassVar[str]  # ข้อความบนปุ่มคัดลอก
    hint: ClassVar[str]  # เอาโค้ดไปรันที่ไหน
    comment: ClassVar[str]  # เครื่องหมาย comment ของภาษานั้น

    def snippet(self, request: CopyableRequest) -> CodeSnippet:
        notes = [f"{self.comment} {note}" for note in request.notes]
        code = "\n".join([*notes, self.code(request)])
        return CodeSnippet(language=self.language, label=self.label, hint=self.hint, code=code)

    @abstractmethod
    def code(self, request: CopyableRequest) -> str: ...


class CurlWriter(CodeWriter):
    """คำสั่ง curl สำหรับ bash / zsh / Git Bash (string อยู่ใน '...' จึงไม่มีอักขระไหนถูกตีความ)

    สอนแนวคิด: inheritance — รับ `snippet()` มาจาก CodeWriter เขียนเองแค่ `code()`
    """

    language = "curl"
    label = "Copy as curl"
    hint = "รันใน bash, zsh หรือ Git Bash (PowerShell ใช้ไม่ได้ เพราะ curl ของ PowerShell เป็นอีกคำสั่งหนึ่ง)"
    comment = "#"

    def code(self, request: CopyableRequest) -> str:
        first = " ".join(["curl", *self.method_option(request), shell_quote(request.url)])
        options = [f"-H {shell_quote(f'{name}: {value}')}" for name, value in request.headers]
        body = request.body
        if body is not None and body.isascii():
            options.append(f"--data-raw {shell_quote(body)}")
        elif body is not None:
            # curl ของ Windows (Git Bash) แปลง argument ตาม code page ภาษาไทยจึงเพี้ยน: ส่ง body ทาง stdin แทน
            first = f"printf '%s' {shell_quote(body)} | {first}"
            options.append("--data-binary @-")
        return " \\\n  ".join([first, *options])

    @staticmethod
    def method_option(request: CopyableRequest) -> list[str]:
        """curl เดา method เอง (ไม่มี body = GET, มี body = POST) บอกเฉพาะเมื่อเดาผิด"""
        if request.method == "HEAD":
            return ["--head"]  # -X HEAD ทำให้ curl ค้างรอ body ที่ไม่มีวันมา
        if request.method == "GET" and request.body is None:
            return []
        return ["-X", request.method]


class PythonRequestsWriter(CodeWriter):
    """สคริปต์ Python ที่ใช้ไลบรารี `requests` (body ที่เป็น JSON ใช้ `json=` จะได้เห็นเป็น dict)

    สอนแนวคิด: inheritance — รับ `snippet()` มาจาก CodeWriter เขียนเองแค่ `code()`
    """

    language = "python"
    label = "Copy as Python requests"
    hint = "ต้องติดตั้งก่อน: pip install requests"
    comment = "#"

    def code(self, request: CopyableRequest) -> str:
        arguments = [python_literal(request.method), python_literal(request.url)]
        if request.headers:
            arguments.append(f"headers={python_literal(dict(request.headers), 4)}")
        if request.json_body is not None:
            arguments.append(f"json={python_literal(request.json_body.value, 4)}")
        elif request.body is not None:
            encode = "" if request.body.isascii() else '.encode("utf-8")'  # requests ส่ง str เป็น latin-1
            arguments.append(f"data={python_literal(request.body)}{encode}")
        call = "".join(f"\n    {argument}," for argument in arguments)
        return "\n".join([
            "import requests",
            "",
            f"response = requests.request({call}\n)",
            "print(response.status_code)",
            "print(response.text)",
        ])


class JavaScriptFetchWriter(CodeWriter):
    """โค้ด JavaScript `fetch` สำหรับ DevTools Console (body ที่เป็น JSON ใช้ `JSON.stringify`)

    สอนแนวคิด: inheritance — รับ `snippet()` มาจาก CodeWriter เขียนเองแค่ `code()`
    """

    language = "fetch"
    label = "Copy as JavaScript fetch"
    hint = (
        "วางใน DevTools Console ของหน้าเว็บเดียวกัน (หน้าโดเมนอื่นติด CORS)"
        " เบราว์เซอร์ไม่ยอมให้ตั้ง header บางตัวเอง เช่น user-agent, referer"
    )
    comment = "//"

    def code(self, request: CopyableRequest) -> str:
        options: list[str] = []
        if request.method != "GET":
            options.append(f"method: {json.dumps(request.method)}")
        if request.headers:
            options.append(f"headers: {indented_json(dict(request.headers))}")
        if request.json_body is not None:
            options.append(f"body: JSON.stringify({indented_json(request.json_body.value)})")
        elif request.body is not None:
            options.append(f"body: {json.dumps(request.body, ensure_ascii=False)}")

        url = json.dumps(request.url)
        if options:
            call = f"fetch({url}, {{\n" + "".join(f"  {option},\n" for option in options) + "})"
        else:
            call = f"fetch({url})"
        return f"const response = await {call};\nconsole.log(response.status, await response.text());"


WRITERS: tuple[CodeWriter, ...] = (CurlWriter(), PythonRequestsWriter(), JavaScriptFetchWriter())


def code_snippets(exchange: HttpExchange) -> list[CodeSnippet]:
    """โค้ดของ Exchange นี้ทุกภาษา เรียงตามที่แสดงในแท็บ "โค้ด" """
    request = CopyableRequest.of(exchange.request)
    return [writer.snippet(request) for writer in WRITERS]


def shell_quote(text: str) -> str:
    """ครอบด้วย '...' ของ shell: ข้างในไม่มีอะไรถูกตีความ ยกเว้น ' เองที่ต้องปิด-ใส่-เปิดใหม่"""
    return "'" + text.replace("'", "'\\''") + "'"


def python_literal(value: object, indent: int = 0) -> str:
    """ค่าจาก JSON เป็น literal ของ Python (true → True, null → None) dict/list ยาวแยกบรรทัด"""
    pad = " " * indent
    if isinstance(value, dict) and value:
        items = [f"{pad}    {python_literal(k)}: {python_literal(v, indent + 4)}," for k, v in value.items()]
        return "{\n" + "\n".join(items) + f"\n{pad}}}"
    if isinstance(value, list) and value:
        items = [f"{pad}    {python_literal(v, indent + 4)}," for v in value]
        return "[\n" + "\n".join(items) + f"\n{pad}]"
    if isinstance(value, bool):
        return "True" if value else "False"
    if value is None:
        return "None"
    return json.dumps(value, ensure_ascii=False)  # str, ตัวเลข, {} และ [] เขียนแบบ JSON ได้เหมือนกัน


def indented_json(value: object) -> str:
    """JSON ที่จัดบรรทัดแล้ว เยื้องให้อยู่ใน object ของ fetch (เยื้อง 2 ช่อง)"""
    return json.dumps(value, indent=2, ensure_ascii=False).replace("\n", "\n  ")
