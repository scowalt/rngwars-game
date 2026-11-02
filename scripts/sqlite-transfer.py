#!/usr/bin/env python3
import argparse
import base64
from contextlib import closing
from datetime import datetime
import hashlib
import hmac
import http.client
import json
import math
import os
from pathlib import Path
import re
import resource
import sqlite3
import ssl
import stat
import struct
import sys
import time
from urllib.parse import urlsplit
import uuid


class TransferError(Exception):
    pass


def require(condition, category):
    if not condition:
        raise TransferError(category)


class PrivateParser(argparse.ArgumentParser):
    def error(self, message):
        raise TransferError("invocation rejected")


def protected_path(value, directory=False):
    path = Path(value)
    require(path.is_absolute(), "path rejected")
    for part in (path, *path.parents):
        require(not part.is_symlink(), "path rejected")
    info = path.lstat()
    require(info.st_uid == os.geteuid() and not info.st_mode & 0o077, "path rejected")
    require(
        stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode),
        "path rejected",
    )
    if not directory:
        require(info.st_nlink == 1, "path rejected")
        protected_path(str(path.parent), True)
    return path


def private_read(value, limit):
    path = protected_path(value)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        content = stream.read(limit + 1)
    require(len(content) <= limit, "input limit exceeded")
    return content


def save(path, content):
    with os.fdopen(
        os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb"
    ) as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "response rejected")
        result[key] = value
    return result


def decode_json(content):
    return json.loads(
        content,
        object_pairs_hook=unique_object,
        parse_constant=lambda value: require(False, "response rejected"),
    )


def hostname(value):
    require(
        isinstance(value, str)
        and re.fullmatch(r"[a-z0-9]+(?:[-.][a-z0-9]+)*\.turso\.io", value) is not None,
        "origin rejected",
    )
    return value


class HTTPS:
    def request(self, method, url, headers, body, limit):
        parsed = urlsplit(url)
        require(
            parsed.scheme == "https"
            and parsed.hostname
            and parsed.netloc == parsed.hostname
            and not parsed.query
            and not parsed.fragment,
            "origin rejected",
        )
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_default_certs()
        connection = http.client.HTTPSConnection(
            parsed.hostname, timeout=60, context=context
        )
        try:
            connection.request(method, parsed.path, body=body, headers=headers)
            response = connection.getresponse()
            data = response.read(limit + 1)
            require(len(data) <= limit, "response limit exceeded")
            headers_out = dict(
                (key.lower(), value) for key, value in response.getheaders()
            )
            if "content-length" in headers_out:
                require(
                    int(headers_out["content-length"]) == len(data), "response rejected"
                )
            return response.status, headers_out, data
        finally:
            connection.close()


class Transport:
    def __init__(self, http, platform_token, database_token):
        self.http = http
        self.platform_token = platform_token
        self.database_token = database_token
        self.deadline = time.monotonic() + 900

    def request(self, method, url, platform=False, body=None, limit=16 * 1024 * 1024):
        require(time.monotonic() < self.deadline, "transfer timed out")
        token = self.platform_token if platform else self.database_token
        headers = {
            "Authorization": "Bearer " + token,
            "Accept-Encoding": "identity",
            "Content-Type": "application/json",
        }
        status, response_headers, data = self.http.request(
            method, url, headers, body, limit
        )
        response_headers = {k.lower(): v for k, v in response_headers.items()}
        require(
            status == 200
            and "location" not in response_headers
            and response_headers.get("content-encoding", "identity") == "identity",
            "HTTP response rejected",
        )
        require(isinstance(data, bytes) and 0 < len(data) <= limit, "response rejected")
        if "content-length" in response_headers:
            require(
                int(response_headers["content-length"]) == len(data),
                "response rejected",
            )
        return data


def token_file(value):
    token = private_read(value, 16384).decode("ascii").strip()
    require(bool(re.fullmatch(r"[A-Za-z0-9_.-]+", token)), "credential rejected")
    return token


def config_file(value):
    config = decode_json(private_read(value, 65536))
    required = {
        "organization",
        "database",
        "database_id",
        "group",
        "primary_name",
        "primary_uuid",
        "primary_hostname",
        "engine",
        "byok",
        "sqlite_version",
        "sqlite_source_id",
        "live_approved",
        "writers_fenced",
        "platform_token_file",
        "database_token_file",
        "output_directory",
    }
    require(
        required <= config.keys() and config.keys() <= required | {"page_size"},
        "configuration rejected",
    )
    require(
        config["live_approved"] is True and config["writers_fenced"] is True,
        "external approval required",
    )
    require(
        config["engine"] == "libsql" and config["byok"] is False,
        "compatibility rejected",
    )
    for name in ("organization", "database", "group", "primary_name"):
        require(
            isinstance(config[name], str)
            and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", config[name]),
            "configuration rejected",
        )
    for name in ("database_id", "primary_uuid"):
        require(str(uuid.UUID(config[name])) == config[name], "configuration rejected")
    require(uuid.UUID(config["database_id"]).bytes[5] != 0x10, "compatibility rejected")
    require(
        isinstance(config["sqlite_version"], str)
        and re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", config["sqlite_version"]),
        "configuration rejected",
    )
    require(
        isinstance(config["sqlite_source_id"], str)
        and re.fullmatch(
            r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [0-9a-f]{60}(?:[0-9a-f]{4}|alt[0-9])(?: alt[0-9]+)?",
            config["sqlite_source_id"],
        ),
        "configuration rejected",
    )
    hostname(config["primary_hostname"])
    page_size = config.get("page_size", 250)
    require(type(page_size) is int and 1 <= page_size <= 1000, "configuration rejected")
    return config


def metadata_value(database, name):
    aliases = {
        "DbId": ("DbId", "dbId"),
        "Schema": ("Schema", "schema"),
        "parent": ("parent", "Parent"),
    }.get(name, (name,))
    present = [database[key] for key in aliases if key in database]
    require(len(present) <= 1, "primary metadata ambiguous")
    return present[0] if present else None


def primary(config, transport):
    url = (
        "https://api.turso.tech/v1/organizations/"
        + config["organization"]
        + "/databases/"
        + config["database"]
    )
    database = decode_json(transport.request("GET", url, platform=True))["database"]
    for actual, expected in (
        ("Name", "database"),
        ("DbId", "database_id"),
        ("group", "group"),
    ):
        require(
            metadata_value(database, actual) == config[expected],
            "primary identity rejected",
        )
    require(
        database.get("database_type") == config["engine"]
        and not database.get("encryption_cipher")
        and not metadata_value(database, "Schema")
        and not database.get("is_schema")
        and not metadata_value(database, "parent")
        and not any(
            database.get(name)
            for name in ("parent_db_id", "parent_name", "parent_branched_at")
        ),
        "compatibility rejected",
    )
    instances = decode_json(transport.request("GET", url + "/instances", platform=True))
    require(
        set(instances) == {"instances"}
        and isinstance(instances["instances"], list)
        and 1 <= len(instances["instances"]) <= 32,
        "primary identity rejected",
    )
    values = instances["instances"]
    identity_fields = {"uuid", "name", "type", "region", "hostname"}
    require(
        all(
            identity_fields <= set(row) <= identity_fields | {"cloud_cluster_name"}
            and row["type"] in ("primary", "replica")
            and (
                "cloud_cluster_name" not in row
                or (
                    isinstance(row["cloud_cluster_name"], str)
                    and re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", row["cloud_cluster_name"])
                )
            )
            for row in values
        ),
        "primary identity rejected",
    )
    require(
        len({row["uuid"] for row in values}) == len(values)
        and len({row["hostname"] for row in values}) == len(values),
        "primary identity rejected",
    )
    selected = [row for row in values if row["type"] == "primary"]
    require(len(selected) == 1, "primary identity rejected")
    instance = selected[0]
    for actual, expected in (
        ("name", "primary_name"),
        ("uuid", "primary_uuid"),
        ("hostname", "primary_hostname"),
    ):
        require(instance[actual] == config[expected], "primary identity rejected")
    hostname(instance["hostname"])
    require(
        instance["region"] == database.get("primaryRegion"), "primary identity rejected"
    )
    return database, sorted(values, key=lambda row: row["uuid"])


def typed(value):
    kind = value["type"]
    if kind == "null":
        require(set(value) == {"type"}, "typed response rejected")
        return None
    if kind == "blob":
        require(set(value) == {"type", "base64"}, "typed response rejected")
        result = base64.b64decode(value["base64"], validate=True)
        require(
            base64.b64encode(result).decode() == value["base64"],
            "typed response rejected",
        )
        return result
    require(set(value) == {"type", "value"}, "typed response rejected")
    content = value["value"]
    if kind == "integer":
        require(
            isinstance(content, str)
            and re.fullmatch(r"0|-?[1-9][0-9]*", content)
            and -(2**63) <= int(content) < 2**63,
            "typed response rejected",
        )
        return int(content)
    if kind == "float":
        require(
            type(content) in (int, float) and math.isfinite(float(content)),
            "typed response rejected",
        )
        return float(content)
    if kind == "text":
        require(isinstance(content, str), "typed response rejected")
        content.encode("utf-8")
        return content
    raise TransferError("typed response rejected")


class RemoteRead:
    def __init__(self, transport, origin):
        self.transport = transport
        self.origin = origin

    def query(self, sql, args=()):
        body = json.dumps(
            {
                "requests": [
                    {
                        "type": "execute",
                        "stmt": {
                            "sql": sql,
                            "args": [
                                {"type": "integer", "value": str(arg)} for arg in args
                            ],
                            "want_rows": True,
                        },
                    },
                    {"type": "close"},
                ]
            }
        ).encode()
        response = decode_json(
            self.transport.request("POST", self.origin + "/v2/pipeline", body=body)
        )
        require(
            response.get("baton") is None and response.get("base_url") is None,
            "routing rejected",
        )
        results = response["results"]
        require(
            len(results) == 2
            and results[0]["type"] == "ok"
            and results[1] == {"type": "ok", "response": {"type": "close"}},
            "query rejected",
        )
        execute = results[0]["response"]
        require(execute["type"] == "execute", "query rejected")
        result = execute["result"]
        require(
            type(result.get("affected_row_count")) is int
            and result["affected_row_count"] == 0
            and result.get("rows_written", 0) == 0,
            "query rejected",
        )
        columns = [col["name"] for col in result["cols"]]
        require(
            len(set(columns)) == len(columns)
            and all(isinstance(col, str) for col in columns),
            "query rejected",
        )
        rows = result["rows"]
        require(
            isinstance(rows, list)
            and len(rows) <= 10000
            and all(isinstance(row, list) and len(row) == len(columns) for row in rows),
            "query rejected",
        )
        return columns, [tuple(typed(v) for v in row) for row in rows]


class LocalRead:
    def __init__(self, conn):
        self.conn = conn

    def query(self, sql, args=()):
        cursor = self.conn.execute(sql, args)
        return [col[0] for col in cursor.description], cursor.fetchall()


def quote(name):
    return '"' + name.replace('"', '""') + '"'


SQL_TOKEN = re.compile(
    r"\s+|--[^\n]*(?:\n|$)|/\*.*?\*/|'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|`(?:``|[^`])*`|\[[^\]]*\]|[A-Za-z_][A-Za-z_0-9]*|[0-9]+(?:\.[0-9]+)?|.",
    re.DOTALL,
)


def sql_tokens(sql):
    tokens = [
        m.group()
        for m in SQL_TOKEN.finditer(sql)
        if not m.group().isspace() and not m.group().startswith(("--", "/*"))
    ]
    if tokens[:5] == ["CREATE", "TABLE", "IF", "NOT", "EXISTS"]:
        tokens[2:5] = []
    if tokens and tokens[-1] == ";":
        tokens.pop()
    return tokens


def schema_rows(reader):
    names, rows = reader.query(
        "SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name"
    )
    require(
        names == ["type", "name", "tbl_name", "sql"] and 1 <= len(rows) <= 32,
        "schema rejected",
    )
    return rows


def expected_gameplay():
    with closing(sqlite3.connect(":memory:")) as conn:
        migrations = Path(__file__).resolve().parents[1] / "apps/api/migrations"
        for name in ("001_initial_schema.sql", "002_add_oauth_fields.sql"):
            conn.executescript((migrations / name).read_text())
        return [
            (kind, name, table, sql_tokens(sql) if sql else None)
            for kind, name, table, sql in schema_rows(LocalRead(conn))
        ]


def canonical(value):
    if value is None:
        tag, data = b"n", b""
    elif type(value) is int:
        tag, data = b"i", str(value).encode()
    elif type(value) is float:
        require(math.isfinite(value), "value compatibility rejected")
        tag, data = b"r", struct.pack(">d", value)
    elif isinstance(value, bytes):
        tag, data = b"b", value
    elif isinstance(value, str):
        tag, data = b"t", value.encode("utf-8")
    elif isinstance(value, (tuple, list)):
        tag, data = b"l", b"".join(canonical(v) for v in value)
    else:
        raise TransferError("typed response rejected")
    return tag + struct.pack(">Q", len(data)) + data


def record_values(row):
    values = []
    for index in range(0, len(row), 2):
        kind, content = row[index : index + 2]
        if kind == "null":
            require(content is None, "value compatibility rejected")
            value = None
        elif kind in ("text", "blob"):
            require(
                isinstance(content, str) and re.fullmatch(r"(?:[0-9A-F]{2})*", content),
                "value compatibility rejected",
            )
            data = bytes.fromhex(content)
            if kind == "text":
                require(b"\x00" not in data, "value compatibility rejected")
                value = data.decode("utf-8")
            else:
                value = data
        elif kind == "integer":
            value = typed({"type": "integer", "value": content})
        elif kind == "real":
            require(isinstance(content, str), "value compatibility rejected")
            value = float(content)
            require(math.isfinite(value), "value compatibility rejected")
        else:
            raise TransferError("value compatibility rejected")
        values.append(value)
    return values


def inventory_rows(reader, sql, expected_names):
    names, rows = reader.query(sql)
    require(names == expected_names, "inventory columns rejected")
    return rows


def collect(reader, key, config):
    version = inventory_rows(
        reader,
        "SELECT sqlite_version() AS engine_version, sqlite_source_id() AS engine_source_id",
        ["engine_version", "engine_source_id"],
    )
    require(
        version == [(config["sqlite_version"], config["sqlite_source_id"])]
        or isinstance(reader, LocalRead),
        "engine version rejected",
    )
    require(
        inventory_rows(reader, "PRAGMA integrity_check", ["integrity_check"])
        == [("ok",)],
        "integrity rejected",
    )
    require(
        inventory_rows(
            reader, "PRAGMA foreign_key_check", ["table", "rowid", "parent", "fkid"]
        )
        == [],
        "foreign keys rejected",
    )
    schema = schema_rows(reader)
    require(
        all(
            kind in ("table", "index") and (sql is None or isinstance(sql, str))
            for kind, name, table, sql in schema
        ),
        "schema compatibility rejected",
    )
    tables = sorted(name for kind, name, table, sql in schema if kind == "table")
    require(
        tables == ["SchemaVersions", "matches", "sqlite_sequence", "users"],
        "schema compatibility rejected",
    )
    normalized = [
        (kind, name, table, sql_tokens(sql) if sql else None)
        for kind, name, table, sql in schema
    ]
    require(
        [row for row in normalized if row[2] in ("users", "matches")]
        == expected_gameplay(),
        "gameplay schema rejected",
    )
    settings = [
        inventory_rows(reader, "PRAGMA " + name, [name])
        for name in ("user_version", "application_id", "encoding")
    ]
    require(
        settings == [[(0,)], [(0,)], [("UTF-8",)]], "settings compatibility rejected"
    )
    inventory, table_digests, journal, sequence = [], [], [], []
    for table in tables:
        quoted = quote(table)
        names, columns = reader.query("PRAGMA table_xinfo(" + quoted + ")")
        require(
            names == ["cid", "name", "type", "notnull", "dflt_value", "pk", "hidden"]
            and 1 <= len(columns) <= 64,
            "columns rejected",
        )
        require(
            all(
                row[0] == index and row[6] == 0 and isinstance(row[1], str)
                for index, row in enumerate(columns)
            ),
            "columns compatibility rejected",
        )
        col_names = [row[1] for row in columns]
        require(
            len(set(col_names)) == len(col_names)
            and all(
                name.lower() not in ("rowid", "_rowid_", "oid") for name in col_names
            ),
            "cursor compatibility rejected",
        )
        if table == "SchemaVersions":
            require(
                [(c[1], c[2], c[3], c[5]) for c in columns]
                == [
                    ("SchemaVersionID", "INTEGER", 1, 1),
                    ("ScriptName", "TEXT", 1, 0),
                    ("Applied", "DATETIME", 1, 0),
                ],
                "journal rejected",
            )
            require(
                any(
                    "AUTOINCREMENT" in (row[3] or "").upper()
                    for row in schema
                    if row[1] == table
                ),
                "journal rejected",
            )
        indexes = inventory_rows(
            reader,
            "PRAGMA index_list(" + quoted + ")",
            ["seq", "name", "unique", "origin", "partial"],
        )
        index_details = [
            (
                row[1],
                inventory_rows(
                    reader,
                    "PRAGMA index_xinfo(" + quote(row[1]) + ")",
                    ["seqno", "cid", "name", "desc", "coll", "key"],
                ),
            )
            for row in indexes
        ]
        foreign_keys = inventory_rows(
            reader,
            "PRAGMA foreign_key_list(" + quoted + ")",
            ["id", "seq", "table", "from", "to", "on_update", "on_delete", "match"],
        )
        inventory.append((table, columns, indexes, index_details, foreign_keys))
        projection = []
        for index, name in enumerate(col_names):
            col = quote(name)
            projection.extend(
                [
                    "typeof(" + col + ") AS " + quote("c" + str(index) + "t"),
                    "CASE typeof("
                    + col
                    + ") WHEN 'null' THEN NULL WHEN 'integer' THEN CAST("
                    + col
                    + " AS TEXT) WHEN 'real' THEN printf('%!.26g',"
                    + col
                    + ") ELSE hex(CAST("
                    + col
                    + " AS BLOB)) END AS "
                    + quote("c" + str(index) + "v"),
                ]
            )
        expected_names = ["scan_cursor"] + [
            f"c{index}{suffix}"
            for index in range(len(col_names))
            for suffix in ("t", "v")
        ]
        count_names, counts = reader.query("SELECT count(*) AS n FROM " + quoted)
        require(
            count_names == ["n"]
            and len(counts) == 1
            and type(counts[0][0]) is int
            and 0 <= counts[0][0] <= 1000000,
            "inventory limit exceeded",
        )
        require(table != "users" or counts[0][0] > 0, "player population rejected")
        total, cursor, digests = 0, None, []
        while True:
            condition = "" if cursor is None else " WHERE rowid > ?"
            args = (
                (config.get("page_size", 250),)
                if cursor is None
                else (cursor, config.get("page_size", 250))
            )
            sql = (
                "SELECT rowid AS scan_cursor,"
                + ",".join(projection)
                + " FROM "
                + quoted
                + condition
                + " ORDER BY rowid LIMIT ?"
            )
            page_names, rows = reader.query(sql, args)
            require(
                page_names == expected_names
                and len(rows) <= config.get("page_size", 250),
                "page rejected",
            )
            if not rows:
                break
            for row in rows:
                require(
                    type(row[0]) is int
                    and (cursor is None or row[0] > cursor)
                    and len(row) == len(expected_names),
                    "cursor rejected",
                )
                cursor = row[0]
                values = record_values(row[1:])
                if table == "SchemaVersions":
                    journal.append(values)
                if table == "sqlite_sequence":
                    sequence.append(values)
                digests.append(hmac.digest(key, canonical(values), "sha256"))
                total += 1
                require(total <= counts[0][0], "page coverage rejected")
        require(total == counts[0][0], "page coverage rejected")
        require(
            inventory_rows(reader, "SELECT count(*) AS n FROM " + quoted, ["n"])
            == counts,
            "page coverage rejected",
        )
        table_digests.append(
            (table, hmac.digest(key, canonical([col_names, sorted(digests)]), "sha256"))
        )
    require(
        len(journal) == 2
        and sorted(row[1] for row in journal)
        == [
            "RNGWars.Api.migrations.001_initial_schema.sql",
            "RNGWars.Api.migrations.002_add_oauth_fields.sql",
        ],
        "journal rejected",
    )
    require(
        all(
            type(row[0]) is int
            and row[0] > 0
            and isinstance(row[2], str)
            and re.fullmatch(
                r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d{1,7})?(?:Z)?", row[2]
            )
            for row in journal
        ),
        "journal rejected",
    )
    for row in journal:
        datetime.fromisoformat(row[2].replace("Z", "+00:00"))
    require(
        len(sequence) == 1
        and sequence[0][0] == "SchemaVersions"
        and type(sequence[0][1]) is int
        and sequence[0][1] >= max(row[0] for row in journal),
        "sequence compatibility rejected",
    )
    return hmac.digest(
        key, canonical([normalized, settings, inventory, table_digests]), "sha256"
    ), table_digests


def statements(dump):
    require(b"\x00" not in dump, "dump rejected")
    sql = dump.decode("utf-8")
    result, start = [], 0
    for index, char in enumerate(sql):
        if char == ";" and sqlite3.complete_statement(sql[start : index + 1]):
            statement = sql[start : index + 1]
            result.append(statement)
            start = index + 1
    require(not sql_tokens(sql[start:]) and len(result) >= 4, "dump rejected")
    tokens = [sql_tokens(statement) for statement in result]
    require(
        tokens[0] == ["PRAGMA", "foreign_keys", "=", "OFF"]
        and tokens[1] == ["BEGIN", "TRANSACTION"]
        and tokens[-1] == ["COMMIT"],
        "dump framing rejected",
    )
    for token in tokens[2:-1]:
        upper = [part.upper() for part in token]
        require(
            upper[:2]
            in (
                ["CREATE", "TABLE"],
                ["CREATE", "INDEX"],
                ["INSERT", "INTO"],
                ["DELETE", "FROM"],
                ["UPDATE", "SQLITE_SEQUENCE"],
            )
            or upper[:3] == ["CREATE", "UNIQUE", "INDEX"],
            "dump SQL rejected",
        )
        require(
            not any(
                part in upper
                for part in (
                    "VIRTUAL",
                    "WITHOUT",
                    "TRIGGER",
                    "VIEW",
                    "ATTACH",
                    "DETACH",
                    "PRAGMA",
                    "SELECT",
                )
            ),
            "dump SQL rejected",
        )
    return result


def import_dump(path, dump):
    commands = statements(dump)
    save(path, b"")
    allowed_tables = {"users", "matches", "SchemaVersions", "sqlite_sequence"}
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("PRAGMA trusted_schema=OFF")
        conn.execute("PRAGMA journal_mode=DELETE")

        def authorizer(action, first, second, database, trigger):
            if action in (
                sqlite3.SQLITE_ATTACH,
                sqlite3.SQLITE_DETACH,
                sqlite3.SQLITE_CREATE_VTABLE,
                sqlite3.SQLITE_CREATE_TRIGGER,
                sqlite3.SQLITE_CREATE_VIEW,
            ):
                return sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_FUNCTION and second not in (
                "strftime",
                "replace",
                "char",
            ):
                return sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_CREATE_TABLE and first not in allowed_tables:
                return sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_PRAGMA and not (
                first == "foreign_keys" and second == "OFF"
            ):
                return sqlite3.SQLITE_DENY
            if action in (
                sqlite3.SQLITE_INSERT,
                sqlite3.SQLITE_UPDATE,
                sqlite3.SQLITE_DELETE,
            ) and first not in allowed_tables | {"sqlite_master"}:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        conn.set_authorizer(authorizer)
        deadline = time.monotonic() + 120
        conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
        for command in commands:
            conn.execute(command)
        conn.set_authorizer(None)
        require(not conn.in_transaction, "import rejected")


def transfer(config, http):
    transport = Transport(
        http,
        token_file(config["platform_token_file"]),
        token_file(config["database_token_file"]),
    )
    output = Path(config["output_directory"])
    require(
        output.is_absolute() and output.name not in ("", ".", ".."), "path rejected"
    )
    protected_path(str(output.parent), True)
    require(not output.exists() and not output.is_symlink(), "output must be fresh")
    os.mkdir(output, 0o700)
    try:
        identity = primary(config, transport)
        key = os.urandom(32)
        save(output / "comparison.key", key)
        origin = "https://" + hostname(config["primary_hostname"])
        remote = RemoteRead(transport, origin)
        before = collect(remote, key, config)
        require(primary(config, transport) == identity, "primary changed")
        dump = transport.request("GET", origin + "/dump", limit=256 * 1024 * 1024)
        save(output / "primary.sql", dump)
        staged = output / "staged.sqlite3"
        import_dump(staged, dump)
        with closing(sqlite3.connect(staged.as_uri() + "?mode=ro", uri=True)) as conn:
            conn.execute("PRAGMA trusted_schema=OFF")
            conn.execute("BEGIN")
            destination = collect(LocalRead(conn), key, config)
        after = collect(remote, key, config)
        require(primary(config, transport) == identity, "primary changed")
        require(before == after == destination, "preservation comparison failed")
        os.link(staged, output / "verified.sqlite3")
        summary = {
            "format": "rngwars-primary-transfer-v1",
            "verified": True,
            "live_identity_and_writer_fence": "operator attested; not established by this tool",
            "tables": [name for name, digest in before[1]],
            "schema_records_settings_hmac": before[0].hex(),
            "source_before_hmac": before[0].hex(),
            "source_after_hmac": after[0].hex(),
            "destination_hmac": destination[0].hex(),
            "algorithm": "framed storage types and sorted row HMAC multiset; HMAC-SHA-256 v1",
            "metadata_passes": 3,
            "source_engine": config["engine"],
            "source_sqlite_version": config["sqlite_version"],
            "source_sqlite_source_id": config["sqlite_source_id"],
            "source_and_destination_equal": True,
            "started_identity_sha256": hashlib.sha256(
                canonical(json.dumps(identity, sort_keys=True))
            ).hexdigest(),
        }
        save(
            output / "summary.json",
            json.dumps(summary, sort_keys=True).encode() + b"\n",
        )
    except Exception:
        save(
            output / "failure.txt",
            b"Transfer rejected; artifacts are not an approved baseline. Artifact contents must remain private.\n",
        )
        raise


def main(argv=None, http=None):
    os.umask(0o077)
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        parser = PrivateParser(
            description="Private read-only primary transfer; separate live approval and writer fencing required."
        )
        parser.add_argument("command", choices=["transfer"])
        parser.add_argument("config_file")
        args = parser.parse_args(argv)
        transfer(config_file(args.config_file), http if http is not None else HTTPS())
        print("transfer verified")
        return 0
    except TransferError as error:
        print("transfer failed: " + str(error), file=sys.stderr)
        return 1
    except Exception:
        print("transfer failed: private operation rejected", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
