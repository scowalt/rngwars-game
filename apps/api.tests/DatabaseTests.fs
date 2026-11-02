namespace RNGWars.Api.Tests

open Xunit
open RNGWars
open System
open System.IO
open Microsoft.Data.Sqlite

[<CollectionDefinition("Database environment", DisableParallelization = true)>]
type DatabaseEnvironmentCollection() = class end

[<Collection("Database environment")>]
type DatabaseConfigurationTests() =
    let withDatabase environment action =
        let names = [ "ASPNETCORE_ENVIRONMENT"; "DOTNET_ENVIRONMENT"; "DATABASE_PATH" ]
        let previous = names |> List.map Environment.GetEnvironmentVariable
        let directory = Path.Combine(Path.GetTempPath(), "rngwars-database-" + Guid.NewGuid().ToString("N"))
        let path = Path.Combine(directory, "game.db")
        Directory.CreateDirectory(directory) |> ignore
        try
            Environment.SetEnvironmentVariable("ASPNETCORE_ENVIRONMENT", environment)
            Environment.SetEnvironmentVariable("DOTNET_ENVIRONMENT", null)
            Environment.SetEnvironmentVariable("DATABASE_PATH", path)
            action path
        finally
            List.zip names previous |> List.iter (fun (name, value) -> Environment.SetEnvironmentVariable(name, value))
            SqliteConnection.ClearAllPools()
            Directory.Delete(directory, true)

    [<Theory>]
    [<InlineData(null)>]
    [<InlineData("")>]
    [<InlineData(" ")>]
    [<InlineData(":memory:")>]
    [<InlineData("file:memory?mode=memory")>]
    [<InlineData("relative.db")>]
    [<InlineData("missing")>]
    let ``production rejects missing or ephemeral storage without creating a population`` (setting: string) =
        withDatabase "Production" (fun path ->
            Environment.SetEnvironmentVariable("DATABASE_PATH", if setting = "missing" then path else setting)
            for action in [ Database.runMigrations; (fun () -> use connection = Database.createConnection () in ()) ] do
                Assert.ThrowsAny<Exception>(Action action) |> ignore
            Assert.False(File.Exists(path)))

    [<Theory>]
    [<InlineData("")>]
    [<InlineData("not a SQLite database")>]
    let ``production rejects empty or invalid existing files without initializing schema`` (contents: string) =
        withDatabase "Production" (fun path ->
            File.WriteAllText(path, contents)
            let before = File.ReadAllBytes(path)
            Assert.ThrowsAny<Exception>(fun () -> Database.runMigrations ()) |> ignore
            Assert.Equal<byte>(before, File.ReadAllBytes(path)))

    [<Fact>]
    let ``production rejects a journal claiming migrations without the gameplay schema`` () =
        withDatabase "Production" (fun path ->
            use connection = new SqliteConnection($"Data Source={path};Pooling=False")
            connection.Open()
            use command = connection.CreateCommand()
            command.CommandText <- "CREATE TABLE users (id TEXT); INSERT INTO users VALUES ('synthetic-existing-player'); CREATE TABLE SchemaVersions (SchemaVersionID INTEGER PRIMARY KEY, ScriptName TEXT NOT NULL, Applied DATETIME NOT NULL); INSERT INTO SchemaVersions VALUES (1, 'RNGWars.Api.migrations.001_initial_schema.sql', '2026-03-22 23:36:16.1839508'), (2, 'RNGWars.Api.migrations.002_add_oauth_fields.sql', '2026-03-23 01:02:03.4567890')"
            command.ExecuteNonQuery() |> ignore
            Assert.ThrowsAny<Exception>(fun () -> Database.runMigrations ()) |> ignore
            command.CommandText <- "SELECT COUNT(*) FROM sqlite_master WHERE name = 'matches'"
            Assert.Equal(0L, Convert.ToInt64(command.ExecuteScalar())))

    [<Fact>]
    let ``historical production records schema and journal survive native startup unchanged`` () =
        withDatabase "Production" (fun path ->
            SyntheticDatabase.seed path 2
            let before = SyntheticDatabase.snapshot path
            Database.runMigrations ()
            Database.runMigrations ()
            Assert.Equal<string list>(before, SyntheticDatabase.snapshot path)
            let player = Database.getUserByToken "11111111-1111-4111-8111-111111111111" |> Option.get
            Assert.Equal("synthetic-player-1", player.Id)
            Assert.Equal(1456, player.RngScore)
            Assert.Equal(12, player.TotalWins)
            Assert.Equal(7, player.TotalLosses)
            Assert.Equal(19, player.TotalMatches)
            Assert.Equal(Some "synthetic-auth-2", (Database.getUserByToken "22222222-2222-4222-8222-222222222222" |> Option.get).AuthId)
            let completed = Database.getMatchById "synthetic-completed-match" |> Option.get
            Assert.Equal(Some 0.875, completed.Player1Roll)
            Assert.Equal(Some 1188, completed.Player2EloAfter)
            Assert.Equal(2, Database.countPlayerMatches player.Id)
            Assert.Equal("synthetic-player-1", (Database.getLeaderboard 0 20).Head.Id))

    [<Fact>]
    let ``imported dump formatting starts production without changing records schema journal or sequence`` () =
        withDatabase "Production" (fun path ->
            SyntheticDatabase.seedImported path
            let before = SyntheticDatabase.snapshot path
            Database.runMigrations ()
            Database.runMigrations ()
            Assert.Equal<string list>(before, SyntheticDatabase.snapshot path)
            let player = Database.getUserByToken "11111111-1111-4111-8111-111111111111" |> Option.get
            Assert.Equal("synthetic-player-1", player.Id)
            Assert.Equal("HistoricalOne", player.Username)
            Assert.Equal(1456, player.RngScore)
            Assert.Equal(12, player.TotalWins)
            Assert.Equal(7, player.TotalLosses)
            Assert.Equal(19, player.TotalMatches)
            Assert.Equal(Some "synthetic-auth-2", (Database.getUserByToken "22222222-2222-4222-8222-222222222222" |> Option.get).AuthId)
            Assert.Equal(Some 0.875, (Database.getMatchById "synthetic-completed-match" |> Option.get).Player1Roll)
            Assert.Equal(2, Database.countPlayerMatches player.Id)
            Assert.Equal("synthetic-player-1", (Database.getLeaderboard 0 20).Head.Id))

    [<Theory>]
    [<InlineData("TEXT /* synthetic equivalent comment */ PRIMARY KEY")>]
    [<InlineData("TEXT -- synthetic equivalent comment\n PRIMARY KEY")>]
    [<InlineData("TEXT -- synthetic equivalent comment\r\n PRIMARY KEY")>]
    [<InlineData("TEXT PRIMARY/* token separator */KEY")>]
    [<InlineData("TEXT/* token separator */PRIMARY KEY")>]
    let ``production accepts imported SQL comments as token separators without changing the baseline`` (definition: string) =
        withDatabase "Production" (fun path ->
            SyntheticDatabase.seedImportedWithSql path (fun sql -> sql.Replace("id            TEXT PRIMARY KEY", "id            " + definition))
            let before = SyntheticDatabase.snapshot path
            Database.runMigrationsForEnvironment "Production"
            Database.runMigrationsForEnvironment "Production"
            Assert.Equal<string list>(before, SyntheticDatabase.snapshot path)
            Assert.Equal("synthetic-player-1", (Database.getUserByToken "11111111-1111-4111-8111-111111111111" |> Option.get).Id))

    [<Fact>]
    let ``production accepts intertoken dump whitespace while preserving the exact stored schema`` () =
        withDatabase "Production" (fun path ->
            SyntheticDatabase.seedImportedWithSql path (fun sql ->
                sql.Replace(",", " \t, \n").Replace("(", " ( \t").Replace(")", "\n ) ").Replace("PRIMARY KEY", "PRIMARY\t\nKEY"))
            let before = SyntheticDatabase.snapshot path
            Database.runMigrations ()
            Assert.Equal<string list>(before, SyntheticDatabase.snapshot path))

    [<Theory>]
    [<InlineData("DEFAULT 1200", "DEFAULT 1201")>]
    [<InlineData("DEFAULT 0", "DEFAULT 1")>]
    [<InlineData("rng_score >= 100", "rng_score >= 99")>]
    [<InlineData("rng_score >= 100", "rng_score > 100")>]
    [<InlineData("AND rng_score <= 3000)", "-- constraint removed until newline\r AND rng_score <= 3000\n)")>]
    [<InlineData("DEFAULT 'waiting'", "DEFAULT 'wait ing'")>]
    [<InlineData("DEFAULT 'waiting'", "DEFAULT 'wait''ing'")>]
    [<InlineData("'now'", "'n o w'")>]
    [<InlineData("'now'", "'n''ow'")>]
    [<InlineData("'now'", "'now  '")>]
    [<InlineData("'now'", "'n/* quoted comment marker */ow'")>]
    [<InlineData("'now'", "'n-- quoted comment marker\now'")>]
    [<InlineData("'now'", "'n''/* quoted escape */ow'")>]
    [<InlineData("INDEX idx_users_auth", "INDEX \"idx_users_auth/* quoted marker */\"")>]
    [<InlineData("INDEX idx_users_auth", "INDEX `idx_users_auth--quoted marker`")>]
    [<InlineData("WHERE auth_provider IS NOT NULL", "WHERE auth_provider IS NULL")>]
    [<InlineData("ON matches(player1_id)", "ON matches(player2_id)")>]
    [<InlineData("matches (\n    id            TEXT PRIMARY KEY", "matches (\n    id            TEXT PRIMARYKEY")>]
    [<InlineData("linked_at TEXT", "linked_at TEXT, \"extra \"\"quoted  name\" TEXT")>]
    [<InlineData("INDEX idx_users_auth", "INDEX `idx_users_auth``quoted`")>]
    [<InlineData("INDEX idx_users_auth", "INDEX \"idx_users_auth\"\"quoted\"")>]
    [<InlineData("INDEX idx_users_auth", "INDEX [idx_users_auth quoted]")>]
    let ``production rejects meaningful imported SQL drift without changing the checked database`` (original: string, changed: string) =
        withDatabase "Production" (fun path ->
            SyntheticDatabase.seedImportedWithSql path (fun sql -> sql.Replace(original, changed))
            let before = SyntheticDatabase.snapshot path
            let error = Assert.Throws<InvalidOperationException>(fun () -> Database.runMigrations ())
            Assert.Contains("gameplay schema does not match", error.Message)
            Assert.Equal<string list>(before, SyntheticDatabase.snapshot path))

    [<Fact>]
    let ``development applies only a pending migration and preserves historical initial journal`` () =
        withDatabase "Development" (fun path ->
            SyntheticDatabase.seed path 1
            Database.runMigrations ()
            Database.runMigrations ()
            use connection = Database.createConnection ()
            use command = connection.CreateCommand()
            command.CommandText <- "SELECT Applied FROM SchemaVersions WHERE SchemaVersionID = 1"
            Assert.Equal("2026-03-22 23:36:16.1839508", string (command.ExecuteScalar()))
            command.CommandText <- "SELECT COUNT(*) FROM SchemaVersions"
            Assert.Equal(2L, Convert.ToInt64(command.ExecuteScalar()))
            Assert.Equal("synthetic-player-1", (Database.getUserByToken "11111111-1111-4111-8111-111111111111" |> Option.get).Id))

    [<Fact>]
    let ``production rejects read only storage before serving any player requests`` () =
        withDatabase "Production" (fun path ->
            SyntheticDatabase.seed path 2
            let before = SyntheticDatabase.snapshot path
            File.SetUnixFileMode(path, UnixFileMode.UserRead)
            try
                Assert.ThrowsAny<Exception>(fun () -> Database.runMigrations ()) |> ignore
                Assert.Equal<string list>(before, SyntheticDatabase.snapshot path)
            finally
                File.SetUnixFileMode(path, UnixFileMode.UserRead ||| UnixFileMode.UserWrite))

    [<Theory>]
    [<InlineData("ALTER TABLE SchemaVersions RENAME COLUMN SchemaVersionID TO RenamedID")>]
    [<InlineData("UPDATE SchemaVersions SET ScriptName = 'unknown-migration.sql' WHERE SchemaVersionID = 2")>]
    [<InlineData("UPDATE SchemaVersions SET ScriptName = 'RNGWars.Api.migrations.001_initial_schema.sql' WHERE SchemaVersionID = 2")>]
    [<InlineData("UPDATE SchemaVersions SET Applied = 'invalid-history' WHERE SchemaVersionID = 1")>]
    [<InlineData("DELETE FROM SchemaVersions WHERE SchemaVersionID = 2")>]
    [<InlineData("DROP INDEX idx_users_auth")>]
    [<InlineData("ALTER TABLE users RENAME COLUMN rng_score TO changed_rating")>]
    [<InlineData("UPDATE matches SET player2_id = 'missing-player'")>]
    let ``production rejects schema journal or record drift before migrating`` (mutation: string) =
        withDatabase "Production" (fun path ->
            SyntheticDatabase.seed path 2
            use connection = new SqliteConnection($"Data Source={path};Pooling=False")
            connection.Open()
            SyntheticDatabase.execute connection "PRAGMA foreign_keys = OFF"
            SyntheticDatabase.execute connection mutation
            let before = SyntheticDatabase.snapshot path
            Assert.ThrowsAny<Exception>(fun () -> Database.runMigrations ()) |> ignore
            Assert.Equal<string list>(before, SyntheticDatabase.snapshot path))

    [<Fact>]
    let ``production rejects a migrated database without a player population`` () =
        withDatabase "Production" (fun path ->
            SyntheticDatabase.seed path 2
            use connection = new SqliteConnection($"Data Source={path};Pooling=False")
            connection.Open()
            SyntheticDatabase.execute connection "DELETE FROM matches; DELETE FROM users"
            Assert.ThrowsAny<Exception>(fun () -> Database.runMigrations ()) |> ignore)

    [<Fact>]
    let ``production rejects a non writable parent directory needed for WAL storage`` () =
        withDatabase "Production" (fun path ->
            SyntheticDatabase.seed path 2
            let directory = Path.GetDirectoryName(path)
            File.SetUnixFileMode(directory, UnixFileMode.UserRead ||| UnixFileMode.UserExecute)
            try
                Assert.ThrowsAny<Exception>(fun () -> Database.runMigrations ()) |> ignore
            finally
                File.SetUnixFileMode(directory, UnixFileMode.UserRead ||| UnixFileMode.UserWrite ||| UnixFileMode.UserExecute))

    [<Fact>]
    let ``runtime never recreates a database removed after startup`` () =
        withDatabase "Development" (fun path ->
            Database.runMigrations ()
            File.Delete(path)
            Assert.ThrowsAny<Exception>(fun () -> Database.createAnonymousUser () |> ignore) |> ignore
            Assert.False(File.Exists(path)))

    [<Fact>]
    let ``development refuses a populated schema without migration history`` () =
        withDatabase "Development" (fun path ->
            SyntheticDatabase.seed path 2
            use connection = new SqliteConnection($"Data Source={path};Pooling=False")
            connection.Open()
            SyntheticDatabase.execute connection "DROP TABLE SchemaVersions"
            Assert.ThrowsAny<Exception>(fun () -> Database.runMigrations ()) |> ignore
            Assert.Equal("synthetic-player-1", (Database.getUserByToken "11111111-1111-4111-8111-111111111111" |> Option.get).Id))

    [<Fact>]
    let ``native startup preserves committed WAL state and existing SQLite constraints`` () =
        withDatabase "Production" (fun path ->
            SyntheticDatabase.seed path 2
            use writer = new SqliteConnection($"Data Source={path};Pooling=False")
            writer.Open()
            SyntheticDatabase.execute writer "PRAGMA journal_mode = WAL; PRAGMA wal_autocheckpoint = 0; UPDATE users SET rng_score = 1500 WHERE id = 'synthetic-player-1'"
            Assert.True(File.Exists(path + "-wal"))
            let before = SyntheticDatabase.snapshot path
            Database.runMigrations ()
            Assert.Equal<string list>(before, SyntheticDatabase.snapshot path)
            Assert.Equal(1500, (Database.getUserByToken "11111111-1111-4111-8111-111111111111" |> Option.get).RngScore)
            use connection = Database.createConnection ()
            for sql in
                [ "INSERT INTO users (id, username, anonymous_id) VALUES ('duplicate-token-player', 'Duplicate', '11111111-1111-4111-8111-111111111111')"
                  "UPDATE users SET rng_score = 99 WHERE id = 'synthetic-player-1'"
                  "DELETE FROM users WHERE id = 'synthetic-player-1'"
                  "INSERT INTO matches (id, player1_id) VALUES ('invalid-player-match', 'missing-player')" ] do
                use command = connection.CreateCommand()
                command.CommandText <- sql
                Assert.Throws<SqliteException>(fun () -> command.ExecuteNonQuery() |> ignore) |> ignore
            Assert.Equal<string list>(before, SyntheticDatabase.snapshot path))

    [<Fact>]
    let ``development startup and application connections use native SQLite`` () =
        withDatabase "Development" (fun _ ->
            Database.runMigrations ()
            use connection = Database.createConnection ()
            Assert.IsType<SqliteConnection>(connection) |> ignore
            let user = Database.createAnonymousUser ()
            Assert.Equal(Some user, Database.getUserByToken user.AnonymousId)
            Database.updateUsername user.Id "Saved_Player" |> ignore
            Database.runMigrations ()
            let returning = Database.getUserByToken user.AnonymousId |> Option.get
            Assert.Equal(user.Id, returning.Id)
            Assert.Equal("Saved_Player", returning.Username))
