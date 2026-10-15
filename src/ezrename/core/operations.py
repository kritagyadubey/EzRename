"""The renaming toolkit: every operation the GUI and the CLI can apply.

An operation is a small, serialisable transformation applied to the *stem* and
*extension* of a file name. The same objects drive the live preview, the CLI
and the executor, so both interfaces are guaranteed to agree on the result.

Operations never touch the filesystem: they only compute names. All validation
happens before anything is renamed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields
from pathlib import Path
from string import Formatter
from typing import Any, ClassVar, Iterable, Optional, Sequence

from .naming import join_name, sanitize_fragment, split_name

# --------------------------------------------------------------------------- #
# Context and errors
# --------------------------------------------------------------------------- #


@dataclass
class NameContext:
    """Mutable name being transformed, plus the metadata operations may use."""

    original: str
    stem: str
    ext: str            # without the dot, "" when there is none
    index: int = 0      # 0-based position of the file in the ordered selection
    path: Optional[Path] = None
    size: int = 0
    mtime: float = 0.0
    ctime: float = 0.0
    atime: float = 0.0
    prefix: str = ""    # user-defined prefix available to templates
    suffix: str = ""    # user-defined suffix available to templates

    @classmethod
    def from_name(
        cls,
        name: str,
        *,
        index: int = 0,
        path: Optional[Path] = None,
        size: int = 0,
        mtime: float = 0.0,
        ctime: float = 0.0,
        atime: float = 0.0,
    ) -> "NameContext":
        stem, ext = split_name(name)
        return cls(
            original=name,
            stem=stem,
            ext=ext,
            index=index,
            path=path,
            size=size,
            mtime=mtime,
            ctime=ctime,
            atime=atime,
        )

    @property
    def name(self) -> str:
        """The current file name after everything applied so far."""

        return join_name(self.stem, self.ext)

    def touch(self) -> None:
        """Hook for subclasses/tests; operations may mutate the context freely."""

    def clone(self) -> "NameContext":
        return NameContext(**{f.name: getattr(self, f.name) for f in fields(self)})


class OperationError(Exception):
    """Raised when an operation itself is misconfigured.

    These are shown to the user *before* anything is renamed, for example an
    invalid regular expression.
    """


class FileOperationError(Exception):
    """Raised when an operation cannot be applied to one specific file."""

    def __init__(self, message: str, *, skip: bool = False) -> None:
        super().__init__(message)
        self.message = message
        #: ``True`` means "leave this file alone", ``False`` means "this is a
        #: real error the user must look at". Both block the file.
        self.skip = skip


# --------------------------------------------------------------------------- #
# Operations
# --------------------------------------------------------------------------- #


class Operation:
    """Base class for all rename operations."""

    type: ClassVar[str] = "operation"
    label: ClassVar[str] = "Operation"
    description: ClassVar[str] = "Base operation"
    category: ClassVar[str] = "General"

    def validate(self) -> None:
        """Raise :class:`OperationError` for an unusable configuration."""

    def apply(self, ctx: NameContext) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def summary(self) -> str:
        """One-line description used by the GUI and the CLI preview."""

        return self.label

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"type": self.type}
        for info in fields(self):  # type: ignore[arg-type]
            payload[info.name] = getattr(self, info.name)
        return payload

    def __str__(self) -> str:  # pragma: no cover - convenience
        return self.summary()


@dataclass
class FindReplace(Operation):
    """Replace text in the name, optionally with a regular expression."""

    type: ClassVar[str] = "find_replace"
    label: ClassVar[str] = "Find and replace"
    description: ClassVar[str] = "Replace text in file names, with optional regular expressions"
    category: ClassVar[str] = "Text"

    find: str = ""
    replace: str = ""
    use_regex: bool = False
    case_sensitive: bool = True
    replace_all: bool = True
    scope: str = "stem"  # stem | ext | both | full

    def validate(self) -> None:
        if self.scope not in ("stem", "ext", "both", "full"):
            raise OperationError(f"unknown scope '{self.scope}'")
        if self.use_regex and self.find:
            try:
                re.compile(self.find)
            except re.error as exc:
                raise OperationError(f"invalid regular expression: {exc}") from exc

    def _substitute(self, text: str) -> str:
        if not self.find:
            return text
        count = 0 if self.replace_all else 1
        if self.use_regex:
            flags = 0 if self.case_sensitive else re.IGNORECASE
            return re.sub(self.find, self.replace, text, count=count, flags=flags)
        if self.case_sensitive:
            return text.replace(self.find, self.replace, count if count else -1)
        pattern = re.compile(re.escape(self.find), re.IGNORECASE)
        return pattern.sub(lambda _match: self.replace, text, count=count)

    def apply(self, ctx: NameContext) -> None:
        if not self.find:
            return
        if self.scope in ("stem", "both"):
            ctx.stem = self._substitute(ctx.stem)
        if self.scope in ("ext", "both"):
            ctx.ext = self._substitute(ctx.ext)
        if self.scope == "full":
            ctx.stem = self._substitute(join_name(ctx.stem, ctx.ext))
            ctx.ext = ""

    def summary(self) -> str:
        mode = "regex" if self.use_regex else "literal"
        flags = []
        if not self.case_sensitive:
            flags.append("ignore case")
        if not self.replace_all:
            flags.append("first only")
        where = {"stem": "", "ext": " in extension", "both": " everywhere", "full": " on full name"}
        suffix = f" ({', '.join(flags)})" if flags else ""
        return f"Replace '{self.find}' with '{self.replace}' ({mode}{where.get(self.scope, '')}){suffix}"


@dataclass
class PrefixSuffix(Operation):
    """Add or remove a prefix/suffix, in front of or behind the extension."""

    type: ClassVar[str] = "prefix_suffix"
    label: ClassVar[str] = "Prefix / suffix"
    description: ClassVar[str] = "Add or strip text at the start or end of file names"
    category: ClassVar[str] = "Text"

    prefix: str = ""
    suffix: str = ""
    suffix_after_extension: bool = False
    remove_prefix: str = ""
    remove_suffix: str = ""
    case_sensitive: bool = True

    def _matches(self, text: str, other: str) -> bool:
        if self.case_sensitive:
            return text == other
        return text.casefold() == other.casefold()

    def apply(self, ctx: NameContext) -> None:
        stem = ctx.stem
        if self.remove_prefix and len(self.remove_prefix) <= len(stem):
            if self._matches(stem[: len(self.remove_prefix)], self.remove_prefix):
                stem = stem[len(self.remove_prefix):]
        if self.remove_suffix and len(self.remove_suffix) <= len(stem):
            if self._matches(stem[len(stem) - len(self.remove_suffix):], self.remove_suffix):
                stem = stem[: len(stem) - len(self.remove_suffix)]
        stem = f"{self.prefix}{stem}"
        if self.suffix:
            if self.suffix_after_extension:
                stem = f"{join_name(stem, ctx.ext)}{self.suffix}"
                ctx.ext = ""
            else:
                stem = f"{stem}{self.suffix}"
        ctx.stem = stem

    def validate(self) -> None:
        if self.prefix and any(char in self.prefix for char in '\\/:*?"<>|'):
            raise OperationError("prefix contains characters that are not allowed in file names")
        if self.suffix and any(char in self.suffix for char in '\\/:*?"<>|'):
            raise OperationError("suffix contains characters that are not allowed in file names")

    def summary(self) -> str:
        parts = []
        if self.remove_prefix:
            parts.append(f"remove prefix '{self.remove_prefix}'")
        if self.remove_suffix:
            parts.append(f"remove suffix '{self.remove_suffix}'")
        if self.prefix:
            parts.append(f"add prefix '{self.prefix}'")
        if self.suffix:
            where = "after the extension" if self.suffix_after_extension else "before the extension"
            parts.append(f"add suffix '{self.suffix}' ({where})")
        detail = ", ".join(parts) if parts else "nothing configured"
        return f"Prefix/suffix: {detail} [{'match case' if self.case_sensitive else 'ignore case'}]"


ROMAN_VALUES = ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
                (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"))

ALPHA_STYLES = ("alpha_lower", "alpha_upper")
ROMAN_STYLES = ("roman_lower", "roman_upper")


def _alpha_number(value: int) -> str:
    """Spreadsheet style letters: 1 -> a, 27 -> aa."""

    if value < 1:
        value = 1
    letters = ""
    while value > 0:
        value, remainder = divmod(value - 1, 26)
        letters = chr(ord("a") + remainder) + letters
    return letters


def _roman_number(value: int) -> str:
    if value < 1 or value > 3999:
        raise FileOperationError("roman numerals only support numbers from 1 to 3999")
    out = []
    remainder = value
    for amount, numeral in ROMAN_VALUES:
        count, remainder = divmod(remainder, amount)
        out.append(numeral * count)
    return "".join(out)


@dataclass
class Numbering(Operation):
    """Sequential numbering with configurable placement and styles."""

    type: ClassVar[str] = "numbering"
    label: ClassVar[str] = "Sequential numbering"
    description: ClassVar[str] = "Number files in order, with padding, style and placement options"
    category: ClassVar[str] = "Order"

    start: int = 1
    step: int = 1
    padding: int = 3
    separator: str = "_"
    position: str = "prefix"       # prefix | suffix | replace
    style: str = "decimal"         # decimal | alpha_lower | alpha_upper | roman_lower | roman_upper
    prefix: str = ""               # text placed before the number itself
    suffix: str = ""               # text placed after the number itself

    def validate(self) -> None:
        if self.position not in ("prefix", "suffix", "replace"):
            raise OperationError(f"unknown number position '{self.position}'")
        if self.style not in ("decimal",) + ALPHA_STYLES + ROMAN_STYLES:
            raise OperationError(f"unknown numbering style '{self.style}'")
        if self.padding < 0:
            raise OperationError("padding cannot be negative")
        if self.padding > 20:
            raise OperationError("padding above 20 is not useful")

    def render(self, index: int) -> str:
        value = self.start + index * self.step
        if self.style == "decimal":
            if value < 0:
                raise FileOperationError("numbering would produce a negative number")
            return str(value).zfill(self.padding)
        if self.style in ALPHA_STYLES:
            if value < 1:
                raise FileOperationError("letter numbering starts at 1")
            letters = _alpha_number(value)
            letters = letters.upper() if self.style == "alpha_upper" else letters
            return letters.rjust(self.padding, "0")
        numeral = _roman_number(value)
        return numeral.upper() if self.style == "roman_upper" else numeral.lower()

    def apply(self, ctx: NameContext) -> None:
        number = f"{self.prefix}{self.render(ctx.index)}{self.suffix}"
        if self.position == "prefix":
            ctx.stem = f"{number}{self.separator}{ctx.stem}"
        elif self.position == "suffix":
            ctx.stem = f"{ctx.stem}{self.separator}{number}"
        else:
            ctx.stem = number

    def summary(self) -> str:
        where = {"prefix": "before the name", "suffix": "after the name", "replace": "replacing the name"}
        bits = [f"start {self.start}", f"step {self.step}"]
        if self.style == "decimal":
            bits.append(f"{self.padding}-digit")
        else:
            bits.append(self.style.replace("_", " "))
        return f"Numbering {where[self.position]} ({', '.join(bits)}, separated by '{self.separator}')"


@dataclass
class CaseConvert(Operation):
    """Upper/lower/title/sentence case conversion."""

    type: ClassVar[str] = "case"
    label: ClassVar[str] = "Case"
    description: ClassVar[str] = "Convert names to UPPER, lower, Title or Sentence case"
    category: ClassVar[str] = "Format"

    mode: str = "lower"  # upper | lower | title | sentence
    scope: str = "stem"  # stem | ext | both

    def validate(self) -> None:
        if self.mode not in ("upper", "lower", "title", "sentence"):
            raise OperationError(f"unknown case mode '{self.mode}'")
        if self.scope not in ("stem", "ext", "both"):
            raise OperationError(f"unknown scope '{self.scope}'")

    def _convert(self, text: str) -> str:
        if self.mode == "upper":
            return text.upper()
        if self.mode == "lower":
            return text.lower()
        if self.mode == "sentence":
            lowered = text.lower()
            for index, char in enumerate(lowered):
                if char.isalpha():
                    return lowered[:index] + char.upper() + lowered[index + 1:]
            return lowered
        # Title case across spaces, dashes, underscores and dots.
        pieces = re.split(r"([\s_\-\.]+)", text)
        return "".join(
            piece[:1].upper() + piece[1:].lower() if piece and not re.fullmatch(r"[\s_\-\.]+", piece) else piece
            for piece in pieces
        )

    def apply(self, ctx: NameContext) -> None:
        if self.scope in ("stem", "both"):
            ctx.stem = self._convert(ctx.stem)
        if self.scope in ("ext", "both"):
            ctx.ext = self._convert(ctx.ext)

    def summary(self) -> str:
        scope = {"stem": "file name", "ext": "extension", "both": "name and extension"}[self.scope]
        return f"Convert {scope} to {self.mode} case"


@dataclass
class Separators(Operation):
    """Whitespace, separator and character cleanup."""

    type: ClassVar[str] = "separators"
    label: ClassVar[str] = "Separators & cleanup"
    description: ClassVar[str] = "Normalise spaces, separators, duplicate words and stray characters"
    category: ClassVar[str] = "Format"

    spaces_to: str = ""            # "" keeps spaces, "_"/"-"/custom replaces them
    collapse_repeats: bool = False  # "a   b" -> "a_b" (repeat of the separator char)
    trim_whitespace: bool = True
    dedupe_words: bool = False
    strip_chars: str = ""
    replace_from: str = ""
    replace_to: str = ""

    def validate(self) -> None:
        if self.replace_from and len(self.replace_from) != len(self.replace_to):
            raise OperationError(
                "'replace character' needs one target character for each source character"
            )
        if len(self.spaces_to) > 1:
            raise OperationError("the space replacement must be a single character")

    def _clean(self, text: str) -> str:
        if self.spaces_to:
            text = text.replace(" ", self.spaces_to)
        if self.collapse_repeats:
            target = self.spaces_to or " "
            text = re.sub(re.escape(target) + r"{2,}", target, text)
        text = re.sub(r"[ \t]{2,}", " " if not self.spaces_to else self.spaces_to, text)
        if self.replace_from:
            table = str.maketrans(self.replace_from, self.replace_to)
            text = text.translate(table)
        if self.strip_chars:
            for char in self.strip_chars:
                text = text.replace(char, "")
        if self.dedupe_words:
            text = self._dedupe(text)
        if self.trim_whitespace:
            text = text.strip()
        return text

    def _dedupe(self, text: str) -> str:
        """Collapse runs of an identical repeated token: ``a_a_b`` -> ``a_b``."""

        pieces = re.split(r"([\s_\-.]+)", text)
        out: list[str] = []
        previous: Optional[str] = None
        for piece in pieces:
            if re.fullmatch(r"[\s_\-.]+", piece or ""):
                out.append(piece)
                continue
            key = piece.casefold()
            if key and key == previous:
                # drop the token and the separator that preceded it
                if out and re.fullmatch(r"[\s_\-.]+", out[-1] or ""):
                    out.pop()
                continue
            previous = key
            out.append(piece)
        return "".join(out)

    def apply(self, ctx: NameContext) -> None:
        ctx.stem = self._clean(ctx.stem)
        if self.spaces_to:
            ctx.ext = ctx.ext.strip()

    def summary(self) -> str:
        bits = []
        if self.spaces_to:
            bits.append(f"spaces to '{self.spaces_to}'")
        if self.collapse_repeats:
            bits.append("collapse repeats")
        if self.dedupe_words:
            bits.append("remove duplicate words")
        if self.strip_chars:
            bits.append(f"remove characters '{self.strip_chars}'")
        if self.replace_from:
            bits.append(f"'{self.replace_from}' to '{self.replace_to}'")
        if self.trim_whitespace:
            bits.append("trim whitespace")
        return "Cleanup: " + ", ".join(bits) if bits else "Cleanup (no change)"


@dataclass
class ExtensionChange(Operation):
    """Extension management: change, re-case or remove."""

    type: ClassVar[str] = "extension"
    label: ClassVar[str] = "Extension"
    description: ClassVar[str] = "Change, re-case or remove file extensions (no format conversion)"
    category: ClassVar[str] = "Extension"

    new_extension: str = ""   # "" keeps the current one
    case: str = "keep"        # keep | lower | upper
    remove: bool = False
    only_when: str = ""       # act only on these extensions, e.g. "jpg,png"

    def validate(self) -> None:
        if self.case not in ("keep", "lower", "upper"):
            raise OperationError(f"unknown extension case '{self.case}'")
        cleaned = self.new_extension.lstrip(".")
        if any(char in cleaned for char in '<>:"/\\|?* '):
            raise OperationError("extension contains characters that are not allowed in file names")

    def matches(self, ext: str) -> bool:
        if not self.only_when.strip():
            return True
        wanted = {part.strip().lstrip(".").casefold() for part in self.only_when.split(",") if part.strip()}
        return ext.casefold() in wanted

    def apply(self, ctx: NameContext) -> None:
        if not self.matches(ctx.ext):
            return
        ext = ctx.ext
        if self.remove:
            ctx.ext = ""
            return
        if self.new_extension:
            ext = self.new_extension.lstrip(".")
        if self.case == "lower":
            ext = ext.lower()
        elif self.case == "upper":
            ext = ext.upper()
        ctx.ext = ext

    def summary(self) -> str:
        bits = []
        if self.remove:
            bits.append("remove extension")
        elif self.new_extension:
            bits.append(f"set extension to '.{self.new_extension.lstrip('.')}'")
        if self.case != "keep":
            bits.append(f"make extension {self.case}case")
        if self.only_when.strip():
            bits.append(f"only for {self.only_when}")
        if not bits:
            bits.append("no extension change")
        return "Extension: " + ", ".join(bits)


@dataclass
class DateInsert(Operation):
    """Insert filesystem date/time information into the name."""

    type: ClassVar[str] = "date"
    label: ClassVar[str] = "Date & time"
    description: ClassVar[str] = "Insert the modified, created or accessed date into file names"
    category: ClassVar[str] = "Metadata"

    format: str = "%Y-%m-%d"
    source: str = "mtime"     # mtime | ctime | atime
    position: str = "prefix"  # prefix | suffix
    separator: str = "_"
    fallback: str = "empty"   # empty | original | error

    def validate(self) -> None:
        if self.source not in ("mtime", "ctime", "atime"):
            raise OperationError(f"unknown date source '{self.source}'")
        if self.position not in ("prefix", "suffix"):
            raise OperationError(f"unknown date position '{self.position}'")
        if self.fallback not in ("empty", "original", "error"):
            raise OperationError(f"unknown fallback '{self.fallback}'")
        try:
            from datetime import datetime

            datetime(2026, 1, 2, 3, 4, 5).strftime(self.format)
        except (ValueError, TypeError) as exc:
            raise OperationError(f"invalid date format: {exc}") from exc

    def timestamp(self, ctx: NameContext) -> Optional[float]:
        value = {"mtime": ctx.mtime, "ctime": ctx.ctime, "atime": ctx.atime}.get(self.source, 0.0)
        return value if value and value > 0 else None

    def apply(self, ctx: NameContext) -> None:
        from datetime import datetime

        stamp = self.timestamp(ctx)
        if stamp is None:
            if self.fallback == "original":
                return
            if self.fallback == "error":
                raise FileOperationError(f"no {self.source} timestamp is available for this file")
            text = ""
        else:
            try:
                text = datetime.fromtimestamp(stamp).strftime(self.format)
            except (OverflowError, OSError, ValueError) as exc:
                raise FileOperationError(f"cannot format the file timestamp: {exc}") from exc
        text = sanitize_fragment(text)
        if not text:
            return
        if self.position == "prefix":
            ctx.stem = f"{text}{self.separator}{ctx.stem}"
        else:
            ctx.stem = f"{ctx.stem}{self.separator}{text}"

    def summary(self) -> str:
        where = "before" if self.position == "prefix" else "after"
        source = {"mtime": "modified", "ctime": "created", "atime": "accessed"}[self.source]
        return f"Insert {source} date '{self.format}' {where} the name"


#: Every template variable EzRename understands.
TEMPLATE_VARIABLES = {
    "name": "original file name with extension",
    "stem": "original file name without extension",
    "ext": "extension with the dot ('.jpg')",
    "extname": "extension without the dot ('jpg')",
    "index": "1-based position in the ordered selection",
    "date": "modified date formatted with --date-format",
    "time": "modified time formatted with --time-format",
    "datetime": "modified date and time",
    "size": "file size in bytes",
    "size_kb": "file size in kilobytes",
    "size_mb": "file size in megabytes",
    "parent": "name of the containing folder",
    "prefix": "the prefix set for this session",
    "suffix": "the suffix set for this session",
}


@dataclass
class Template(Operation):
    """Compose a name from a pattern such as ``{stem}_{index:03d}{ext}``."""

    type: ClassVar[str] = "template"
    label: ClassVar[str] = "Template"
    description: ClassVar[str] = "Build names from a pattern with variables like {stem} or {date}"
    category: ClassVar[str] = "Metadata"

    pattern: str = "{stem}{ext}"
    date_format: str = "%Y-%m-%d"
    time_format: str = "%H-%M-%S"
    indexing: bool = False  # when True {index} is 0-based like other operations

    def validate(self) -> None:
        if not self.pattern.strip():
            raise OperationError("template pattern cannot be empty")
        known = set(TEMPLATE_VARIABLES)
        for _literal, field_name, _spec, _conv in Formatter().parse(self.pattern):
            if field_name is None:
                continue
            base = field_name.split(".")[0].split("[")[0]
            if base and base not in known:
                raise OperationError(
                    f"unknown template variable '{{{base}}}' - available: "
                    + ", ".join(sorted(known))
                )
        try:
            self.render_sample()
        except FileOperationError as exc:
            raise OperationError(f"invalid template pattern: {exc}") from exc
        except (KeyError, IndexError, ValueError) as exc:
            raise OperationError(f"invalid template pattern: {exc}") from exc

    def _values(self, ctx: NameContext) -> dict[str, Any]:
        from datetime import datetime

        when = datetime.fromtimestamp(ctx.mtime) if ctx.mtime else datetime.fromtimestamp(0)
        index = ctx.index if self.indexing else ctx.index + 1
        return {
            "name": ctx.original,
            "stem": ctx.original.rsplit(".", 1)[0] if "." in ctx.original else ctx.original,
            "ext": f".{ctx.ext}" if ctx.ext else "",
            "extname": ctx.ext,
            "index": index,
            "date": when.strftime(self.date_format),
            "time": when.strftime(self.time_format),
            "datetime": when.strftime(f"{self.date_format}{self.time_format}"),
            "size": ctx.size,
            "size_kb": round(ctx.size / 1024, 1),
            "size_mb": round(ctx.size / (1024 * 1024), 2),
            "parent": ctx.path.parent.name if ctx.path else "",
            "prefix": ctx.prefix,
            "suffix": ctx.suffix,
        }

    def render(self, ctx: NameContext) -> str:
        try:
            rendered = self.pattern.format(**self._values(ctx))
        except (KeyError, IndexError, ValueError) as exc:
            raise FileOperationError(f"template could not be applied: {exc}") from exc
        return sanitize_fragment(rendered)

    def render_sample(self) -> str:
        sample = NameContext.from_name("example.txt", index=0, size=2048, mtime=1_700_000_000)
        return self.render(sample)

    def apply(self, ctx: NameContext) -> None:
        rendered = self.render(ctx)
        stem, ext = split_name(rendered)
        ctx.stem, ctx.ext = stem, ext

    def summary(self) -> str:
        return f"Template '{self.pattern}'"


@dataclass
class TextEdit(Operation):
    """Insert text at a position, or remove text from the ends/all over."""

    type: ClassVar[str] = "text_edit"
    label: ClassVar[str] = "Insert / remove text"
    description: ClassVar[str] = "Insert text at a fixed position or remove text from the ends"
    category: ClassVar[str] = "Text"

    mode: str = "insert"     # insert | remove
    text: str = ""
    position: str = "start"  # insert: start | end | index ; remove: start | end | anywhere | first | last
    index: int = 0
    case_sensitive: bool = True
    limit: int = 0           # for "first"/"last": how many occurrences

    def validate(self) -> None:
        if self.mode not in ("insert", "remove"):
            raise OperationError(f"unknown text edit mode '{self.mode}'")
        if self.mode == "insert" and self.position not in ("start", "end", "index"):
            raise OperationError(f"unknown insert position '{self.position}'")
        if self.mode == "remove" and self.position not in ("start", "end", "anywhere", "first", "last"):
            raise OperationError(f"unknown remove position '{self.position}'")
        if self.mode == "insert" and not self.text:
            raise OperationError("nothing to insert")
        if self.mode == "remove" and not self.text:
            raise OperationError("nothing to remove")

    def apply(self, ctx: NameContext) -> None:
        if self.mode == "insert":
            if self.position == "start":
                ctx.stem = f"{self.text}{ctx.stem}"
            elif self.position == "end":
                ctx.stem = f"{ctx.stem}{self.text}"
            else:
                index = max(0, min(self.index, len(ctx.stem)))
                ctx.stem = f"{ctx.stem[:index]}{self.text}{ctx.stem[index:]}"
            return

        text = self.text
        stem = ctx.stem
        if self.position == "start":
            if (stem.startswith(text) if self.case_sensitive else stem.casefold().startswith(text.casefold())):
                stem = stem[len(text):]
        elif self.position == "end":
            if (stem.endswith(text) if self.case_sensitive else stem.casefold().endswith(text.casefold())):
                stem = stem[: len(stem) - len(text)]
        elif self.position == "anywhere":
            if self.case_sensitive:
                stem = stem.replace(text, "")
            else:
                stem = re.sub(re.escape(text), "", stem, flags=re.IGNORECASE)
        elif self.position in ("first", "last"):
            limit = max(1, self.limit or 1)
            pattern = re.compile(re.escape(text), 0 if self.case_sensitive else re.IGNORECASE)
            matches = list(pattern.finditer(stem))
            if matches:
                chosen = matches[:limit] if self.position == "first" else matches[-limit:]
                for match in sorted(chosen, key=lambda m: m.start(), reverse=True):
                    stem = stem[: match.start()] + stem[match.end():]
        ctx.stem = stem

    def summary(self) -> str:
        if self.mode == "insert":
            where = {"start": "at the start", "end": "at the end"}.get(self.position, f"at position {self.index}")
            return f"Insert '{self.text}' {where} of the name"
        where = {
            "start": "at the start",
            "end": "at the end",
            "anywhere": "everywhere",
            "first": "from the first occurrence",
            "last": "from the last occurrence",
        }.get(self.position, self.position)
        return f"Remove '{self.text}' {where}"


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #

OPERATION_CLASSES: tuple[type[Operation], ...] = (
    FindReplace,
    PrefixSuffix,
    Numbering,
    CaseConvert,
    Separators,
    ExtensionChange,
    DateInsert,
    Template,
    TextEdit,
)

#: Machine type -> class, used for deserialising plans and presets.
OPERATION_TYPES: dict[str, type[Operation]] = {cls.type: cls for cls in OPERATION_CLASSES}

#: Ordered catalogue used by the GUI tools page and ``ezrename ops``.
OPERATION_CATALOGUE: tuple[type[Operation], ...] = OPERATION_CLASSES

#: The order in which CLI flags are combined into a rename pipeline. Applying
#: operations in a documented, stable order keeps ``--find``+``--case`` style
#: invocations predictable.
CLI_OPERATION_ORDER: tuple[str, ...] = (
    "find_replace",
    "text_edit",
    "separators",
    "case",
    "date",
    "prefix_suffix",
    "template",
    "numbering",
    "extension",
)


def new_operation(type_name: str, **params: Any) -> Operation:
    """Instantiate an operation by machine name."""

    try:
        cls = OPERATION_TYPES[type_name]
    except KeyError:
        raise OperationError(
            f"unknown operation '{type_name}' - known: {', '.join(sorted(OPERATION_TYPES))}"
        ) from None
    valid = {info.name for info in fields(cls)}  # type: ignore[arg-type]
    unknown = set(params) - valid
    if unknown:
        raise OperationError(
            f"unknown option(s) for '{type_name}': {', '.join(sorted(unknown))}"
        )
    return cls(**params)


def operation_from_dict(payload: dict[str, Any]) -> Operation:
    """Rebuild an operation from its serialised form."""

    if not isinstance(payload, dict) or "type" not in payload:
        raise OperationError("operation entries need a 'type' key")
    data = dict(payload)
    type_name = str(data.pop("type"))
    return new_operation(type_name, **data)


def operations_from_dicts(payloads: Iterable[dict[str, Any]]) -> list[Operation]:
    return [operation_from_dict(item) for item in payloads]


def validate_operations(operations: Sequence[Operation]) -> list[str]:
    """Return configuration problems (empty list means "ready to run")."""

    problems: list[str] = []
    for operation in operations:
        try:
            operation.validate()
        except OperationError as exc:
            problems.append(f"{operation.label}: {exc}")
    return problems


def describe_operations(operations: Sequence[Operation], *, numbered: bool = True) -> list[str]:
    """Human readable pipeline description shared by both interfaces."""

    lines: list[str] = []
    for position, operation in enumerate(operations, start=1):
        prefix = f"{position}. " if numbered else ""
        lines.append(f"{prefix}{operation.summary()}")
    return lines


def has_numbering(operations: Sequence[Operation]) -> bool:
    return any(isinstance(operation, Numbering) for operation in operations)


def applies_to_extension(operations: Sequence[Operation]) -> bool:
    return any(
        isinstance(operation, ExtensionChange)
        or (isinstance(operation, FindReplace) and operation.scope in ("ext", "both", "full"))
        or (isinstance(operation, CaseConvert) and operation.scope in ("ext", "both"))
        for operation in operations
    )
