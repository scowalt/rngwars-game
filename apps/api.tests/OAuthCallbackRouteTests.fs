namespace RNGWars.Api.Tests

open System
open System.IO
open System.Net
open System.Net.Http
open System.Threading
open System.Threading.Tasks
open Giraffe
open Microsoft.AspNetCore.Http
open Microsoft.Data.Sqlite
open Microsoft.Extensions.DependencyInjection
open RNGWars
open Xunit

type private SyntheticProvider(respond: HttpRequestMessage -> HttpResponseMessage) =
    inherit HttpMessageHandler()

    override _.SendAsync(request: HttpRequestMessage, _cancellationToken: CancellationToken) =
        Task.FromResult(respond request)

module private OAuthHarness =
    let githubAccount (request: HttpRequestMessage) =
        let body =
            if request.RequestUri.AbsoluteUri = "https://github.com/login/oauth/access_token" then
                """{"access_token":"synthetic-access-token"}"""
            else
                """{"id":4242,"login":"synthetic-login"}"""

        new HttpResponseMessage(HttpStatusCode.OK, Content = new StringContent(body))

    let unreachable (_: HttpRequestMessage) : HttpResponseMessage =
        raise (HttpRequestException("synthetic-secret-detail"))

    let callback (respond: HttpRequestMessage -> HttpResponseMessage) = task {
        let services = ServiceCollection().AddGiraffe()
        services.ConfigureHttpClientDefaults(fun builder ->
            builder.ConfigurePrimaryHttpMessageHandler(fun () -> new SyntheticProvider(respond) :> HttpMessageHandler) |> ignore)
        |> ignore
        use provider = services.BuildServiceProvider()
        let context = DefaultHttpContext(RequestServices = provider)
        context.Request.Method <- "GET"
        context.Request.Scheme <- "https"
        context.Request.Host <- HostString("game.example")
        context.Request.Path <- PathString("/auth/github/callback")
        context.Request.QueryString <- QueryString("?code=synthetic-code&state=synthetic-state")
        use body = new MemoryStream()
        context.Response.Body <- body
        let! _ = Routes.webApp (fun handled -> Task.FromResult(Some handled)) context
        body.Position <- 0L
        use reader = new StreamReader(body)
        let text = reader.ReadToEnd()
        return context.Response.StatusCode, context.Response.Headers.Location.ToString(), text
    }

    let users path =
        use connection = new SqliteConnection($"Data Source={path};Pooling=False")
        connection.Open()
        use command = connection.CreateCommand()
        command.CommandText <- "SELECT COUNT(*) FROM users"
        Convert.ToInt64(command.ExecuteScalar())

[<Collection("Database environment")>]
type OAuthCallbackRouteTests() =
    let withMigratedDatabase action =
        SyntheticDatabase.withDatabase "Development" (fun path ->
            Database.runMigrations ()
            action path)

    let assertFailureRedirect path (status: int, location: string, text: string) =
        for sensitive in [ "synthetic-secret-detail"; path; "SQLite"; "INSERT"; "anonymous_id"; "Exception"; "StackTrace" ] do
            Assert.DoesNotContain(sensitive, text)
            Assert.DoesNotContain(sensitive, location)
        Assert.Equal(302, status)
        Assert.Equal("/?auth_error=OAUTH_ERROR", location)
        Assert.Equal(0L, OAuthHarness.users path)

    [<Fact>]
    let ``callback links the provider account and redirects with its token`` () =
        withMigratedDatabase (fun _ ->
            task {
                let! status, location, _ = OAuthHarness.callback OAuthHarness.githubAccount
                Assert.Equal(302, status)
                Assert.StartsWith("/auth/success?token=", location)
                let token = Uri.UnescapeDataString(location.Substring("/auth/success?token=".Length))
                let user = Database.getUserByToken token |> Option.get
                Assert.Equal(Some "github", user.AuthProvider)
                Assert.Equal(Some "4242", user.AuthId)
                Assert.False(user.IsAnonymous)
            }
            |> fun work -> work.GetAwaiter().GetResult())

    [<Fact>]
    let ``unreachable provider redirects with a stable code and no exception text`` () =
        withMigratedDatabase (fun path ->
            task {
                let! response = OAuthHarness.callback OAuthHarness.unreachable
                assertFailureRedirect path response
            }
            |> fun work -> work.GetAwaiter().GetResult())

    [<Fact>]
    let ``rejected account link redirects with a stable code and no database text`` () =
        withMigratedDatabase (fun path ->
            use connection = new SqliteConnection($"Data Source={path};Pooling=False")
            connection.Open()
            SyntheticDatabase.execute connection "CREATE TRIGGER synthetic_reject BEFORE INSERT ON users BEGIN SELECT RAISE(ABORT, 'synthetic-secret-detail'); END"
            connection.Close()
            task {
                let! response = OAuthHarness.callback OAuthHarness.githubAccount
                assertFailureRedirect path response
            }
            |> fun work -> work.GetAwaiter().GetResult())
