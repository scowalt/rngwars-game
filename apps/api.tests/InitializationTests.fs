namespace RNGWars.Api.Tests

open System
open System.Diagnostics
open System.IO
open Microsoft.Data.Sqlite
open RNGWars
open Xunit

[<Collection("Database environment")>]
type InitializationTests() =
    let privateDirectory = UnixFileMode.UserRead ||| UnixFileMode.UserWrite ||| UnixFileMode.UserExecute

    let withDestination action =
        let directory = Path.Combine(Path.GetTempPath(), "rngwars-init-test-" + Guid.NewGuid().ToString("N"))
        Directory.CreateDirectory(directory, privateDirectory) |> ignore
        try
            action (Path.Combine(directory, "game.db"))
        finally
            SqliteConnection.ClearAllPools()
            Directory.Delete(directory, true)

    let invokeWithLimit limited arguments =
        let host = Environment.GetEnvironmentVariable("DOTNET_HOST_PATH") |> Option.ofObj |> Option.defaultValue "dotnet"
        let start = ProcessStartInfo(if limited then "/usr/bin/prlimit" else host)
        if limited then
            for argument in [ "--fsize=1024:1024"; "--core=0:0"; "--"; host ] do
                start.ArgumentList.Add(argument)
        start.UseShellExecute <- false
        start.RedirectStandardOutput <- true
        start.RedirectStandardError <- true
        start.Environment.Clear()
        for name in [ "PATH"; "DOTNET_ROOT"; "HOME" ] do
            match Environment.GetEnvironmentVariable(name) with
            | null -> ()
            | value -> start.Environment[name] <- value
        start.Environment["ASPNETCORE_ENVIRONMENT"] <- "Production"
        start.Environment["DOTNET_ENVIRONMENT"] <- "Production"
        start.Environment["DATABASE_PATH"] <- ":memory:"
        start.Environment["DOTNET_URLS"] <- "invalid-listening-address"
        start.Environment["ASPNETCORE_URLS"] <- "invalid-listening-address"
        start.Environment["SENTRY_DSN"] <- ""
        start.Environment["DOTNET_DbgEnableMiniDump"] <- "0"
        if limited then start.Environment["DOTNET_EnableWriteXorExecute"] <- "0"
        start.ArgumentList.Add(typeof<Models.User>.Assembly.Location)
        for argument in arguments do start.ArgumentList.Add(argument)
        use child = Process.Start(start)
        let output = child.StandardOutput.ReadToEndAsync()
        let error = child.StandardError.ReadToEndAsync()
        let exited = child.WaitForExit(15000)
        if not exited then child.Kill(true)
        Assert.True(exited, "Offline initializer must exit without starting the web host")
        child.ExitCode, output.GetAwaiter().GetResult(), error.GetAwaiter().GetResult()

    let invoke arguments = invokeWithLimit false arguments

    [<Fact>]
    let ``initializer never overwrites existing database bytes or follows a destination link`` () =
        withDestination (fun path ->
            let target = Path.Combine(Path.GetDirectoryName(path), "existing.db")
            File.WriteAllText(target, "synthetic existing data")
            File.CreateSymbolicLink(path, target) |> ignore
            let code, _, _ = invoke [ "init-db"; path ]
            Assert.NotEqual(0, code)
            Assert.Equal("synthetic existing data", File.ReadAllText(target))
            Assert.Equal(target, FileInfo(path).LinkTarget)
            File.Delete(path)
            File.CreateSymbolicLink(path, target + ".missing") |> ignore
            let code, _, _ = invoke [ "init-db"; path ]
            Assert.NotEqual(0, code)
            Assert.False(File.Exists(target + ".missing"))
            File.Delete(path)
            let start = ProcessStartInfo("/usr/bin/ln")
            for argument in [ "--"; target; path ] do start.ArgumentList.Add(argument)
            use link = Process.Start(start)
            link.WaitForExit()
            Assert.Equal(0, link.ExitCode)
            let code, _, _ = invoke [ "init-db"; path ]
            Assert.NotEqual(0, code)
            Assert.Equal("synthetic existing data", File.ReadAllText(path))
            Assert.Equal("synthetic existing data", File.ReadAllText(target)))

    [<Fact>]
    let ``initializer rejects missing parent and invalid argument counts`` () =
        withDestination (fun path ->
            let missing = Path.Combine(Path.GetDirectoryName(path), "missing", "game.db")
            for args in [ [ "init-db" ]; [ "init-db"; path; "extra" ]; [ "init-db"; missing ] ] do
                let code, _, _ = invoke args
                Assert.NotEqual(0, code)
            Assert.Empty(Directory.GetFileSystemEntries(Path.GetDirectoryName(path))))

    [<Fact>]
    let ``failed initialization does not publish a partial destination`` () =
        withDestination (fun path ->
            let code, output, error = invokeWithLimit true [ "init-db"; path ]
            Assert.DoesNotContain("Failed to create CoreCLR", output + error)
            Assert.NotEqual(0, code)
            Assert.False(File.Exists(path)))

    [<Fact>]
    let ``initializer requires an explicit absolute destination`` () =
        withDestination (fun path ->
            let relative = Path.GetRelativePath(Environment.CurrentDirectory, path)
            let code, _, _ = invoke [ "init-db"; relative ]
            Assert.NotEqual(0, code)
            Assert.False(File.Exists(path)))

    [<Fact>]
    let ``initialization refuses linked parent paths even when their target is private`` () =
        withDestination (fun path ->
            let root = Path.GetDirectoryName(path)
            let target = Path.Combine(root, "real")
            Directory.CreateDirectory(target, privateDirectory) |> ignore
            let link = Path.Combine(root, "linked")
            Directory.CreateSymbolicLink(link, target) |> ignore
            let code, _, _ = invoke [ "init-db"; Path.Combine(link, "game.db") ]
            Assert.NotEqual(0, code)
            Assert.Empty(Directory.GetFileSystemEntries(target)))

    [<Fact>]
    let ``initialization rejects a private directory under an unprotected writable ancestor`` () =
        withDestination (fun path ->
            let root = Path.GetDirectoryName(path)
            File.SetUnixFileMode(root, privateDirectory ||| UnixFileMode.OtherWrite ||| UnixFileMode.OtherExecute)
            let data = Path.Combine(root, "data")
            Directory.CreateDirectory(data, privateDirectory) |> ignore
            let code, _, _ = invoke [ "init-db"; Path.Combine(data, "game.db") ]
            Assert.NotEqual(0, code)
            Assert.Empty(Directory.GetFileSystemEntries(data)))

    [<Fact>]
    let ``initialization rejects a non private destination directory without creating files`` () =
        withDestination (fun path ->
            let directory = Path.GetDirectoryName(path)
            File.SetUnixFileMode(directory, privateDirectory ||| UnixFileMode.GroupRead ||| UnixFileMode.GroupExecute)
            let code, _, _ = invoke [ "init-db"; path ]
            Assert.NotEqual(0, code)
            Assert.Empty(Directory.GetFileSystemEntries(directory)))

    [<Theory>]
    [<InlineData("-wal")>]
    [<InlineData("-shm")>]
    [<InlineData("-journal")>]
    let ``initialization rejects existing sidecars without touching them`` suffix =
        withDestination (fun path ->
            let existing = path + suffix
            File.WriteAllText(existing, "synthetic existing sidecar")
            let before = File.ReadAllBytes(existing)
            let code, _, _ = invoke [ "init-db"; path ]
            Assert.NotEqual(0, code)
            Assert.False(File.Exists(path))
            Assert.Equal<byte>(before, File.ReadAllBytes(existing)))

    let withProduction path action =
        let names = [ "ASPNETCORE_ENVIRONMENT"; "DOTNET_ENVIRONMENT"; "DATABASE_PATH" ]
        let previous = names |> List.map Environment.GetEnvironmentVariable
        try
            Environment.SetEnvironmentVariable("ASPNETCORE_ENVIRONMENT", "Production")
            Environment.SetEnvironmentVariable("DOTNET_ENVIRONMENT", "Production")
            Environment.SetEnvironmentVariable("DATABASE_PATH", path)
            action ()
        finally
            List.zip names previous |> List.iter (fun (name, value) -> Environment.SetEnvironmentVariable(name, value))

    [<Theory>]
    [<InlineData("DROP TABLE matches")>]
    [<InlineData("DELETE FROM SchemaVersions WHERE SchemaVersionID = 2")>]
    [<InlineData("ALTER TABLE users ADD COLUMN unexpected TEXT")>]
    let ``initialization marker never bypasses schema or journal validation`` mutation =
        withDestination (fun path ->
            let code, output, error = invoke [ "init-db"; path ]
            Assert.True((code = 0), output + error)
            do
                use connection = new SqliteConnection($"Data Source={path};Pooling=False")
                connection.Open()
                SyntheticDatabase.execute connection mutation
            let before = File.ReadAllBytes(path)
            withProduction path (fun () ->
                Assert.ThrowsAny<Exception>(fun () -> Database.runMigrations ()) |> ignore)
            Assert.Equal<byte>(before, File.ReadAllBytes(path)))

    [<Fact>]
    let ``explicitly initialized empty storage accepts the first production identity and preserves it on restart`` () =
        withDestination (fun path ->
            let code, output, error = invoke [ "init-db"; path ]
            Assert.True((code = 0), output + error)
            withProduction path (fun () ->
                Database.runMigrations ()
                Assert.Empty(Database.getLeaderboard 0 20)
                let user = Database.createAnonymousUser ()
                Assert.Equal(Some user, Database.getUserByToken user.AnonymousId)
                Database.updateUsername user.Id "Fresh_Player" |> ignore
                Database.runMigrations ()
                let returning = Database.getUserByToken user.AnonymousId |> Option.get
                Assert.Equal(user.Id, returning.Id)
                Assert.Equal("Fresh_Player", returning.Username)
                let before = File.ReadAllBytes(path)
                let code, _, _ = invoke [ "init-db"; path ]
                Assert.NotEqual(0, code)
                Assert.Equal<byte>(before, File.ReadAllBytes(path))
                Assert.Equal(Some returning, Database.getUserByToken user.AnonymousId)))

    [<Fact>]
    let ``offline initialization creates an empty migrated database without starting the server`` () =
        withDestination (fun path ->
            let code, output, error = invoke [ "init-db"; path ]
            Assert.True((code = 0), output + error)
            Assert.DoesNotContain("Application started", output)
            Assert.True(File.Exists(path))
            Assert.Equal(UnixFileMode.UserRead ||| UnixFileMode.UserWrite, File.GetUnixFileMode(path))
            Assert.Equal<string>([| path |], Directory.GetFileSystemEntries(Path.GetDirectoryName(path)))
            use connection = new SqliteConnection($"Data Source={path};Mode=ReadOnly;Pooling=False")
            connection.Open()
            use command = connection.CreateCommand()
            command.CommandText <- "SELECT (SELECT count(*) FROM users), (SELECT count(*) FROM matches), (SELECT count(*) FROM SchemaVersions)"
            use rows = command.ExecuteReader()
            Assert.True(rows.Read())
            Assert.Equal(0L, rows.GetInt64(0))
            Assert.Equal(0L, rows.GetInt64(1))
            Assert.Equal(2L, rows.GetInt64(2)))
