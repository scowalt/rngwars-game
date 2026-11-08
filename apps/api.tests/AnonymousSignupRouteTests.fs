namespace RNGWars.Api.Tests

open System
open System.IO
open System.Text.Json
open System.Threading.Tasks
open Giraffe
open Microsoft.AspNetCore.Http
open Microsoft.Data.Sqlite
open Microsoft.Extensions.DependencyInjection
open Microsoft.Extensions.Primitives
open RNGWars
open Xunit

module private RouteHarness =
    let private services = ServiceCollection().AddGiraffe().BuildServiceProvider()

    let send (httpMethod: string) (path: string) (token: string option) = task {
        let context = DefaultHttpContext(RequestServices = services)
        context.Request.Method <- httpMethod
        context.Request.Path <- PathString(path)
        token |> Option.iter (fun value -> context.Request.Headers.Authorization <- StringValues("Bearer " + value))
        use body = new MemoryStream()
        context.Response.Body <- body
        let! _ = Routes.webApp (fun handled -> Task.FromResult(Some handled)) context
        body.Position <- 0L
        use reader = new StreamReader(body)
        return context.Response.StatusCode, reader.ReadToEnd()
    }

    let offThread (work: unit -> Task<int * string>) : Task<int * string> = Task.Factory.StartNew(Func<Task<int * string>>(work)).Unwrap()

    let signup () = send "POST" "/api/users/anonymous" None

    let sql path statements =
        use connection = new SqliteConnection($"Data Source={path};Pooling=False")
        connection.Open()
        SyntheticDatabase.execute connection statements

    let scalar path query =
        use connection = new SqliteConnection($"Data Source={path};Pooling=False")
        connection.Open()
        use command = connection.CreateCommand()
        command.CommandText <- query
        Convert.ToInt64(command.ExecuteScalar())

[<Collection("Database environment")>]
type AnonymousSignupRouteTests() =
    let withMigratedDatabase action =
        SyntheticDatabase.withDatabase "Development" (fun path ->
            Database.runMigrations ()
            action path)

    let parse (text: string) = JsonDocument.Parse(text).RootElement

    [<Fact>]
    let ``signup issues a token that authenticates the same persisted user`` () =
        withMigratedDatabase (fun path ->
            task {
                let! status, text = RouteHarness.signup ()
                Assert.Equal(201, status)
                let created = parse text
                let token = created.GetProperty("token").GetString()
                let id = created.GetProperty("user").GetProperty("id").GetString()
                let! meStatus, meText = RouteHarness.send "GET" "/api/users/me" (Some token)
                Assert.Equal(200, meStatus)
                Assert.Equal(id, (parse meText).GetProperty("id").GetString())
                let stored = Database.getUserByToken token |> Option.get
                Assert.Equal(id, stored.Id)
                Assert.Equal(token, stored.AnonymousId)
                Assert.Equal(1L, RouteHarness.scalar path "SELECT COUNT(*) FROM users")
            }
            |> fun work -> work.GetAwaiter().GetResult())

    [<Fact>]
    let ``concurrent signups issue distinct identities with usable tokens`` () =
        withMigratedDatabase (fun path ->
            task {
                let count = 32
                let! signups = Task.WhenAll [| for _ in 1..count -> RouteHarness.offThread RouteHarness.signup |]
                let created =
                    signups
                    |> Array.map (fun (status, text) ->
                        Assert.Equal(201, status)
                        let body = parse text
                        body.GetProperty("token").GetString(), body.GetProperty("user").GetProperty("id").GetString())
                Assert.Equal(count, created |> Array.map fst |> Array.distinct |> Array.length)
                Assert.Equal(count, created |> Array.map snd |> Array.distinct |> Array.length)
                let! lookups =
                    Task.WhenAll [| for token, _ in created -> RouteHarness.offThread (fun () -> RouteHarness.send "GET" "/api/users/me" (Some token)) |]
                Array.zip created lookups
                |> Array.iter (fun ((_, id), (status, text)) ->
                    Assert.Equal(200, status)
                    Assert.Equal(id, (parse text).GetProperty("id").GetString()))
                Assert.Equal(int64 count, RouteHarness.scalar path "SELECT COUNT(*) FROM users")
            }
            |> fun work -> work.GetAwaiter().GetResult())

    [<Theory>]
    [<InlineData("insert is rejected", "CREATE TRIGGER synthetic_reject BEFORE INSERT ON users BEGIN SELECT RAISE(ABORT, 'synthetic-secret-detail'); END")>]
    [<InlineData("row is gone before it is read", "CREATE TABLE synthetic_attempts (id TEXT); CREATE TRIGGER synthetic_attempt AFTER INSERT ON users BEGIN INSERT INTO synthetic_attempts VALUES (NEW.id); DELETE FROM users WHERE id = NEW.id; END")>]
    let ``failed or unconfirmed creation returns a structured failure without a token`` (_scenario: string, fault: string) =
        withMigratedDatabase (fun path ->
            RouteHarness.sql path fault
            task {
                let! status, text = RouteHarness.signup ()
                Assert.Equal(500, status)
                let body = parse text
                Assert.Equal("SIGNUP_FAILED", body.GetProperty("error").GetProperty("code").GetString())
                Assert.False(body.TryGetProperty("token") |> fst)
                Assert.False(body.TryGetProperty("user") |> fst)
                for sensitive in [ "synthetic-secret-detail"; path; "SQLite"; "StackTrace" ] do
                    Assert.DoesNotContain(sensitive, text)
                Assert.Equal(0L, RouteHarness.scalar path "SELECT COUNT(*) FROM users")
                if fault.Contains("synthetic_attempts") then
                    Assert.Equal(1L, RouteHarness.scalar path "SELECT COUNT(*) FROM synthetic_attempts")
            }
            |> fun work -> work.GetAwaiter().GetResult())

    [<Fact>]
    let ``signup against storage that disappeared fails without recreating it`` () =
        withMigratedDatabase (fun path ->
            File.Delete(path)
            task {
                let! status, text = RouteHarness.signup ()
                Assert.Equal(500, status)
                Assert.Equal("SIGNUP_FAILED", (parse text).GetProperty("error").GetProperty("code").GetString())
                Assert.DoesNotContain(path, text)
                Assert.False(File.Exists(path))
            }
            |> fun work -> work.GetAwaiter().GetResult())
