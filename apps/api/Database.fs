namespace RNGWars

open System
open System.Data
open System.Reflection
open System.IO
open Microsoft.Data.Sqlite
open Donald
open DbUp

module Database =

    let private environmentName () =
        [ "DOTNET_ENVIRONMENT"; "ASPNETCORE_ENVIRONMENT" ]
        |> List.tryPick (fun name -> Environment.GetEnvironmentVariable(name) |> Option.ofObj)
        |> Option.defaultValue "Production"

    let private canInitialize (environment: string) =
        environment.Equals("Development", StringComparison.OrdinalIgnoreCase)
        || environment.Equals("Testing", StringComparison.OrdinalIgnoreCase)

    let private connectionString (path: string) mode =
        let builder = SqliteConnectionStringBuilder()
        builder.DataSource <- path
        builder.Mode <- mode
        builder.Pooling <- false
        builder.ForeignKeys <- Nullable true
        builder.DefaultTimeout <- 5
        builder.ConnectionString

    let private connectionSettings environment allowCreate =
        let configured = Environment.GetEnvironmentVariable("DATABASE_PATH")
        let path = if isNull configured && canInitialize environment then "game.db" else configured
        if String.IsNullOrWhiteSpace(path) || path = ":memory:"
           || path.StartsWith("file:", StringComparison.OrdinalIgnoreCase) then
            invalidOp "DATABASE_PATH must identify a persistent SQLite file."
        if not (canInitialize environment) && not (Path.IsPathFullyQualified(path)) then
            invalidOp "Production DATABASE_PATH must be an absolute persistent SQLite file path."
        let mode = if allowCreate && canInitialize environment then SqliteOpenMode.ReadWriteCreate else SqliteOpenMode.ReadWrite
        connectionString (Path.GetFullPath(path)) mode

    let private configureConnection (connection: SqliteConnection) =
        use journal = connection.CreateCommand()
        journal.CommandText <- "PRAGMA journal_mode = WAL"
        if string (journal.ExecuteScalar()) <> "wal" then
            invalidOp "SQLite requires writable WAL storage."
        for pragma in [ "PRAGMA busy_timeout = 5000"; "PRAGMA synchronous = NORMAL" ] do
            use command = connection.CreateCommand()
            command.CommandText <- pragma
            command.ExecuteScalar() |> ignore

    let createConnection () : IDbConnection =
        let connection = new SqliteConnection(connectionSettings (environmentName ()) false)
        try
            connection.Open()
            configureConnection connection
            connection :> IDbConnection
        with _ ->
            connection.Dispose()
            reraise ()

    let private migrate connectionString requireProduction =
        use connection = new SqliteConnection(connectionString)
        connection.Open()
        SqliteSchema.validate connection requireProduction
        configureConnection connection
        let upgrader =
            DeployChanges.To
                .SqliteDatabase(connectionString)
                .WithScriptsEmbeddedInAssembly(Assembly.GetExecutingAssembly())
                .WithTransaction()
                .LogToConsole()
                .Build()
        let result = upgrader.PerformUpgrade()
        if not result.Successful then
            failwithf "Database migration failed: %s" (result.Error.ToString())
        SqliteSchema.validate connection false
        use transaction = connection.BeginTransaction()
        use writable = connection.CreateCommand()
        writable.Transaction <- transaction
        writable.CommandText <- "UPDATE users SET rng_score = rng_score WHERE 0"
        writable.ExecuteNonQuery() |> ignore
        transaction.Rollback()
        printfn "Database migrations completed successfully"

    let runMigrationsForEnvironment environment =
        migrate (connectionSettings environment true) (not (canInitialize environment))

    let internal initializeAtPath path =
        let settings = connectionString path SqliteOpenMode.ReadWrite
        migrate settings false
        use connection = new SqliteConnection(settings)
        connection.Open()
        use command = connection.CreateCommand()
        command.CommandText <- "SELECT (SELECT COUNT(*) FROM users) + (SELECT COUNT(*) FROM matches)"
        if Convert.ToInt64(command.ExecuteScalar()) <> 0L then
            invalidOp "Fresh initialization must not seed player or match records."
        command.CommandText <- $"PRAGMA application_id = {SqliteSchema.freshApplicationId}"
        command.ExecuteNonQuery() |> ignore
        SqliteSchema.validate connection true
        command.CommandText <- "PRAGMA journal_mode = DELETE"
        if string (command.ExecuteScalar()) <> "delete" then
            invalidOp "Fresh initialization must finish without WAL sidecars."

    let runMigrations () = runMigrationsForEnvironment (environmentName ())

    let private safeGetString (rd: IDataReader) (name: string) : string =
        let ordinal = rd.GetOrdinal(name)
        if rd.IsDBNull(ordinal) then ""
        else rd.GetValue(ordinal).ToString()

    let private safeGetStringOption (rd: IDataReader) (name: string) : string option =
        let ordinal = rd.GetOrdinal(name)
        if rd.IsDBNull(ordinal) then None
        else Some (rd.GetValue(ordinal).ToString())

    let private safeGetInt32 (rd: IDataReader) (name: string) : int =
        let ordinal = rd.GetOrdinal(name)
        if rd.IsDBNull(ordinal) then 0
        else System.Convert.ToInt32(rd.GetValue(ordinal))

    let private safeGetDouble (rd: IDataReader) (name: string) : float =
        let ordinal = rd.GetOrdinal(name)
        if rd.IsDBNull(ordinal) then 0.0
        else System.Convert.ToDouble(rd.GetValue(ordinal))


    let private readUser (rd: IDataReader) : User =
        { Id = safeGetString rd "id"
          Username = safeGetString rd "username"
          AnonymousId = safeGetString rd "anonymous_id"
          AuthProvider = safeGetStringOption rd "auth_provider"
          AuthId = safeGetStringOption rd "auth_id"
          Email = safeGetStringOption rd "email"
          DisplayName = safeGetStringOption rd "display_name"
          AvatarUrl = safeGetStringOption rd "avatar_url"
          IsAnonymous = safeGetInt32 rd "is_anonymous" = 1
          LinkedAt = safeGetStringOption rd "linked_at"
          RngScore = safeGetInt32 rd "rng_score"
          TotalWins = safeGetInt32 rd "total_wins"
          TotalLosses = safeGetInt32 rd "total_losses"
          TotalMatches = safeGetInt32 rd "total_matches"
          CreatedAt = safeGetString rd "created_at"
          LastSeenAt = safeGetString rd "last_seen_at" }

    let createAnonymousUser () : User =
        let id = Guid.NewGuid().ToString()
        let anonymousId = Guid.NewGuid().ToString()
        let username = sprintf "Player_%s" (id.Substring(0, 6))

        use conn = createConnection ()

        conn
        |> Db.newCommand
            "INSERT INTO users (id, username, anonymous_id) VALUES (@id, @username, @anonymous_id)"
        |> Db.setParams
            [ "@id", SqlType.String id
              "@username", SqlType.String username
              "@anonymous_id", SqlType.String anonymousId ]
        |> Db.exec

        conn
        |> Db.newCommand "SELECT * FROM users WHERE id = @id"
        |> Db.setParams [ "@id", SqlType.String id ]
        |> Db.querySingle readUser
        |> Option.defaultWith (fun () -> invalidOp "Anonymous user was not readable after insert.")

    let getUserByToken (token: string) : User option =
        use conn = createConnection ()

        conn
        |> Db.newCommand "SELECT * FROM users WHERE anonymous_id = @token"
        |> Db.setParams [ "@token", SqlType.String token ]
        |> Db.querySingle readUser

    let getUserById (id: string) : User option =
        use conn = createConnection ()

        conn
        |> Db.newCommand "SELECT * FROM users WHERE id = @id"
        |> Db.setParams [ "@id", SqlType.String id ]
        |> Db.querySingle readUser

    let updateUsername (userId: string) (username: string) : User option =
        use conn = createConnection ()

        conn
        |> Db.newCommand "UPDATE users SET username = @username WHERE id = @id"
        |> Db.setParams
            [ "@username", SqlType.String username
              "@id", SqlType.String userId ]
        |> Db.exec

        conn
        |> Db.newCommand "SELECT * FROM users WHERE id = @id"
        |> Db.setParams [ "@id", SqlType.String userId ]
        |> Db.querySingle readUser

    let getLeaderboard (offset: int) (limit: int) : User list =
        use conn = createConnection ()

        conn
        |> Db.newCommand
            "SELECT * FROM users WHERE total_matches > 0 ORDER BY rng_score DESC, total_wins DESC LIMIT @limit OFFSET @offset"
        |> Db.setParams
            [ "@limit", SqlType.Int32 limit
              "@offset", SqlType.Int32 offset ]
        |> Db.query readUser

    let getUserByAuthId (provider: string) (authId: string) : User option =
        use conn = createConnection ()

        conn
        |> Db.newCommand "SELECT * FROM users WHERE auth_provider = @provider AND auth_id = @authId"
        |> Db.setParams
            [ "@provider", SqlType.String provider
              "@authId", SqlType.String authId ]
        |> Db.querySingle readUser

    let linkAnonymousToAuth (userId: string) (provider: string) (authId: string) (email: string option) (displayName: string option) (avatarUrl: string option) : User option =
        use conn = createConnection ()

        conn
        |> Db.newCommand
            "UPDATE users SET auth_provider = @provider, auth_id = @authId, email = @email, display_name = @displayName, avatar_url = @avatarUrl, is_anonymous = 0, linked_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = @id"
        |> Db.setParams
            [ "@provider", SqlType.String provider
              "@authId", SqlType.String authId
              "@email", (match email with Some e -> SqlType.String e | None -> SqlType.Null)
              "@displayName", (match displayName with Some d -> SqlType.String d | None -> SqlType.Null)
              "@avatarUrl", (match avatarUrl with Some a -> SqlType.String a | None -> SqlType.Null)
              "@id", SqlType.String userId ]
        |> Db.exec

        conn
        |> Db.newCommand "SELECT * FROM users WHERE id = @id"
        |> Db.setParams [ "@id", SqlType.String userId ]
        |> Db.querySingle readUser

    let mergeAnonymousIntoExisting (anonymousUserId: string) (existingUserId: string) : User option =
        use conn = createConnection ()

        let anon =
            conn
            |> Db.newCommand "SELECT * FROM users WHERE id = @id"
            |> Db.setParams [ "@id", SqlType.String anonymousUserId ]
            |> Db.querySingle readUser

        let existing =
            conn
            |> Db.newCommand "SELECT * FROM users WHERE id = @id"
            |> Db.setParams [ "@id", SqlType.String existingUserId ]
            |> Db.querySingle readUser

        match anon, existing with
        | Some a, Some e ->
            let newElo = max a.RngScore e.RngScore

            conn
            |> Db.newCommand
                "UPDATE users SET total_wins = @wins, total_losses = @losses, total_matches = @matches, rng_score = @elo WHERE id = @id"
            |> Db.setParams
                [ "@wins", SqlType.Int32 (a.TotalWins + e.TotalWins)
                  "@losses", SqlType.Int32 (a.TotalLosses + e.TotalLosses)
                  "@matches", SqlType.Int32 (a.TotalMatches + e.TotalMatches)
                  "@elo", SqlType.Int32 newElo
                  "@id", SqlType.String existingUserId ]
            |> Db.exec

            conn
            |> Db.newCommand "UPDATE matches SET player1_id = @newId WHERE player1_id = @oldId"
            |> Db.setParams
                [ "@newId", SqlType.String existingUserId
                  "@oldId", SqlType.String anonymousUserId ]
            |> Db.exec

            conn
            |> Db.newCommand "UPDATE matches SET player2_id = @newId WHERE player2_id = @oldId"
            |> Db.setParams
                [ "@newId", SqlType.String existingUserId
                  "@oldId", SqlType.String anonymousUserId ]
            |> Db.exec

            conn
            |> Db.newCommand "DELETE FROM users WHERE id = @id"
            |> Db.setParams [ "@id", SqlType.String anonymousUserId ]
            |> Db.exec

            conn
            |> Db.newCommand "SELECT * FROM users WHERE id = @id"
            |> Db.setParams [ "@id", SqlType.String existingUserId ]
            |> Db.querySingle readUser
        | _ -> None

    let updateLastSeen (userId: string) : unit =
        use conn = createConnection ()

        conn
        |> Db.newCommand
            "UPDATE users SET last_seen_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = @id"
        |> Db.setParams [ "@id", SqlType.String userId ]
        |> Db.exec


    let private safeGetInt32Option (rd: IDataReader) (name: string) : int option =
        let ordinal = rd.GetOrdinal(name)
        if rd.IsDBNull(ordinal) then None
        else Some (System.Convert.ToInt32(rd.GetValue(ordinal)))

    let private safeGetDoubleOption (rd: IDataReader) (name: string) : float option =
        let ordinal = rd.GetOrdinal(name)
        if rd.IsDBNull(ordinal) then None
        else Some (System.Convert.ToDouble(rd.GetValue(ordinal)))

    let private readMatch (rd: IDataReader) : Match =
        { Id = safeGetString rd "id"
          Player1Id = safeGetString rd "player1_id"
          Player2Id = safeGetStringOption rd "player2_id"
          WinnerId = safeGetStringOption rd "winner_id"
          Status = safeGetString rd "status"
          IsPractice = safeGetInt32 rd "is_practice" = 1
          AiName = safeGetStringOption rd "ai_name"
          Player1Roll = safeGetDoubleOption rd "player1_roll"
          Player2Roll = safeGetDoubleOption rd "player2_roll"
          Player1EloBefore = safeGetInt32Option rd "player1_elo_before"
          Player2EloBefore = safeGetInt32Option rd "player2_elo_before"
          Player1EloAfter = safeGetInt32Option rd "player1_elo_after"
          Player2EloAfter = safeGetInt32Option rd "player2_elo_after"
          StartedAt = safeGetStringOption rd "started_at"
          CompletedAt = safeGetStringOption rd "completed_at"
          CreatedAt = safeGetString rd "created_at" }

    let getMatchById (matchId: string) : Match option =
        use conn = createConnection ()

        conn
        |> Db.newCommand "SELECT * FROM matches WHERE id = @id"
        |> Db.setParams [ "@id", SqlType.String matchId ]
        |> Db.querySingle readMatch

    let getPlayerMatches (playerId: string) (offset: int) (limit: int) : Match list =
        use conn = createConnection ()

        conn
        |> Db.newCommand
            "SELECT * FROM matches
             WHERE (player1_id = @player_id OR player2_id = @player_id)
               AND status IN ('completed', 'forfeited')
             ORDER BY created_at DESC
             LIMIT @limit OFFSET @offset"
        |> Db.setParams
            [ "@player_id", SqlType.String playerId
              "@limit", SqlType.Int32 limit
              "@offset", SqlType.Int32 offset ]
        |> Db.query readMatch

    let countPlayerMatches (playerId: string) : int =
        use conn = createConnection ()

        conn
        |> Db.newCommand
            "SELECT COUNT(*) as cnt FROM matches
             WHERE (player1_id = @player_id OR player2_id = @player_id)
               AND status IN ('completed', 'forfeited')"
        |> Db.setParams [ "@player_id", SqlType.String playerId ]
        |> Db.querySingle (fun rd -> safeGetInt32 rd "cnt")
        |> Option.defaultValue 0

    let createPracticeMatch (matchId: string) (playerId: string) (aiName: string) : unit =
        use conn = createConnection ()

        conn
        |> Db.newCommand
            "INSERT INTO matches (id, player1_id, status, is_practice, ai_name, started_at)
             VALUES (@id, @player1_id, 'active', 1, @ai_name, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"
        |> Db.setParams
            [ "@id", SqlType.String matchId
              "@player1_id", SqlType.String playerId
              "@ai_name", SqlType.String aiName ]
        |> Db.exec

    let createMultiplayerMatch (matchId: string) (player1Id: string) (player2Id: string) : unit =
        use conn = createConnection ()

        conn
        |> Db.newCommand
            "INSERT INTO matches (id, player1_id, player2_id, status, is_practice, started_at)
             VALUES (@id, @p1_id, @p2_id, 'active', 0, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"
        |> Db.setParams
            [ "@id", SqlType.String matchId
              "@p1_id", SqlType.String player1Id
              "@p2_id", SqlType.String player2Id ]
        |> Db.exec

    let completeMatchWithElo
        (matchId: string)
        (winnerId: string)
        (p1Roll: float)
        (p2Roll: float)
        (p1Id: string)
        (p2Id: string)
        (p1EloBefore: int)
        (p1EloAfter: int)
        (p2EloBefore: int)
        (p2EloAfter: int)
        : unit =
        use conn = createConnection ()
        let p1Won = winnerId = p1Id

        conn
        |> Db.newCommand
            "UPDATE matches SET
                status = 'completed', winner_id = @winner_id,
                player1_roll = @p1_roll, player2_roll = @p2_roll,
                player1_elo_before = @p1_elo_before, player2_elo_before = @p2_elo_before,
                player1_elo_after = @p1_elo_after, player2_elo_after = @p2_elo_after,
                completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
             WHERE id = @match_id"
        |> Db.setParams
            [ "@winner_id", SqlType.String winnerId
              "@p1_roll", SqlType.Double p1Roll
              "@p2_roll", SqlType.Double p2Roll
              "@p1_elo_before", SqlType.Int32 p1EloBefore
              "@p2_elo_before", SqlType.Int32 p2EloBefore
              "@p1_elo_after", SqlType.Int32 p1EloAfter
              "@p2_elo_after", SqlType.Int32 p2EloAfter
              "@match_id", SqlType.String matchId ]
        |> Db.exec

        conn
        |> Db.newCommand
            "UPDATE users SET
                rng_score = @new_elo,
                total_wins = total_wins + @win_inc,
                total_losses = total_losses + @loss_inc,
                total_matches = total_matches + 1
             WHERE id = @user_id"
        |> Db.setParams
            [ "@new_elo", SqlType.Int32 p1EloAfter
              "@win_inc", SqlType.Int32 (if p1Won then 1 else 0)
              "@loss_inc", SqlType.Int32 (if p1Won then 0 else 1)
              "@user_id", SqlType.String p1Id ]
        |> Db.exec

        conn
        |> Db.newCommand
            "UPDATE users SET
                rng_score = @new_elo,
                total_wins = total_wins + @win_inc,
                total_losses = total_losses + @loss_inc,
                total_matches = total_matches + 1
             WHERE id = @user_id"
        |> Db.setParams
            [ "@new_elo", SqlType.Int32 p2EloAfter
              "@win_inc", SqlType.Int32 (if p1Won then 0 else 1)
              "@loss_inc", SqlType.Int32 (if p1Won then 1 else 0)
              "@user_id", SqlType.String p2Id ]
        |> Db.exec

    let completePracticeMatch
        (matchId: string)
        (winnerId: string)
        (p1Roll: float)
        (p2Roll: float)
        (p1Id: string)
        (p1Elo: int)
        : unit =
        use conn = createConnection ()

        conn
        |> Db.newCommand
            "UPDATE matches SET
                status = 'completed', winner_id = @winner_id,
                player1_roll = @p1_roll, player2_roll = @p2_roll,
                player1_elo_before = @p1_elo, player1_elo_after = @p1_elo,
                completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
             WHERE id = @match_id"
        |> Db.setParams
            [ "@winner_id", (if winnerId = "" then SqlType.Null else SqlType.String winnerId)
              "@p1_roll", SqlType.Double p1Roll
              "@p2_roll", SqlType.Double p2Roll
              "@p1_elo", SqlType.Int32 p1Elo
              "@match_id", SqlType.String matchId ]
        |> Db.exec

        conn
        |> Db.newCommand
            "UPDATE users SET total_matches = total_matches + 1 WHERE id = @user_id"
        |> Db.setParams [ "@user_id", SqlType.String p1Id ]
        |> Db.exec

    let forfeitMatch (matchId: string) (winnerId: string) : unit =
        use conn = createConnection ()

        conn
        |> Db.newCommand
            "UPDATE matches SET
                status = 'forfeited', winner_id = @winner_id,
                completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
             WHERE id = @match_id"
        |> Db.setParams
            [ "@winner_id", SqlType.String winnerId
              "@match_id", SqlType.String matchId ]
        |> Db.exec

    let abandonMatch (matchId: string) : unit =
        use conn = createConnection ()

        conn
        |> Db.newCommand
            "UPDATE matches SET
                status = 'abandoned',
                completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
             WHERE id = @match_id"
        |> Db.setParams [ "@match_id", SqlType.String matchId ]
        |> Db.exec
