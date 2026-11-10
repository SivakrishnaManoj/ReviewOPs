"""Streaming Amazon Reviews 2023 validation, without model calls or raw-file caching."""

import gzip
import hashlib
import html
import json
import re
import unicodedata
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

SOURCE = "amazon_reviews_2023"
BASE_URL = "https://mcauleylab.ucsd.edu/public_datasets/data/amazon_2023/raw/review_categories"
MIN_TIMESTAMP = datetime(1996, 1, 1, tzinfo=UTC)
MAX_TIMESTAMP = datetime(2023, 10, 1, tzinfo=UTC)
MAX_LINE_BYTES = 2 * 1024 * 1024


class InvalidRecord(ValueError):
    """The message is a fixed reason code, never review content."""


@dataclass(frozen=True)
class Review:
    review_id: str
    product_id: str
    asin: str
    title: str
    body: str
    rating: int
    reviewed_at: datetime
    verified_purchase: bool | None
    content_hash: str

    @property
    def has_text(self):
        return bool(self.title or self.body)


def text_field(value, name, max_length):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise InvalidRecord(f"invalid_{name}")
    value = html.unescape(re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE))
    value = unicodedata.normalize("NFC", value)
    if any(unicodedata.category(c) in {"Cc", "Cs"} and c not in "\t\n\r" for c in value):
        raise InvalidRecord(f"invalid_{name}_characters")
    value = " ".join(value.split())
    if len(value) > max_length:
        raise InvalidRecord(f"oversized_{name}")
    return value


def normalize(raw):
    if not isinstance(raw, dict):
        raise InvalidRecord("not_an_object")
    identifiers = []
    for key in ("parent_asin", "asin"):
        value = raw.get(key)
        if not isinstance(value, str) or not re.fullmatch(r"[A-Z0-9]{10}", value.strip()):
            raise InvalidRecord(f"invalid_{key}")
        identifiers.append(value.strip())
    product_id, asin = identifiers
    user_id = raw.get("user_id")
    if not isinstance(user_id, str) or not user_id.strip() or len(user_id) > 128:
        raise InvalidRecord("invalid_user_id")
    rating = raw.get("rating")
    if (
        isinstance(rating, bool)
        or not isinstance(rating, (int, float))
        or rating not in (1, 2, 3, 4, 5)
    ):
        raise InvalidRecord("invalid_rating")
    # Both names occur in the publisher's examples. Never guess seconds vs milliseconds.
    timestamp = raw.get("timestamp", raw.get("sort_timestamp"))
    if isinstance(timestamp, bool) or not isinstance(timestamp, int):
        raise InvalidRecord("invalid_timestamp")
    if "timestamp" in raw and "sort_timestamp" in raw and raw["sort_timestamp"] != timestamp:
        raise InvalidRecord("conflicting_timestamps")
    if (
        not int(MIN_TIMESTAMP.timestamp() * 1000)
        <= timestamp
        < int(MAX_TIMESTAMP.timestamp() * 1000)
    ):
        raise InvalidRecord("timestamp_outside_dataset")
    reviewed_at = datetime.fromtimestamp(timestamp / 1000, UTC)
    title = text_field(raw.get("title"), "title", 10000)
    body = text_field(raw.get("text"), "text", 200000)
    verified = raw.get("verified_purchase")
    if verified is not None and not isinstance(verified, bool):
        raise InvalidRecord("invalid_verified_purchase")
    # Distinct people can write identical text. No reviewer ID is stored or returned.
    identity = json.dumps([SOURCE, user_id.strip(), asin, timestamp], separators=(",", ":"))
    review_id = "amz23_" + hashlib.sha256(identity.encode()).hexdigest()
    content = json.dumps(
        [product_id, asin, timestamp, int(rating), title, body, verified],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return Review(
        review_id,
        product_id,
        asin,
        title,
        body,
        int(rating),
        reviewed_at,
        verified,
        hashlib.sha256(content.encode()).hexdigest(),
    )


@contextmanager
def open_source(category, input_path=None):
    if not re.fullmatch(r"[A-Za-z][A-Za-z_]{0,79}", category):
        raise ValueError("Invalid category name")
    if input_path is not None:
        path = Path(input_path)
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rb") as stream:
            yield stream
    else:
        request = urllib.request.Request(
            f"{BASE_URL}/{category}.jsonl.gz", headers={"User-Agent": "ReviewOPs/0.1"}
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            with gzip.GzipFile(fileobj=response) as stream:
                yield stream


def records(stream, limit=0):
    """Yield line number, raw-line hash, parsed record and a safe rejection code."""
    if limit < 0:
        raise ValueError("limit must be nonnegative")
    number = 0
    while not limit or number < limit:
        line = stream.readline(MAX_LINE_BYTES + 1)
        if not line:
            return
        number += 1
        digest = hashlib.sha256(line)
        if len(line) > MAX_LINE_BYTES:
            while not line.endswith(b"\n"):
                line = stream.readline(MAX_LINE_BYTES + 1)
                if not line:
                    break
                digest.update(line)
            yield number, digest.hexdigest(), None, "oversized_record"
            continue
        try:
            raw = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            yield number, digest.hexdigest(), None, "invalid_json_or_encoding"
            continue
        yield number, digest.hexdigest(), raw, None
