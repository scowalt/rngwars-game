namespace RNGWars.Api.Tests

open System.IO
open System.Text.Json
open Microsoft.Data.Sqlite
open RNGWars

module SyntheticDatabase =
    let execute (connection: SqliteConnection) sql =
        use command = connection.CreateCommand()
        command.CommandText <- sql
        command.ExecuteNonQuery() |> ignore

    let private seedWithSchema path scriptCount imported transform =
        use connection = new SqliteConnection($"Data Source={path};Pooling=False")
        connection.Open()
        let scripts =
            [ "RNGWars.Api.migrations.001_initial_schema.sql", "2026-03-22 23:36:16.1839508"
              "RNGWars.Api.migrations.002_add_oauth_fields.sql", "2026-03-23 01:02:03.4567890" ]
        execute connection "CREATE TABLE SchemaVersions (SchemaVersionID INTEGER CONSTRAINT PK_SchemaVersions_Id PRIMARY KEY AUTOINCREMENT NOT NULL, ScriptName TEXT NOT NULL, Applied DATETIME NOT NULL)"
        for name, timestamp in scripts |> List.take scriptCount do
            use stream = typeof<Models.User>.Assembly.GetManifestResourceStream(name)
            use reader = new StreamReader(stream)
            let sql = reader.ReadToEnd()
            let schemaSql =
                if not imported then sql
                elif name.EndsWith("001_initial_schema.sql") then
                    sql.Insert(sql.IndexOf("\n);", System.StringComparison.Ordinal), ", auth_provider TEXT, auth_id TEXT, email TEXT, display_name TEXT, avatar_url TEXT, is_anonymous INTEGER NOT NULL DEFAULT 1, linked_at TEXT")
                else
                    "CREATE UNIQUE INDEX idx_users_auth ON users(auth_provider, auth_id) WHERE auth_provider IS NOT NULL"
            execute connection (transform schemaSql)
            use command = connection.CreateCommand()
            command.CommandText <- "INSERT INTO SchemaVersions (ScriptName, Applied) VALUES (@name, @timestamp)"
            command.Parameters.AddWithValue("@name", name) |> ignore
            command.Parameters.AddWithValue("@timestamp", timestamp) |> ignore
            command.ExecuteNonQuery() |> ignore
        execute connection "INSERT INTO users (id, username, anonymous_id, rng_score, total_wins, total_losses, total_matches, created_at, last_seen_at) VALUES ('synthetic-player-1', 'HistoricalOne', '11111111-1111-4111-8111-111111111111', 1456, 12, 7, 19, '2026-01-01T01:02:03.004Z', '2026-03-21T12:34:56.789Z'), ('synthetic-player-2', 'HistoricalTwo', '22222222-2222-4222-8222-222222222222', 1188, 3, 9, 12, '2026-01-02T01:02:03.004Z', '2026-03-20T12:34:56.789Z')"
        if scriptCount = 2 then
            execute connection "UPDATE users SET auth_provider = 'github', auth_id = 'synthetic-auth-2', email = 'synthetic@example.invalid', display_name = 'Historical Two', avatar_url = 'https://example.invalid/avatar', is_anonymous = 0, linked_at = '2026-02-03T04:05:06.007Z' WHERE id = 'synthetic-player-2'"
        execute connection "INSERT INTO matches (id, player1_id, player2_id, winner_id, status, is_practice, ai_name, player1_roll, player2_roll, player1_elo_before, player2_elo_before, player1_elo_after, player2_elo_after, started_at, completed_at, created_at) VALUES ('synthetic-completed-match', 'synthetic-player-1', 'synthetic-player-2', 'synthetic-player-1', 'completed', 0, NULL, 0.875, 0.25, 1444, 1200, 1456, 1188, '2026-03-21T10:00:00.000Z', '2026-03-21T10:00:20.000Z', '2026-03-21T10:00:00.000Z'), ('synthetic-practice-match', 'synthetic-player-1', NULL, NULL, 'completed', 1, 'Historical Bot', 0.125, 0.75, 1456, NULL, 1456, NULL, '2026-03-21T11:00:00.000Z', '2026-03-21T11:00:20.000Z', '2026-03-21T11:00:00.000Z')"

    let seed path scriptCount = seedWithSchema path scriptCount false id

    let seedImportedWithSql path transform =
        seedWithSchema path 2 true transform
        use connection = new SqliteConnection($"Data Source={path};Pooling=False")
        connection.Open()
        execute connection "UPDATE SchemaVersions SET SchemaVersionID = 3 WHERE SchemaVersionID = 1; UPDATE SchemaVersions SET SchemaVersionID = 8 WHERE SchemaVersionID = 2; UPDATE sqlite_sequence SET seq = 40 WHERE name = 'SchemaVersions'"

    let seedImported path = seedImportedWithSql path id

    let snapshot path =
        use connection = new SqliteConnection($"Data Source={path};Mode=ReadOnly;Pooling=False")
        connection.Open()
        [ for sql in [ "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
                       "SELECT * FROM SchemaVersions ORDER BY 1"
                       "SELECT rowid, * FROM users ORDER BY id"
                       "SELECT rowid, * FROM matches ORDER BY id"
                       "SELECT * FROM sqlite_sequence ORDER BY name" ] do
            use command = connection.CreateCommand()
            command.CommandText <- sql
            use reader = command.ExecuteReader()
            let rows =
                [ while reader.Read() do
                    yield [ for index in 0 .. reader.FieldCount - 1 do
                                yield if reader.IsDBNull(index) then null else reader.GetValue(index) ] ]
            yield JsonSerializer.Serialize(rows) ]
