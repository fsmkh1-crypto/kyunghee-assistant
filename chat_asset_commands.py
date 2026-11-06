"""Pathless typed AI capabilities with a separate original-user intent guard.

No files, image bytes, model prose, arbitrary paths, or shell commands are
executed here. The UI resolves opaque IDs against a fresh local catalog.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
import unicodedata

ROLES = frozenset({"default", "cheer", "rest", "away", "warning", "leave",
                   "stats", "settings", "alert", "profile"})
MAX_CATALOG_IMAGES = 512
MAX_TOOL_ARGUMENT_BYTES = 2048
MAX_USER_TEXT = 400
_ID = re.compile(r"img_[0-9a-f]{12,64}\Z")
_NUMBERED_FILE = re.compile(
    r"(default|cheer|rest|away|warning|leave|stats|settings|alert|profile)_([0-9]{2})\.png\Z"
)
_CANONICAL_FILES = {
    "main_kyunghee.png": "default", "focus_cheer_kyunghee.png": "cheer",
    "rest_suggest_kyunghee.png": "rest", "away_kyunghee.png": "away",
    "warning_kyunghee.png": "warning", "leave_work_kyunghee.png": "leave",
    "stats_kyunghee.png": "stats", "settings_kyunghee.png": "settings",
    "alert_kyunghee.png": "alert", "profile_kyunghee.png": "profile",
}
_LEGACY_STEMS = {
    "default_full": "default", "playful": "default",
    "cheer_full": "cheer", "cheer": "cheer", "cute_cheer": "cheer",
    "worry": "warning", "nag": "warning", "praise": "leave", "master_face": "profile",
}
_KNOWN_FILES = {**_CANONICAL_FILES, **{
    f"{stem}.{extension}": role for stem, role in _LEGACY_STEMS.items()
    for extension in ("png", "webp", "jpg", "jpeg")
}}
ROLE_LABELS = {
    "default": "기본", "cheer": "응원", "rest": "휴식", "away": "자리 비움",
    "warning": "경고", "leave": "퇴근", "stats": "통계", "settings": "설정",
    "alert": "알림", "profile": "프로필",
}
_ROLE_ALIASES = {
    "default": ("default", "기본", "일반"),
    "cheer": ("cheer", "응원", "집중 응원"),
    "rest": ("rest", "휴식", "쉬는"),
    "away": ("away", "자리 비움", "자리비움", "부재"),
    "warning": ("warning", "경고", "걱정", "잔소리"),
    "leave": ("leave", "퇴근"), "stats": ("stats", "통계"),
    "settings": ("settings", "설정"), "alert": ("alert", "알림"),
    "profile": ("profile", "프로필", "얼굴"),
}
_ROLE_PATTERNS = {
    role: tuple(re.compile(
        r"(?<![a-z가-힣])" + re.escape(alias) +
        r"(?=$|[\s0-9_.]|이미지|사진|그림|포즈|으로|로|을|를)"
    ) for alias in aliases)
    for role, aliases in _ROLE_ALIASES.items()
}
_FILE_TOKEN = re.compile(r"(?<![a-z0-9_.-])[a-z][a-z0-9_.-]*\.(?:png|webp|jpeg|jpg)(?![a-z0-9_.-])")
_REQUEST = re.compile(
    r"바꿔|바꾸어\s*줘|변경(?:해|하|$|\s)|설정해|선택해|적용해|사용해|"
    r"보여\s*(?:줘|주|줄)|띄워\s*줘|불러\s*와|보고\s*싶"
)
_UNSAFE_INTENT = re.compile(
    r"만약|예를\s*들|예시|가정|한다고|한다면|라면|하면|바꾸면|바꾼다면|"
    r"바꾸는|변경하는|어떻게|방법|무슨|왜|라고|라는|냐고|"
    r"바꿨|변경했|선택했|적용했|설정했|보여줬|"
    r"않|말고|말아|말라|마세요|마요|하지\s*마|바꾸지\s*마|"
    r"안\s*(?:바꾸|바꿔|변경|보여)|아니|싫|취소|그대로|유지|"
    r"그리고|또는|혹은|둘\s*다|모두|각각|바꾸고|변경하고|선택하고|보여주고"
)
_QUOTES = frozenset("'\"“”‘’「」『』«»") | {chr(96)}
_AFFIRMATIVE_ENDINGS = tuple(sorted({
    "바꿔", "바꿔줘", "바꿔주세요", "바꿔줄래", "바꿔줄래요", "바꿔주실래요",
    "변경", "변경해", "변경해줘", "변경해주세요", "변경해줄래", "변경해줄래요",
    "설정", "설정해", "설정해줘", "설정해주세요",
    "선택", "선택해", "선택해줘", "선택해주세요",
    "적용", "적용해", "적용해줘", "적용해주세요",
    "사용해", "사용해줘", "사용해주세요",
    "보여줘", "보여주세요", "보여줄래", "보여줄래요", "보고싶어", "보고싶어요",
    "띄워줘", "띄워주세요", "불러와", "불러와줘",
}, key=len, reverse=True))
_COMPACT_ROLE = {alias.replace(" ", ""): role for role, aliases in _ROLE_ALIASES.items() for alias in aliases}
_ROLE_TOKEN = "(?:" + "|".join(re.escape(alias) for alias in sorted(_COMPACT_ROLE, key=len, reverse=True)) + ")"
_WHOLE_TARGETS = (
    re.compile(r"(?P<number>[0-9]{1,2})(?:번|호)?(?:(?:이미지|사진)?세트|이미지|사진|그림)\Z"),
    re.compile(r"(?:(?:이미지|사진)?세트|이미지|사진|그림)(?P<number>[0-9]{1,2})(?:번|호)?\Z"),
)
_ROLE_TARGETS = (
    re.compile(r"(?P<number>[0-9]{1,2})(?:번|호)?(?P<role>" + _ROLE_TOKEN + r")(?:이미지|사진|그림|포즈)?\Z"),
    re.compile(r"(?P<role>" + _ROLE_TOKEN + r")(?:이미지|사진|그림|포즈)?(?P<number>[0-9]{1,2})(?:번|호)?(?:이미지|사진|그림|포즈)?\Z"),
)
_ASSET_NOUN = re.compile(r"(?:이미지|사진|그림|에셋|세트)(?=$|[\s0-9]|으로|로|을|를|이|가|은|는|의|들|목록|리스트|바꿔|변경|보여|선택|적용|설정|좀|한번)")
_DISCUSSION_OR_REFUSAL = re.compile(
    r"만약|예를\s*들|예시|가정|한다면|라면|하면|바꾸면|바꾼다면|"
    r"바꾸는|변경하는|어떻게|방법|라고|라는|냐고|"
    r"바꿨|변경했|선택했|적용했|설정했|보여줬|"
    r"않|말고|말아|말라|마세요|마요|하지\s*마|바꾸지\s*마|주지\s*마|"
    r"안\s*(?:바꾸|바꿔|변경|보여)|안\s*돼|아니|싫|취소|그대로|유지|"
    r"필요\s*없|좋을까|될까|어떨까|괜찮을까"
)
_LIST_NOUN = r"(?:이미지세트|사진세트|이미지|사진|그림|에셋|세트)(?:들)?"
_LIST_PREFIX = r"(?:(?:현재|지금|설치된|사용가능한|사용할수있는|내장|전체|등록된))*"
_LIST_ENDING = r"(?:보여줘|보여주세요|알려줘|알려주세요|보고싶어|확인해줘)?"
_LIST_REQUESTS = (
    re.compile(_LIST_PREFIX + _LIST_NOUN + r"(?:목록|리스트)(?:을|를)?" + _LIST_ENDING + r"\Z"),
    re.compile(r"(?:설치된|사용가능한|사용할수있는|내장)" + _LIST_NOUN + r"(?:을|를)?" + _LIST_ENDING + r"\Z"),
    re.compile(r"(?:어떤|무슨)" + _LIST_NOUN + r"(?:이|가)?(?:있어|있니|있나요|있는지알려줘|사용가능해)\Z"),
    re.compile(_LIST_PREFIX + _LIST_NOUN + r"(?:이|가|은|는)?(?:뭐가있어|어떤게있어|몇개야|몇개있어|몇종류야|몇종류있어)\Z"),
)


def _valid_number(value: object) -> bool:
    return type(value) is int and 1 <= value <= 99


def _normalized_text(value: object) -> str:
    if type(value) is not str or not 0 < len(value) <= MAX_USER_TEXT:
        return ""
    if any(char in _QUOTES for char in value) or any(
        unicodedata.category(char) == "Cc" and not char.isspace() for char in value
    ):
        return ""
    return " ".join(unicodedata.normalize("NFKC", value).lower().split())


@dataclass(frozen=True)
class AssetChoice:
    asset_id: str
    role: str
    number: int | None = None
    filename: str = ""

    def __post_init__(self):
        if type(self.asset_id) is not str or not _ID.fullmatch(self.asset_id):
            raise ValueError("이미지 목록의 식별자가 올바르지 않습니다.")
        if type(self.role) is not str or self.role not in ROLES:
            raise ValueError("이미지 목록의 역할이 올바르지 않습니다.")
        if self.number is not None and not _valid_number(self.number):
            raise ValueError("이미지 목록의 번호가 올바르지 않습니다.")
        if type(self.filename) is not str or len(self.filename) > 80:
            raise ValueError("이미지 목록의 이름이 올바르지 않습니다.")
        if self.filename:
            name = self.filename.lower()
            numbered = _NUMBERED_FILE.fullmatch(name)
            if numbered and numbered[2] != "00":
                if numbered[1] != self.role or self.number not in (None, int(numbered[2])):
                    raise ValueError("이미지 목록의 이름과 역할 또는 번호가 다릅니다.")
                object.__setattr__(self, "number", int(numbered[2]))
            elif _KNOWN_FILES.get(name) != self.role or self.number is not None:
                raise ValueError("이미지 목록에는 알려진 기본 파일 이름만 사용할 수 있습니다.")
            object.__setattr__(self, "filename", name)

    @property
    def label(self) -> str:
        label = ROLE_LABELS[self.role]
        return f"{label} · {self.number:02}번" if self.number else f"{label} 이미지"


@dataclass(frozen=True)
class AssetCatalog:
    sets: tuple[int, ...] = ()
    images: tuple[AssetChoice, ...] = ()
    current_set: int | None = None
    current_asset_id: str | None = None

    def __post_init__(self):
        if type(self.sets) is not tuple or len(self.sets) > 99:
            raise ValueError("설치된 세트 목록이 올바르지 않습니다.")
        if any(not _valid_number(number) for number in self.sets) or len(set(self.sets)) != len(self.sets):
            raise ValueError("설치된 세트 목록이 올바르지 않습니다.")
        if type(self.images) is not tuple or len(self.images) > MAX_CATALOG_IMAGES:
            raise ValueError("설치된 이미지 목록이 너무 크거나 올바르지 않습니다.")
        if any(type(choice) is not AssetChoice for choice in self.images):
            raise ValueError("설치된 이미지 목록이 올바르지 않습니다.")
        ids = {choice.asset_id for choice in self.images}
        if len(ids) != len(self.images):
            raise ValueError("이미지 식별자가 중복되어 선택할 수 없습니다.")
        if self.current_set is not None and not _valid_number(self.current_set):
            raise ValueError("현재 세트 번호가 올바르지 않습니다.")
        if self.current_asset_id is not None and type(self.current_asset_id) is not str:
            raise ValueError("현재 이미지 식별자가 올바르지 않습니다.")
        object.__setattr__(self, "sets", tuple(sorted(self.sets)))
        if self.current_set not in self.sets:
            object.__setattr__(self, "current_set", None)
        if self.current_asset_id not in ids:
            object.__setattr__(self, "current_asset_id", None)


@dataclass(frozen=True)
class AssetCommand:
    kind: str
    number: int | None = None
    asset_id: str | None = None

    def __post_init__(self):
        if type(self.kind) is not str:
            raise ValueError("지원하지 않는 이미지 선택 명령입니다.")
        valid = (
            self.kind == "set" and _valid_number(self.number) and self.asset_id is None or
            self.kind == "file" and self.number is None and type(self.asset_id) is str and bool(_ID.fullmatch(self.asset_id)) or
            self.kind in {"list", "status"} and self.number is None and self.asset_id is None
        )
        if not valid:
            raise ValueError("지원하지 않는 이미지 선택 명령입니다.")


def _require_catalog(catalog: AssetCatalog) -> None:
    if type(catalog) is not AssetCatalog:
        raise ValueError("설치된 이미지 목록을 다시 확인해 주세요.")


def catalog_context(catalog: AssetCatalog) -> dict:
    """Bounded metadata only; custom names, paths and image bytes stay local."""
    _require_catalog(catalog)
    images = []
    for choice in catalog.images:
        item = {"asset_id": choice.asset_id, "role": choice.role, "label": choice.label}
        if choice.number is not None:
            item["number"] = choice.number
        if choice.filename:
            item["filename"] = choice.filename
        images.append(item)
    result = {"available_sets": list(catalog.sets), "images": images}
    if catalog.current_set is not None:
        result["current_set"] = catalog.current_set
    if catalog.current_asset_id is not None:
        result["current_asset_id"] = catalog.current_asset_id
    return result


def build_asset_tools(catalog: AssetCatalog) -> list[dict]:
    """Responses strict function schemas with enums from this request's catalog."""
    _require_catalog(catalog)
    tools = []
    if catalog.sets:
        tools.append({
            "type": "function", "name": "select_asset_set",
            "description": "사용자가 명확히 지정한 설치된 이미지 세트 전체를 선택합니다. 번호가 없거나 모호하면 호출하지 마세요.",
            "strict": True,
            "parameters": {"type": "object", "properties": {
                "number": {"type": "integer", "enum": list(catalog.sets)}},
                "required": ["number"], "additionalProperties": False},
        })
    if catalog.images:
        tools.append({
            "type": "function", "name": "select_asset_image",
            "description": "사용자가 명확히 지정한 이미지 한 장을 현재 표시 위치에 선택합니다. 파일 경로나 임의 이름은 받지 않습니다.",
            "strict": True,
            "parameters": {"type": "object", "properties": {
                "asset_id": {"type": "string", "enum": [choice.asset_id for choice in catalog.images]}},
                "required": ["asset_id"], "additionalProperties": False},
        })
    for name, description in (
        ("list_assets", "현재 설치된 세트와 선택 가능한 이미지 목록을 안내합니다. 이미지는 변경하지 않습니다."),
        ("get_timer_status", "사용자가 물어본 현재 시각과 타이머 상태를 로컬 실제 값으로 안내합니다. 설정은 바꾸지 않습니다."),
    ):
        tools.append({
            "type": "function", "name": name, "description": description, "strict": True,
            "parameters": {"type": "object", "properties": {}, "required": [],
                           "additionalProperties": False},
        })
    return tools


def _no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("이미지 명령의 인수가 중복되었습니다.")
        result[key] = value
    return result


def validate_asset_call(name: str, arguments: object, catalog: AssetCatalog) -> AssetCommand:
    """Validate a single API call; the UI separately guards original-user intent."""
    _require_catalog(catalog)
    if type(name) is not str or name not in {"select_asset_set", "select_asset_image", "list_assets", "get_timer_status"}:
        raise ValueError("지원하지 않는 이미지 명령입니다.")
    if type(arguments) is str:
        try:
            size = len(arguments.encode("utf-8"))
        except UnicodeError:
            raise ValueError("이미지 명령의 인수를 읽을 수 없습니다.") from None
        if size > MAX_TOOL_ARGUMENT_BYTES:
            raise ValueError("이미지 명령의 인수가 너무 깁니다.")
        try:
            arguments = json.loads(arguments, object_pairs_hook=_no_duplicate_keys)
        except (ValueError, TypeError, RecursionError):
            raise ValueError("이미지 명령의 인수를 읽을 수 없습니다.") from None
    if type(arguments) is not dict:
        raise ValueError("이미지 명령의 인수가 올바르지 않습니다.")
    if name in {"list_assets", "get_timer_status"}:
        if arguments:
            raise ValueError("조회 명령에는 인수를 사용할 수 없습니다.")
        return AssetCommand("list" if name == "list_assets" else "status")
    if name == "select_asset_set":
        if set(arguments) != {"number"} or not _valid_number(arguments["number"]):
            raise ValueError("세트 번호는 정수 01~99 하나로 지정해 주세요.")
        if arguments["number"] not in catalog.sets:
            raise ValueError("지정한 세트가 현재 설치되어 있지 않습니다.")
        return AssetCommand("set", number=arguments["number"])
    if set(arguments) != {"asset_id"} or type(arguments["asset_id"]) is not str:
        raise ValueError("이미지 식별자 하나로 지정해 주세요.")
    if arguments["asset_id"] not in {choice.asset_id for choice in catalog.images}:
        raise ValueError("지정한 이미지가 현재 목록에 없습니다.")
    return AssetCommand("file", asset_id=arguments["asset_id"])


def is_timer_status_query(user_text: str) -> bool:
    """Small read-only fallback recognizer, never an image-selection parser."""
    text = _normalized_text(user_text).rstrip(".!?~ ")
    if not text or _UNSAFE_INTENT.search(text) or re.search(r"알려주지|안\s*알려", text):
        return False
    text = re.sub(r"^(?:승아야|경희야)[,\s]+", "", text)
    patterns = (
        r"(?:(?:지금|현재)\s*)?몇\s*시(?:야|예요|에요|지|인지\s*알려\s*(?:줘|주세요))?",
        r"(?:(?:지금|현재)\s*)?(?:시간|시각)(?:을|이|은)?\s*(?:알려\s*줘|알려\s*주세요|보여\s*줘|몇\s*시야|얼마야)",
        r"(?:(?:지금|현재|오늘)\s*)?(?:타이머(?:\s*(?:시간|상태))?|(?:업무|작업|근무|집중|휴식|연속\s*사용|자리\s*비움|사용)\s*(?:시간|상태))(?:를|을|가|는)?\s*(?:알려\s*줘|알려\s*주세요|보여\s*줘|어때|얼마나\s*됐어|얼마야)",
        r"(?:(?:지금|현재)\s*)?상태(?:를|가|는)?\s*(?:알려\s*줘|알려\s*주세요|어때)",
        r"(?:(?:지금|현재|오늘)\s*)?(?:얼마나|몇\s*분|몇\s*시간)\s*(?:일했어|작업했어|쉬었어|썼어|사용했어)",
        r"(?:(?:지금|현재|오늘)\s*)?(?:일한|작업한|쉰|사용한)\s*시간(?:이|은)?\s*(?:얼마야|얼마나\s*됐어|알려\s*줘)",
    )
    return any(re.fullmatch(pattern, text) for pattern in patterns)


# Both names describe the same read-only predicate; no action is executed here.
is_timer_status_request = is_timer_status_query


def is_asset_change_request(user_text: str) -> bool:
    """Compatibility UI hint for mutations only, excluding lists and discussion."""
    return classify_chat_intent(user_text) in {"asset_change", "asset_ambiguous"}


def _explicit_selection(user_text: str):
    """Accept only finite positive endings and one exact, bounded target."""
    text = _normalized_text(user_text).rstrip(".!?~ ")
    if not text or _UNSAFE_INTENT.search(text) or "/" in text or "\\" in text or ":" in text:
        return None
    text = re.sub(r"^(?:승아야|경희야)[,\s]*", "", text)
    text = re.sub(r"^(?:지금|이제|오늘|혹시)\s*", "", text)
    compact = "".join(text.split())
    for ending in _AFFIRMATIVE_ENDINGS:
        if not compact.endswith(ending):
            continue
        target = compact[:-len(ending)]
        target = re.sub(r"(?:으로|로|을|를)$", "", target)
        if _FILE_TOKEN.fullmatch(target):
            return ("file", None, None, target)
        for pattern in _WHOLE_TARGETS:
            match = pattern.fullmatch(target)
            if match and _valid_number(int(match["number"])):
                return ("set", int(match["number"]), None, None)
        for pattern in _ROLE_TARGETS:
            match = pattern.fullmatch(target)
            if match and _valid_number(int(match["number"])):
                return ("role", int(match["number"]), _COMPACT_ROLE[match["role"]], None)
    return None


def _is_known_filename(filename: str) -> bool:
    numbered = _NUMBERED_FILE.fullmatch(filename)
    return filename in _KNOWN_FILES or bool(numbered and numbered[2] != "00")


def classify_chat_intent(user_text: str) -> str:
    """Route tools without treating ordinary conversation as an asset command.

    Categories: chat, asset_change, asset_ambiguous, asset_list, timer_status.
    This exposes no catalog and authorizes no write; the API call and original
    intent still pass the strict validator and fresh local selection guard.
    """
    text = _normalized_text(user_text).rstrip(".!?~ ")
    if not text:
        return "chat"
    if is_timer_status_query(user_text):
        return "timer_status"
    if _DISCUSSION_OR_REFUSAL.search(text):
        return "chat"
    compact = "".join(re.sub(r"^(?:승아야|경희야)[,\s]*", "", text).split())
    if any(pattern.fullmatch(compact) for pattern in _LIST_REQUESTS):
        return "asset_list"
    selection = _explicit_selection(user_text)
    if selection is not None:
        if selection[0] == "file" and not _is_known_filename(selection[3]):
            return "asset_ambiguous"
        return "asset_change"
    if not _REQUEST.search(text):
        return "chat"
    if _ASSET_NOUN.search(text):
        return "asset_ambiguous"
    filenames = _FILE_TOKEN.findall(text)
    if any(_is_known_filename(filename) for filename in filenames):
        return "asset_ambiguous"
    # A role alone is ordinary speech (휴식, 기본, 설정). Only a role plus a
    # numbered image identifier can imply image selection without an asset noun.
    has_role = any(pattern.search(text) for patterns in _ROLE_PATTERNS.values() for pattern in patterns)
    has_number = bool(re.search(r"[0-9]+", text))
    has_units = bool(re.search(r"[0-9]+\s*(?:분|초|시간|시|일|월|년|회|개)", text))
    if has_role and has_number and not has_units:
        return "asset_ambiguous"
    return "chat"


def allowed_asset_tools(user_text: str) -> tuple[str, ...]:
    """Request-scoped tool names; ordinary/unclear requests expose no tools."""
    intent = classify_chat_intent(user_text)
    if intent == "timer_status":
        return ("get_timer_status",)
    if intent == "asset_list":
        return ("list_assets",)
    if intent == "asset_change":
        selection = _explicit_selection(user_text)
        return ("select_asset_set",) if selection[0] == "set" else ("select_asset_image",)
    return ()


def build_scoped_asset_tools(catalog: AssetCatalog, user_text: str) -> list[dict]:
    """Offer only tools relevant to this original user message."""
    names = allowed_asset_tools(user_text)
    if not names:
        return []
    return [tool for tool in build_asset_tools(catalog) if tool["name"] in names]


def guard_asset_command(command: AssetCommand, user_text: str, catalog: AssetCatalog) -> AssetCommand:
    """Conservatively check an actual API selection against the user's identifier.

    No original number/file can be substituted with another installed choice.
    Unrecognized wording asks for clarification instead of changing an image.
    """
    _require_catalog(catalog)
    if type(command) is not AssetCommand:
        raise ValueError("이미지 명령을 확인할 수 없습니다.")
    if command.kind == "list":
        return command
    if command.kind == "status":
        if not is_timer_status_query(user_text):
            raise ValueError("현재 시간이나 타이머 상태를 직접 물어봐 주세요.")
        return command
    if command.kind == "set":
        validate_asset_call("select_asset_set", {"number": command.number}, catalog)
    else:
        validate_asset_call("select_asset_image", {"asset_id": command.asset_id}, catalog)
    requested = _explicit_selection(user_text)
    if requested is None:
        raise ValueError("변경 요청이 모호해서 이미지를 유지했어요. 번호와 역할 또는 정확한 파일 이름 하나를 직접 지정해 주세요.")
    scope, number, role, filename = requested
    if command.kind == "set":
        if scope != "set" or number != command.number:
            raise ValueError("요청한 세트 번호와 선택이 다르거나 범위가 모호해서 변경하지 않았어요.")
        return command
    choice = next(choice for choice in catalog.images if choice.asset_id == command.asset_id)
    if scope == "file":
        matches = [item for item in catalog.images if item.filename and item.filename == filename]
        if len(matches) != 1 or matches[0].asset_id != choice.asset_id:
            raise ValueError("지정한 파일 이름과 일치하는 이미지 하나를 확인할 수 없습니다.")
    elif scope == "role":
        matches = [item for item in catalog.images if item.number == number and item.role == role]
        if len(matches) != 1 or matches[0].asset_id != choice.asset_id:
            raise ValueError("지정한 역할과 번호에 해당하는 이미지 하나를 확인할 수 없습니다.")
    else:
        raise ValueError("이미지 한 장과 세트 전체의 선택 범위가 달라 변경하지 않았어요.")
    return command
