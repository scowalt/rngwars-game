import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import ssl
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/sqlite-transfer.py"
JOURNAL = "CREATE TABLE SchemaVersions (SchemaVersionID INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, ScriptName TEXT NOT NULL, Applied DATETIME NOT NULL);"
SCHEMA = (
    "\n".join(
        (ROOT / "apps/api/migrations" / name).read_text()
        for name in ("001_initial_schema.sql", "002_add_oauth_fields.sql")
    )
    + JOURNAL
)
RECORDS = """
INSERT INTO users (rowid,id,username,anonymous_id,rng_score,total_wins,total_losses,total_matches,created_at,last_seen_at,auth_provider,auth_id,email,display_name,avatar_url,is_anonymous,linked_at)
VALUES (-7,'11111111-1111-4111-8111-111111111111','quote'' / 雪','33333333-3333-4333-8333-333333333333',1432,12,9,21,'2020-01-02T03:04:05.1234567Z','2021-02-03T04:05:06Z',NULL,NULL,'a@example.invalid',CAST(X'00FF' AS BLOB),'https://example.invalid/avatar',1,NULL);
INSERT INTO matches (id,player1_id,player2_id,winner_id,status,is_practice,ai_name,player1_roll,player2_roll,player1_elo_before,player2_elo_before,player1_elo_after,player2_elo_after,started_at,completed_at,created_at)
VALUES ('22222222-2222-4222-8222-222222222222','11111111-1111-4111-8111-111111111111',NULL,'11111111-1111-4111-8111-111111111111','completed',1,'Synthetic AI',0.10000000000000002,4.0,1432,NULL,1432,NULL,'2020-02-03T04:05:06.1234567Z','2020-02-03T04:05:07Z','2020-02-03T04:05:06Z');
INSERT INTO SchemaVersions VALUES (3,'RNGWars.Api.migrations.001_initial_schema.sql','2020-01-01 02:03:04.1234567');
INSERT INTO SchemaVersions VALUES (8,'RNGWars.Api.migrations.002_add_oauth_fields.sql','2020-01-01 02:03:04.9876543');
UPDATE sqlite_sequence SET seq=40 WHERE name='SchemaVersions';
"""
DUMP_SCHEMA = (
    (ROOT / "apps/api/migrations/001_initial_schema.sql")
    .read_text()
    .replace(
        "\n);",
        ", auth_provider TEXT, auth_id TEXT, email TEXT, display_name TEXT, avatar_url TEXT, is_anonymous INTEGER NOT NULL DEFAULT 1, linked_at TEXT\n);",
        1,
    )
    + "CREATE UNIQUE INDEX idx_users_auth ON users(auth_provider, auth_id) WHERE auth_provider IS NOT NULL;"
    + JOURNAL
)
DUMP = (
    "PRAGMA foreign_keys=OFF;\nBEGIN TRANSACTION;\n"
    + DUMP_SCHEMA
    + RECORDS.replace("(rowid,id,", "(id,").replace(
        "VALUES (-7,'11111111-1111-4111-8111-111111111111'",
        "VALUES ('11111111-1111-4111-8111-111111111111'",
    )
    + "\nCOMMIT;\n"
)


def wire(value):
    if value is None:
        return {"type": "null"}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if isinstance(value, bytes):
        import base64

        return {"type": "blob", "base64": base64.b64encode(value).decode()}
    return {"type": "text", "value": value}


class SyntheticHTTP:
    def __init__(self):
        self.source = sqlite3.connect(":memory:")
        self.source.executescript(SCHEMA + RECORDS)
        self.dump = DUMP.encode()
        self.database = {
            "Name": "synthetic-db",
            "DbId": "01234567-8900-4000-8000-012345678901",
            "group": "synthetic-group",
            "primaryRegion": "synthetic-region",
            "database_type": "libsql",
            "encryption_cipher": "",
        }
        self.instances = [
            {
                "uuid": "01234567-8900-4000-8000-012345678902",
                "name": "synthetic-primary",
                "type": "primary",
                "region": "synthetic-region",
                "hostname": "synthetic-primary.turso.io",
                "cloud_cluster_name": "synthetic-cluster",
            }
        ]
        self.calls = []
        self.on_dump = lambda: None
        self.transform = lambda path, data: data
        self.status = 200
        self.headers = {}
        self.dump_status = None
        self.dump_headers = None
        self.raw_transform = lambda path, data: data

    def request(self, method, url, headers, body, limit):
        path = urlsplit(url).path
        self.calls.append((method, url, body))
        if path.endswith("/instances"):
            data = {"instances": self.instances}
        elif path.startswith("/v1/"):
            data = {"database": self.database}
        elif path == "/dump":
            self.on_dump()
            return (
                self.status if self.dump_status is None else self.dump_status,
                self.headers if self.dump_headers is None else self.dump_headers,
                self.dump,
            )
        else:
            stmt = json.loads(body)["requests"][0]["stmt"]
            args = [int(item["value"]) for item in stmt["args"]]
            cursor = self.source.execute(stmt["sql"], args)
            result = {
                "cols": [{"name": col[0]} for col in cursor.description],
                "rows": [[wire(v) for v in row] for row in cursor.fetchall()],
                "affected_row_count": 0,
                "last_insert_rowid": None,
            }
            data = {
                "baton": None,
                "base_url": None,
                "results": [
                    {"type": "ok", "response": {"type": "execute", "result": result}},
                    {"type": "ok", "response": {"type": "close"}},
                ],
            }
        data = self.transform(path, data)
        return (
            self.status,
            self.headers,
            self.raw_transform(path, json.dumps(data).encode()),
        )


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.private = Path(self.temp.name)
        self.private.chmod(0o700)
        self.http = SyntheticHTTP()
        self.addCleanup(self.http.source.close)
        self.config = {
            "organization": "synthetic-org",
            "database": "synthetic-db",
            "database_id": self.http.database["DbId"],
            "group": "synthetic-group",
            "primary_name": "synthetic-primary",
            "primary_uuid": self.http.instances[0]["uuid"],
            "primary_hostname": "synthetic-primary.turso.io",
            "engine": "libsql",
            "byok": False,
            "sqlite_version": sqlite3.sqlite_version,
            "sqlite_source_id": self.http.source.execute(
                "SELECT sqlite_source_id()"
            ).fetchone()[0],
            "live_approved": True,
            "writers_fenced": True,
            "platform_token_file": str(self.private / "platform.token"),
            "database_token_file": str(self.private / "database.token"),
            "output_directory": str(self.private / "result"),
            "page_size": 1,
        }
        for name in ("platform.token", "database.token"):
            self.save(name, "SYNTHETIC-PRIVATE-CREDENTIAL")
        self.save("config.json", json.dumps(self.config))

    def save(self, name, value):
        path = self.private / name
        path.write_text(value)
        path.chmod(0o600)
        return path

    def run_transfer(self, argv=None, network_adapter=False):
        spec = importlib.util.spec_from_file_location("sqlite_transfer", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.save("config.json", json.dumps(self.config))
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = module.main(
                argv or ["transfer", str(self.private / "config.json")],
                http=None if network_adapter else self.http,
            )
        return code, stdout.getvalue(), stderr.getvalue()

    def test_current_libsql_metadata_without_deprecated_version_preserves_data(self):
        self.http.database.pop("Version", None)
        self.http.database.update(
            database_type="libsql", server_type="turso-server", schema=None,
            parent=None, parent_db_id="", parent_name="", parent_branched_at=None,
        )
        self.config.pop("metadata_version", None)
        self.config["sqlite_source_id"] = self.http.source.execute(
            "SELECT sqlite_source_id()"
        ).fetchone()[0]
        code, stdout, stderr = self.run_transfer()
        self.assertEqual((code, stdout, stderr), (0, "transfer verified\n", ""))

    def test_current_instance_cluster_metadata_preserves_pinned_transfer(self):
        self.http.instances[0]["cloud_cluster_name"] = "synthetic-cluster-1"
        code, stdout, stderr = self.run_transfer()
        self.assertEqual((code, stdout, stderr), (0, "transfer verified\n", ""))

    def test_instance_cluster_identifier_boundary_is_supported(self):
        self.http.instances[0]["cloud_cluster_name"] = "x" * 128
        code, stdout, stderr = self.run_transfer()
        self.assertEqual((code, stdout, stderr), (0, "transfer verified\n", ""))

    def test_instance_cluster_metadata_cannot_be_boolean(self):
        self.http.instances[0]["cloud_cluster_name"] = True
        self.assert_rejected()
        self.assertFalse(any(url.endswith("/v2/pipeline") for _, url, _ in self.http.calls))

    def test_instance_cluster_metadata_must_be_bounded(self):
        self.http.instances[0]["cloud_cluster_name"] = "x" * 129
        self.assert_rejected()
        self.assertFalse(any(url.endswith("/v2/pipeline") for _, url, _ in self.http.calls))

    def test_legacy_instance_without_cluster_metadata_still_preserves_transfer(self):
        self.http.instances[0].pop("cloud_cluster_name")
        code, stdout, stderr = self.run_transfer()
        self.assertEqual((code, stdout, stderr), (0, "transfer verified\n", ""))

    def test_instance_cluster_metadata_rejects_invalid_identifiers_and_types(self):
        for index, value in enumerate((None, 1, {}, [], "", "line\nbreak", "cluster/host", "雪")):
            with self.subTest(value=value):
                output = self.private / ("invalid-cluster-" + str(index))
                self.config["output_directory"] = str(output)
                self.http.instances[0]["cloud_cluster_name"] = value
                code, stdout, stderr = self.run_transfer()
                self.assertEqual((code, stdout, stderr), (1, "", "transfer failed: primary identity rejected\n"))
                self.assertFalse((output / "verified.sqlite3").exists())

    def test_known_cluster_metadata_does_not_allow_unknown_instance_fields(self):
        self.http.instances[0]["unknown_cluster_metadata"] = "synthetic-cluster"
        self.assert_rejected()

    def test_cluster_metadata_cannot_replace_pinned_primary_identity(self):
        original = self.http.instances[0].copy()
        for field, value in (
            ("uuid", "01234567-8900-4000-8000-012345678999"),
            ("name", "another-primary"),
            ("hostname", "another-primary.turso.io"),
            ("region", "another-region"),
            ("type", "replica"),
        ):
            with self.subTest(field=field):
                output = self.private / ("wrong-primary-" + field)
                self.config["output_directory"] = str(output)
                self.http.instances[0] = original | {field: value}
                code, stdout, stderr = self.run_transfer()
                self.assertEqual((code, stdout, stderr), (1, "", "transfer failed: primary identity rejected\n"))
                self.assertFalse((output / "verified.sqlite3").exists())

    def test_duplicate_primaries_sharing_cluster_metadata_are_not_selected(self):
        self.http.instances.append(self.http.instances[0] | {
            "uuid": "01234567-8900-4000-8000-012345678999",
            "name": "another-primary", "hostname": "another-primary.turso.io",
        })
        self.assert_rejected()

    def test_replica_cluster_metadata_does_not_redirect_primary_transfer(self):
        self.http.instances.append(self.http.instances[0] | {
            "uuid": "01234567-8900-4000-8000-012345678999", "type": "replica",
            "name": "synthetic-replica", "hostname": "synthetic-replica.turso.io",
            "region": "synthetic-secondary", "cloud_cluster_name": "another-cluster",
        })
        code, stdout, stderr = self.run_transfer()
        self.assertEqual((code, stdout, stderr), (0, "transfer verified\n", ""))
        self.assertFalse(any("synthetic-replica.turso.io" in url for _, url, _ in self.http.calls))

    def test_cluster_metadata_drift_during_dump_blocks_promotion(self):
        self.http.on_dump = lambda: self.http.instances[0].update(cloud_cluster_name="another-cluster")
        self.assert_rejected()

    def test_cluster_metadata_removal_during_dump_blocks_promotion(self):
        self.http.on_dump = lambda: self.http.instances[0].pop("cloud_cluster_name")
        self.assert_rejected()

    def test_cluster_metadata_addition_during_dump_blocks_promotion(self):
        self.http.instances[0].pop("cloud_cluster_name")
        self.http.on_dump = lambda: self.http.instances[0].update(cloud_cluster_name="synthetic-cluster")
        self.assert_rejected()

    def test_supported_complete_transfer_preserves_named_values_not_hidden_rowids(self):
        code, stdout, stderr = self.run_transfer()
        self.assertEqual((code, stdout, stderr), (0, "transfer verified\n", ""))
        output = self.private / "result"
        self.assertEqual((output.stat().st_mode & 0o777), 0o700)
        self.assertEqual(((output / "verified.sqlite3").stat().st_mode & 0o777), 0o600)
        summary = json.loads((output / "summary.json").read_text())
        self.assertTrue(summary["verified"])
        self.assertEqual(
            summary["tables"], ["SchemaVersions", "matches", "sqlite_sequence", "users"]
        )
        with contextlib.closing(
            sqlite3.connect(
                (output / "verified.sqlite3").as_uri() + "?mode=ro", uri=True
            )
        ) as artifact:
            self.assertTrue(
                artifact.execute("SELECT * FROM users").fetchall()
                == [
                    (
                        "11111111-1111-4111-8111-111111111111",
                        "quote' / 雪",
                        "33333333-3333-4333-8333-333333333333",
                        1432,
                        12,
                        9,
                        21,
                        "2020-01-02T03:04:05.1234567Z",
                        "2021-02-03T04:05:06Z",
                        None,
                        None,
                        "a@example.invalid",
                        b"\x00\xff",
                        "https://example.invalid/avatar",
                        1,
                        None,
                    )
                ]
            )
            self.assertTrue(
                artifact.execute("SELECT * FROM matches").fetchall()
                == [
                    (
                        "22222222-2222-4222-8222-222222222222",
                        "11111111-1111-4111-8111-111111111111",
                        None,
                        "11111111-1111-4111-8111-111111111111",
                        "completed",
                        1,
                        "Synthetic AI",
                        0.10000000000000002,
                        4.0,
                        1432,
                        None,
                        1432,
                        None,
                        "2020-02-03T04:05:06.1234567Z",
                        "2020-02-03T04:05:07Z",
                        "2020-02-03T04:05:06Z",
                    )
                ]
            )
            self.assertTrue(
                artifact.execute(
                    "SELECT * FROM SchemaVersions ORDER BY SchemaVersionID"
                ).fetchall()
                == [
                    (
                        3,
                        "RNGWars.Api.migrations.001_initial_schema.sql",
                        "2020-01-01 02:03:04.1234567",
                    ),
                    (
                        8,
                        "RNGWars.Api.migrations.002_add_oauth_fields.sql",
                        "2020-01-01 02:03:04.9876543",
                    ),
                ]
            )
            self.assertTrue(
                artifact.execute("SELECT * FROM sqlite_sequence").fetchall()
                == [("SchemaVersions", 40)]
            )
            self.assertTrue(
                artifact.execute("SELECT rowid FROM users").fetchall() == [(1,)]
            )
        self.assertNotIn(
            "33333333-3333-4333-8333-333333333333",
            (output / "summary.json").read_text(),
        )
        self.assertTrue(
            all(
                url.startswith(
                    ("https://api.turso.tech/", "https://synthetic-primary.turso.io/")
                )
                for _, url, _ in self.http.calls
            )
        )
        self.assertTrue(
            all(method in ("GET", "POST") for method, _, _ in self.http.calls)
        )

    def assert_rejected(self, argv=None):
        code, stdout, stderr = self.run_transfer(argv)
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertTrue(stderr.startswith("transfer failed: "))
        for secret in (
            "PRIVATE-TOKEN-A",
            "33333333-3333-4333-8333-333333333333",
            "SYNTHETIC-PRIVATE-CREDENTIAL",
            "a@example.invalid",
            "https://",
            str(self.private),
        ):
            self.assertNotIn(secret, stderr)
        self.assertFalse((self.private / "result/verified.sqlite3").exists())
        self.assertFalse((self.private / "result/summary.json").exists())

    def test_invalid_historical_journal_date_is_not_a_valid_baseline(self):
        self.http.source.execute(
            "UPDATE SchemaVersions SET Applied='2020-99-99 99:99:99' WHERE SchemaVersionID=3"
        )
        self.http.dump = self.http.dump.replace(
            b"2020-01-01 02:03:04.1234567", b"2020-99-99 99:99:99"
        )
        self.assert_rejected()

    def test_equal_count_record_mutation_blocks_import(self):
        self.http.dump = self.http.dump.replace(
            b"33333333-3333-4333-8333-333333333333",
            b"44444444-4444-4444-8444-444444444444",
        )
        self.assert_rejected()

    def test_named_blob_field_bytes_matter(self):
        self.http.dump = self.http.dump.replace(b"CAST(X'00FF' AS BLOB)", b"X'00FE'")
        self.assert_rejected()

    def test_historical_timestamp_precision_is_not_normalized(self):
        self.http.dump = self.http.dump.replace(
            b"2020-01-01 02:03:04.1234567", b"2020-01-01 02:03:04.1234560"
        )
        self.assert_rejected()

    def test_sequence_above_surviving_journal_ids_must_survive(self):
        self.http.dump = self.http.dump.replace(b"SET seq=40", b"SET seq=8")
        self.assert_rejected()

    def test_source_update_between_observations_blocks_an_equal_count_dump(self):
        self.http.on_dump = lambda: self.http.source.execute(
            "UPDATE users SET rng_score=1500"
        )
        self.assert_rejected()

    def test_column_drift_blocks_even_a_self_consistent_dump(self):
        self.http.source.execute("ALTER TABLE users ADD COLUMN extra TEXT")
        self.assert_rejected()

    def test_index_drift_blocks_import(self):
        self.http.dump = self.http.dump.replace(
            b"CREATE INDEX idx_matches_player2 ON matches(player2_id);", b""
        )
        self.assert_rejected()

    def test_hidden_parent_database_id_blocks_current_metadata(self):
        self.http.database.update(parent=None, parent_db_id="synthetic-parent")
        self.assert_rejected()
        self.assertFalse(any(url.endswith("/dump") for _, url, _ in self.http.calls))

    def test_primary_failover_during_dump_blocks_transfer(self):
        self.http.on_dump = lambda: self.http.instances[0].update(
            hostname="changed-primary.turso.io"
        )
        self.assert_rejected()

    def test_ambiguous_primary_blocks_before_data_access(self):
        self.http.instances.append(
            dict(
                self.http.instances[0],
                uuid="01234567-8900-4000-8000-012345678903",
                hostname="other-primary.turso.io",
            )
        )
        self.assert_rejected()
        self.assertFalse(
            any(
                url.endswith(("/dump", "/v2/pipeline")) for _, url, _ in self.http.calls
            )
        )

    def test_http_errors_and_redirects_are_not_sql_dump_success(self):
        self.http.status = 403
        self.http.dump = b"PRIVATE-TOKEN-A error with https://secret.invalid/?token=SYNTHETIC-PRIVATE-CREDENTIAL"
        self.assert_rejected()

    def test_redirect_header_is_rejected_even_with_http_200(self):
        self.http.headers = {
            "Location": "https://secret.invalid/?token=SYNTHETIC-PRIVATE-CREDENTIAL"
        }
        self.assert_rejected()

    def test_hrana_routing_cannot_retarget_the_primary(self):
        self.http.transform = (
            lambda path, data: dict(
                data,
                base_url="https://secret.invalid/?token=SYNTHETIC-PRIVATE-CREDENTIAL",
            )
            if path == "/v2/pipeline"
            else data
        )
        self.assert_rejected()

    def test_http_200_with_query_error_never_counts_as_records(self):
        def transform(path, data):
            if path == "/v2/pipeline":
                data["results"][0] = {
                    "type": "error",
                    "error": {"message": "PRIVATE-TOKEN-A"},
                }
            return data

        self.http.transform = transform
        self.assert_rejected()

    def test_missing_response_rows_rejected_privately(self):
        def transform(path, data):
            if path == "/v2/pipeline":
                del data["results"][0]["response"]["result"]["rows"]
            return data

        self.http.transform = transform
        self.assert_rejected()

    def test_truncated_page_does_not_become_a_complete_empty_table(self):
        def transform(path, data):
            if path == "/v2/pipeline":
                result = data["results"][0]["response"]["result"]
                if result["cols"][0]["name"] == "scan_cursor":
                    result["rows"] = []
            return data

        self.http.transform = transform
        self.assert_rejected()

    def test_truncated_dump_is_rejected_not_promoted(self):
        self.http.dump = self.http.dump[:-10]
        self.assert_rejected()

    def test_missing_dump_record_detected_by_complete_evidence(self):
        self.http.dump = self.http.dump.replace(
            RECORDS[
                RECORDS.index("INSERT INTO matches") : RECORDS.index(
                    "INSERT INTO SchemaVersions"
                )
            ].encode(),
            b"",
        )
        self.assert_rejected()

    def test_dump_dot_command_and_source_write_payload_are_rejected(self):
        self.http.dump = self.http.dump.replace(
            b"COMMIT;", b".shell echo PRIVATE-TOKEN-A;\nCOMMIT;"
        )
        self.assert_rejected()

    def test_nul_text_is_a_compatibility_stop_not_a_truncated_value(self):
        self.http.source.execute(
            "UPDATE users SET username=?", ("prefix\x00PRIVATE-TOKEN-A",)
        )
        self.assert_rejected()

    def test_nonfinite_real_is_an_explicit_compatibility_stop(self):
        self.http.source.execute("UPDATE matches SET player1_roll=?", (float("inf"),))
        self.assert_rejected()

    def test_unsupported_source_table_is_not_silently_omitted(self):
        self.http.source.execute("CREATE TABLE unreviewed (value TEXT)")
        self.assert_rejected()

    def test_source_header_settings_are_not_silently_lost(self):
        self.http.source.execute("PRAGMA user_version=42")
        self.assert_rejected()

    def test_broken_foreign_key_is_not_a_supported_baseline(self):
        self.http.source.execute("UPDATE matches SET player1_id='missing-player'")
        self.assert_rejected()

    def test_byok_and_unapproved_live_inputs_block_before_http(self):
        self.config["byok"] = True
        self.assert_rejected()
        self.assertEqual(self.http.calls, [])

    def test_engine_metadata_must_match_approved_configuration(self):
        self.http.database["database_type"] = "turso"
        self.assert_rejected()

    def test_missing_affirmative_engine_metadata_blocks_before_sql(self):
        self.http.database.pop("database_type")
        self.assert_rejected()
        self.assertFalse(any(url.endswith("/v2/pipeline") for _, url, _ in self.http.calls))

    def test_libsql_source_id_with_modified_build_suffix_is_pinned_verbatim(self):
        source_id = "2024-10-21 16:30:22 " + "a" * 60 + "alt1"
        self.http.source.create_function("sqlite_source_id", 0, lambda: source_id)
        self.config["sqlite_source_id"] = source_id
        code, stdout, stderr = self.run_transfer()
        self.assertEqual((code, stdout, stderr), (0, "transfer verified\n", ""))
        summary = json.loads((self.private / "result/summary.json").read_text())
        self.assertEqual(summary["source_sqlite_source_id"], source_id)

    def test_sqlite_source_id_mismatch_blocks_before_dump(self):
        self.config["sqlite_source_id"] = "2020-01-01 00:00:00 " + "0" * 64
        self.assert_rejected()
        self.assertFalse(any(url.endswith("/dump") for _, url, _ in self.http.calls))

    def test_sqlite_version_mismatch_blocks_before_dump(self):
        self.config["sqlite_version"] = "0.0.0"
        self.assert_rejected()
        self.assertFalse(any(url.endswith("/dump") for _, url, _ in self.http.calls))

    def test_sqlite_source_id_drift_during_dump_blocks_promotion(self):
        self.http.on_dump = lambda: self.http.source.create_function(
            "sqlite_source_id", 0, lambda: "2020-01-01 00:00:00 " + "0" * 64
        )
        self.assert_rejected()

    def test_source_identity_columns_cannot_be_omitted(self):
        def transform(path, data):
            if path == "/v2/pipeline":
                result = data["results"][0]["response"]["result"]
                if result["cols"][0]["name"] == "engine_version":
                    result["cols"].pop()
                    result["rows"][0].pop()
            return data

        self.http.transform = transform
        self.assert_rejected()

    def test_malformed_source_id_blocks_before_http(self):
        self.config["sqlite_source_id"] = "PRIVATE-TOKEN-A\nforged source"
        self.assert_rejected()
        self.assertEqual(self.http.calls, [])

    def test_legacy_build_version_cannot_replace_source_id(self):
        self.config.pop("sqlite_source_id")
        self.config["metadata_version"] = "synthetic-libsql"
        self.assert_rejected()
        self.assertEqual(self.http.calls, [])

    def test_verified_summary_records_observed_source_identity(self):
        code, stdout, stderr = self.run_transfer()
        self.assertEqual((code, stdout, stderr), (0, "transfer verified\n", ""))
        summary = json.loads((self.private / "result/summary.json").read_text())
        self.assertEqual(summary["source_engine"], "libsql")
        self.assertEqual(summary["source_sqlite_version"], self.config["sqlite_version"])
        self.assertEqual(summary["source_sqlite_source_id"], self.config["sqlite_source_id"])

    def test_nonempty_parent_name_blocks_current_metadata(self):
        self.http.database.update(parent=None, parent_name="synthetic-parent")
        self.assert_rejected()

    def test_nonempty_parent_timestamp_blocks_current_metadata(self):
        self.http.database.update(parent=None, parent_branched_at="2020-01-01T00:00:00Z")
        self.assert_rejected()

    def test_source_engine_change_during_dump_blocks_promotion(self):
        self.http.on_dump = lambda: self.http.database.update(database_type="turso")
        self.assert_rejected()

    def test_credential_bearing_origin_is_never_sent_or_echoed(self):
        self.config["primary_hostname"] = (
            "https://SYNTHETIC-PRIVATE-CREDENTIAL@secret.invalid/?token=PRIVATE-TOKEN-A"
        )
        self.assert_rejected()
        self.assertEqual(self.http.calls, [])

    def test_credential_header_injection_is_rejected_without_http(self):
        self.save(
            "database.token", "SYNTHETIC-PRIVATE-CREDENTIAL\nX-Secret: PRIVATE-TOKEN-A"
        )
        self.assert_rejected()
        self.assertEqual(self.http.calls, [])

    def test_insecure_credentials_are_rejected_before_access(self):
        (self.private / "database.token").chmod(0o644)
        self.assert_rejected()
        self.assertEqual(self.http.calls, [])

    def test_symlink_ancestor_cannot_redirect_credential_access(self):
        alias = self.private / "alias"
        alias.symlink_to(self.private, target_is_directory=True)
        self.config["database_token_file"] = str(alias / "database.token")
        self.assert_rejected()

    def test_existing_output_is_not_modified(self):
        output = self.private / "result"
        output.mkdir(mode=0o700)
        (output / "sentinel").write_text("retained")
        self.assert_rejected()
        self.assertEqual((output / "sentinel").read_text(), "retained")
        self.assertEqual(self.http.calls, [])

    def test_missing_output_parent_is_not_created(self):
        self.config["output_directory"] = str(self.private / "missing/result")
        self.assert_rejected()
        self.assertFalse((self.private / "missing").exists())

    def test_argument_errors_do_not_echo_private_strings(self):
        self.assert_rejected(
            [
                "PRIVATE-TOKEN-A",
                "https://secret.invalid/?token=SYNTHETIC-PRIVATE-CREDENTIAL",
            ]
        )

    def test_empty_player_population_cannot_be_promoted_for_production(self):
        self.http.source.execute("DELETE FROM matches")
        self.http.source.execute("DELETE FROM users")
        self.http.dump = (
            "PRAGMA foreign_keys=OFF;\nBEGIN TRANSACTION;\n"
            + DUMP_SCHEMA
            + RECORDS[RECORDS.index("INSERT INTO SchemaVersions") :]
            + "\nCOMMIT;\n"
        ).encode()
        self.assert_rejected()

    def test_unknown_inventory_response_columns_are_rejected(self):
        def transform(path, data):
            if path == "/v2/pipeline":
                columns = data["results"][0]["response"]["result"]["cols"]
                if [col["name"] for col in columns] == [
                    "seq",
                    "name",
                    "unique",
                    "origin",
                    "partial",
                ]:
                    columns[0]["name"] = "unrecognized"
            return data

        self.http.transform = transform
        self.assert_rejected()

    def test_pinned_client_metadata_casing_is_supported_without_ambiguity(self):
        self.http.database["dbId"] = self.http.database.pop("DbId")
        code, stdout, stderr = self.run_transfer()
        self.assertEqual((code, stdout, stderr), (0, "transfer verified\n", ""))

    def test_verified_tls_adapter_uses_exact_https_origins_and_checks_lengths(self):
        fixture = self.http
        test = self

        class Connection:
            def __init__(self, host, timeout, context):
                test.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
                test.assertTrue(context.check_hostname)
                self.host = host

            def request(self, method, path, body, headers):
                test.assertNotIn("SYNTHETIC-PRIVATE-CREDENTIAL", path)
                self.status, self.headers, self.data = fixture.request(
                    method,
                    "https://" + self.host + path,
                    headers,
                    body,
                    256 * 1024 * 1024,
                )

            def getresponse(self):
                return self

            def getheaders(self):
                return [("Content-Length", str(len(self.data)))]

            def read(self, limit):
                return self.data[:limit]

            def close(self):
                pass

        with patch("http.client.HTTPSConnection", Connection):
            code, stdout, stderr = self.run_transfer(network_adapter=True)
        self.assertEqual((code, stdout, stderr), (0, "transfer verified\n", ""))

    def test_certificate_and_network_errors_are_private_failures(self):
        with patch(
            "http.client.HTTPSConnection",
            side_effect=ssl.SSLCertVerificationError(
                "PRIVATE-TOKEN-A https://secret.invalid/?token=SYNTHETIC-PRIVATE-CREDENTIAL"
            ),
        ):
            code, stdout, stderr = self.run_transfer(network_adapter=True)
        self.assertEqual(
            (code, stdout, stderr),
            (1, "", "transfer failed: private operation rejected\n"),
        )
        self.assertFalse((self.private / "result/verified.sqlite3").exists())

    def test_advertised_length_mismatch_cannot_hide_truncation(self):
        self.http.headers = {"Content-Length": "1"}
        self.assert_rejected()

    def test_missing_query_column_value_is_not_defaulted(self):
        def transform(path, data):
            if path == "/v2/pipeline":
                result = data["results"][0]["response"]["result"]
                if result["rows"]:
                    result["rows"][0].pop()
            return data

        self.http.transform = transform
        self.assert_rejected()

    def test_unknown_hrana_type_is_not_stringified(self):
        def transform(path, data):
            if path == "/v2/pipeline":
                result = data["results"][0]["response"]["result"]
                if result["rows"]:
                    result["rows"][0][0] = {
                        "type": "unknown",
                        "value": "PRIVATE-TOKEN-A",
                    }
            return data

        self.http.transform = transform
        self.assert_rejected()

    def test_projection_float_precision_cannot_be_rounded(self):
        self.http.dump = self.http.dump.replace(b"0.10000000000000002", b"0.1")
        self.assert_rejected()

    def test_failure_artifacts_are_private_and_not_raw_diagnostics(self):
        self.http.dump = b"PRIVATE-TOKEN-A https://secret.invalid/?token=SYNTHETIC-PRIVATE-CREDENTIAL"
        self.assert_rejected()
        output = self.private / "result"
        self.assertTrue((output / "failure.txt").exists())
        self.assertNotIn("PRIVATE-TOKEN-A", (output / "failure.txt").read_text())
        self.assertTrue(
            all((path.stat().st_mode & 0o777) == 0o600 for path in output.iterdir())
        )

    def test_unfenced_writer_attestation_blocks_all_http(self):
        self.config["writers_fenced"] = False
        self.assert_rejected()
        self.assertEqual(self.http.calls, [])

    def test_absent_live_approval_blocks_all_http(self):
        self.config["live_approved"] = False
        self.assert_rejected()
        self.assertEqual(self.http.calls, [])

    def test_missing_credentials_are_not_created(self):
        self.config["database_token_file"] = str(self.private / "absent.token")
        self.assert_rejected()
        self.assertFalse((self.private / "absent.token").exists())
        self.assertEqual(self.http.calls, [])

    def test_insecure_output_parent_is_not_accepted(self):
        public = self.private / "public"
        public.mkdir(mode=0o755)
        public.chmod(0o755)
        self.config["output_directory"] = str(public / "result")
        self.assert_rejected()
        self.assertFalse((public / "result").exists())

    def test_unsupported_tursodb_uuid_marker_blocks_before_http(self):
        self.config["database_id"] = "01234567-8910-4000-8000-012345678901"
        self.assert_rejected()
        self.assertEqual(self.http.calls, [])

    def test_generated_or_hidden_source_column_cannot_be_omitted(self):
        self.http.source.execute(
            "ALTER TABLE users ADD COLUMN generated_value TEXT GENERATED ALWAYS AS (username) VIRTUAL"
        )
        self.assert_rejected()

    def test_readonly_inventory_reports_no_writes(self):
        def transform(path, data):
            if path == "/v2/pipeline":
                data["results"][0]["response"]["result"]["affected_row_count"] = 1
            return data

        self.http.transform = transform
        self.assert_rejected()

    def test_permanent_replica_role_cannot_be_pinned_as_primary(self):
        self.http.instances[0]["type"] = "replica"
        self.assert_rejected()

    def test_ambiguous_database_identity_aliases_are_rejected(self):
        self.http.database["dbId"] = self.http.database["DbId"]
        self.assert_rejected()

    def test_invalid_source_sequence_is_not_a_compatible_baseline(self):
        self.http.source.execute("UPDATE sqlite_sequence SET seq=7")
        self.http.dump = self.http.dump.replace(b"SET seq=40", b"SET seq=7")
        self.assert_rejected()

    def test_documented_dump_newline_carriage_return_expressions_preserve_text(self):
        self.http.source.execute("UPDATE users SET username=?", ("line\n雪\rtext",))
        self.http.dump = self.http.dump.replace(
            "'quote'' / 雪'".encode(),
            "replace(replace('line\\n雪\\rtext','\\r',char(13)),'\\n',char(10))".encode(),
        )
        code, stdout, stderr = self.run_transfer()
        self.assertEqual((code, stdout, stderr), (0, "transfer verified\n", ""))

    def test_dump_http_error_after_complete_source_queries_never_imports(self):
        self.http.dump_status = 403
        self.http.dump = b"PRIVATE-TOKEN-A error with https://secret.invalid/?token=SYNTHETIC-PRIVATE-CREDENTIAL"
        self.assert_rejected()
        self.assertFalse((self.private / "result/staged.sqlite3").exists())
        self.assertTrue(any(url.endswith("/dump") for _, url, _ in self.http.calls))

    def test_dump_redirect_after_source_capture_is_not_followed(self):
        self.http.dump_status = 302
        self.http.dump_headers = {
            "Location": "https://secret.invalid/?token=SYNTHETIC-PRIVATE-CREDENTIAL"
        }
        self.assert_rejected()
        self.assertTrue(
            all("secret.invalid" not in url for _, url, _ in self.http.calls)
        )

    def test_truncated_http_json_is_not_a_valid_collection(self):
        self.http.raw_transform = (
            lambda path, data: data[:-2] if path == "/v2/pipeline" else data
        )
        self.assert_rejected()

    def test_provider_dump_sequence_delete_insert_form_preserves_state(self):
        self.http.dump = self.http.dump.replace(
            b"UPDATE sqlite_sequence SET seq=40 WHERE name='SchemaVersions';",
            b"DELETE FROM sqlite_sequence; INSERT INTO sqlite_sequence VALUES('SchemaVersions',40);",
        )
        self.http.dump = self.http.dump.replace(
            b"CREATE TABLE users", b"CREATE TABLE IF NOT EXISTS users"
        )
        code, stdout, stderr = self.run_transfer()
        self.assertEqual((code, stdout, stderr), (0, "transfer verified\n", ""))

    def test_integer_form_dump_float_retains_declared_real_storage(self):
        self.http.dump = self.http.dump.replace(
            b"0000000002,4.0,1432", b"0000000002,4,1432"
        )
        code, stdout, stderr = self.run_transfer()
        self.assertEqual((code, stdout, stderr), (0, "transfer verified\n", ""))

    def test_cursor_repetition_cannot_skip_or_duplicate_pages(self):
        def transform(path, data):
            if path == "/v2/pipeline":
                result = data["results"][0]["response"]["result"]
                if result["cols"][0]["name"] == "scan_cursor" and result["rows"]:
                    result["rows"][0][0] = {"type": "integer", "value": "-999"}
            return data

        self.http.transform = transform
        self.assert_rejected()

    def test_sensitive_sqlite_error_does_not_escape_import(self):
        self.http.dump = self.http.dump.replace(
            b"'11111111-1111-4111-8111-111111111111','quote''",
            b"'11111111-1111-4111-8111-111111111111' 'PRIVATE-TOKEN-A','quote''",
        )
        self.assert_rejected()

    def test_dump_cannot_load_extensions_or_attach_files(self):
        self.http.dump = self.http.dump.replace(
            "'quote'' / 雪'".encode(), b"load_extension('PRIVATE-TOKEN-A')"
        )
        self.assert_rejected()

    def test_source_encryption_metadata_cannot_be_ignored(self):
        self.http.database["encryption_cipher"] = "aes256cbc"
        self.assert_rejected()

    def test_ambient_tls_key_logging_cannot_write_secret_artifacts(self):
        path = self.private / "unexpected.keylog"
        with (
            patch.dict(os.environ, {"SSLKEYLOGFILE": str(path)}),
            patch(
                "http.client.HTTPSConnection",
                side_effect=ValueError("synthetic network stop"),
            ),
        ):
            code, stdout, stderr = self.run_transfer(network_adapter=True)
        self.assertEqual(code, 1)
        self.assertFalse(path.exists())

    def test_same_bytes_blob_to_text_storage_drift_blocks_import(self):
        self.http.source.execute("UPDATE users SET display_name=?", (b"payload",))
        self.http.dump = self.http.dump.replace(b"CAST(X'00FF' AS BLOB)", b"'payload'")
        self.assert_rejected()

    def test_null_and_empty_text_are_not_equivalent(self):
        self.http.dump = self.http.dump.replace(b"avatar',1,NULL)", b"avatar',1,'')")
        self.assert_rejected()

    def test_constraint_drift_blocks_import_even_with_valid_current_rows(self):
        self.http.dump = self.http.dump.replace(
            b"CHECK (status IN ('waiting', 'active', 'completed', 'forfeited', 'abandoned'))",
            b"",
        )
        self.assert_rejected()


if __name__ == "__main__":
    unittest.main()
