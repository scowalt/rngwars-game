namespace RNGWars.Api.Tests

open System
open System.IO
open System.Net
open System.Net.Http
open System.Text.Json
open System.Threading
open System.Threading.Tasks
open Giraffe
open Microsoft.AspNetCore.Http
open Microsoft.AspNetCore.WebUtilities
open Microsoft.Data.Sqlite
open Microsoft.Extensions.DependencyInjection
open Microsoft.Extensions.Primitives
open RNGWars
open Xunit

type private SyntheticProvider(respond: HttpRequestMessage -> HttpResponseMessage) =
    inherit HttpMessageHandler()

    override _.SendAsync(request: HttpRequestMessage, _cancellationToken: CancellationToken) =
        Task.FromResult(respond request)

type private SyntheticClock() =
    inherit TimeProvider()
    member val Now = DateTimeOffset(2026, 11, 7, 12, 0, 0, TimeSpan.Zero) with get, set
    override this.GetUtcNow() = this.Now

type private Reply =
    { Status: int
      Location: string
      SetCookie: string list
      Body: string }

    member this.Json = JsonDocument.Parse(this.Body).RootElement

    member this.Cookie = this.SetCookie |> List.head |> fun header -> header.Split(';')[0]

type private Server(respond: HttpRequestMessage -> HttpResponseMessage) =
    let providerRequests = ResizeArray<string>()
    let locations = ResizeArray<string>()
    let clock = SyntheticClock()

    let record (request: HttpRequestMessage) =
        let body = if isNull request.Content then "" else request.Content.ReadAsStringAsync().Result
        lock providerRequests (fun () -> providerRequests.Add(request.RequestUri.AbsoluteUri + " " + body))
        respond request

    let services =
        let collection = ServiceCollection().AddGiraffe()
        collection.AddSingleton<TimeProvider>(clock) |> ignore
        collection.ConfigureHttpClientDefaults(fun builder ->
            builder.ConfigurePrimaryHttpMessageHandler(fun () -> new SyntheticProvider(record) :> HttpMessageHandler) |> ignore)
        |> ignore
        collection.BuildServiceProvider()

    member _.Clock = clock
    member _.ProviderRequests = List.ofSeq providerRequests
    member _.Locations = List.ofSeq locations

    member _.Send(httpMethod: string, target: string, ?cookie: string, ?bearer: string) = task {
        let context = DefaultHttpContext(RequestServices = services)
        context.Request.Method <- httpMethod
        context.Request.Scheme <- "https"
        context.Request.Host <- HostString("game.example")
        let path, query =
            match target.IndexOf('?') with
            | -1 -> target, ""
            | index -> target.Substring(0, index), target.Substring(index)
        context.Request.Path <- PathString(path)
        context.Request.QueryString <- QueryString(query)
        cookie |> Option.iter (fun value -> context.Request.Headers.Cookie <- StringValues(value))
        bearer |> Option.iter (fun value -> context.Request.Headers.Authorization <- StringValues("Bearer " + value))
        use body = new MemoryStream()
        context.Response.Body <- body
        let! _ = Routes.webApp (fun handled -> Task.FromResult(Some handled)) context
        body.Position <- 0L
        use reader = new StreamReader(body)
        let location = context.Response.Headers.Location.ToString()
        if location <> "" then locations.Add(location)
        return
            { Status = context.Response.StatusCode
              Location = location
              SetCookie = context.Response.Headers.SetCookie |> Seq.toList
              Body = reader.ReadToEnd() }
    }

    member this.Start(?bearer: string) = task {
        let! reply =
            match bearer with
            | Some token -> this.Send("POST", "/auth/github", bearer = token)
            | None -> this.Send("POST", "/auth/github")
        Assert.Equal(200, reply.Status)
        let authorizeUrl = reply.Json.GetProperty("url").GetString()
        let query = QueryHelpers.ParseQuery(Uri(authorizeUrl).Query)
        let state = query["state"].ToString()
        return reply, authorizeUrl, state
    }

    member this.Callback(state: string, ?cookie: string, ?provider: string) =
        let target = sprintf "/auth/%s/callback?code=synthetic-code&state=%s" (defaultArg provider "github") (Uri.EscapeDataString state)
        match cookie with
        | Some value -> this.Send("GET", target, cookie = value)
        | None -> this.Send("GET", target)

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

    let users path =
        use connection = new SqliteConnection($"Data Source={path};Pooling=False")
        connection.Open()
        use command = connection.CreateCommand()
        command.CommandText <- "SELECT COUNT(*) FROM users"
        Convert.ToInt64(command.ExecuteScalar())

[<Collection("Database environment")>]
type OAuthCallbackRouteTests() =
    let withConfiguredGithub (action: string -> Task<unit>) =
        SyntheticDatabase.withDatabase "Development" (fun path ->
            Database.runMigrations ()
            let previous = Environment.GetEnvironmentVariable("GITHUB_CLIENT_ID")
            Environment.SetEnvironmentVariable("GITHUB_CLIENT_ID", "synthetic-client")
            try
                (action path).GetAwaiter().GetResult()
            finally
                Environment.SetEnvironmentVariable("GITHUB_CLIENT_ID", previous))

    let assertFailureRedirect (reply: Reply) =
        for sensitive in [ "synthetic-secret-detail"; "SQLite"; "INSERT"; "anonymous_id"; "Exception"; "StackTrace" ] do
            Assert.DoesNotContain(sensitive, reply.Body)
            Assert.DoesNotContain(sensitive, reply.Location)
        Assert.Equal(302, reply.Status)
        Assert.Equal("/?auth_error=OAUTH_ERROR", reply.Location)

    let assertRejectedBeforeProvider path (server: Server) (reply: Reply) =
        assertFailureRedirect reply
        Assert.Empty(server.ProviderRequests)
        Assert.Equal(0L, OAuthHarness.users path)

    let assertNeverInUrls (server: Server) (authorizeUrl: string) (token: string) =
        Assert.DoesNotContain(token, authorizeUrl)
        Assert.NotEmpty(server.Locations)
        for location in server.Locations do
            Assert.DoesNotContain(token, location)
        Assert.NotEmpty(server.ProviderRequests)
        for request in server.ProviderRequests do
            Assert.DoesNotContain(token, request)

    [<Fact>]
    let ``start binds a random state to an HttpOnly cookie and keeps the token out of the provider URL`` () =
        withConfiguredGithub (fun _ ->
            task {
                let server = Server(OAuthHarness.githubAccount)
                let anonymous = Database.createAnonymousUser ()
                let! reply, authorizeUrl, state = server.Start(bearer = anonymous.AnonymousId)
                Assert.StartsWith("https://github.com/login/oauth/authorize?", authorizeUrl)
                Assert.DoesNotContain(anonymous.AnonymousId, authorizeUrl)
                Assert.True(state.Length >= 32, "state carries at least 32 characters of entropy")
                let cookie = reply.SetCookie |> List.exactlyOne
                Assert.DoesNotContain(anonymous.AnonymousId, cookie)
                Assert.DoesNotContain(state, cookie)
                for attribute in [ "httponly"; "secure"; "samesite=lax"; "path=/" ] do
                    Assert.Contains(attribute, cookie.ToLowerInvariant())
                let! _, _, otherState = server.Start()
                Assert.NotEqual<string>(state, otherState)
            })

    [<Fact>]
    let ``linking an anonymous account hands over its token without putting it in a URL`` () =
        withConfiguredGithub (fun _ ->
            task {
                let server = Server(OAuthHarness.githubAccount)
                let anonymous = Database.createAnonymousUser ()
                let! started, authorizeUrl, state = server.Start(bearer = anonymous.AnonymousId)
                let! callback = server.Callback(state, cookie = started.Cookie)
                Assert.Equal(302, callback.Status)
                Assert.Equal("/auth/success", callback.Location)
                let! session = server.Send("POST", "/auth/session", cookie = started.Cookie)
                Assert.Equal(200, session.Status)
                Assert.Equal(anonymous.AnonymousId, session.Json.GetProperty("token").GetString())
                Assert.Equal(anonymous.Id, session.Json.GetProperty("user").GetProperty("id").GetString())
                let linked = Database.getUserById anonymous.Id |> Option.get
                Assert.Equal(Some "github", linked.AuthProvider)
                Assert.Equal(Some "4242", linked.AuthId)
                Assert.False(linked.IsAnonymous)
                assertNeverInUrls server authorizeUrl anonymous.AnonymousId
            })

    [<Fact>]
    let ``signing in to an existing account merges the anonymous account into it`` () =
        withConfiguredGithub (fun _ ->
            task {
                let server = Server(OAuthHarness.githubAccount)
                let existing = Database.createAnonymousUser ()
                Database.linkAnonymousToAuth existing.Id "github" "4242" None None None |> ignore
                let anonymous = Database.createAnonymousUser ()
                let! started, authorizeUrl, state = server.Start(bearer = anonymous.AnonymousId)
                let! callback = server.Callback(state, cookie = started.Cookie)
                Assert.Equal("/auth/success", callback.Location)
                let! session = server.Send("POST", "/auth/session", cookie = started.Cookie)
                Assert.Equal(existing.AnonymousId, session.Json.GetProperty("token").GetString())
                Assert.Equal(None, Database.getUserById anonymous.Id)
                assertNeverInUrls server authorizeUrl anonymous.AnonymousId
            })

    [<Fact>]
    let ``signing in without an anonymous account creates a linked user`` () =
        withConfiguredGithub (fun path ->
            task {
                let server = Server(OAuthHarness.githubAccount)
                let! started, _, state = server.Start()
                let! callback = server.Callback(state, cookie = started.Cookie)
                Assert.Equal("/auth/success", callback.Location)
                let! session = server.Send("POST", "/auth/session", cookie = started.Cookie)
                let user = Database.getUserByToken (session.Json.GetProperty("token").GetString()) |> Option.get
                Assert.Equal(Some "4242", user.AuthId)
                Assert.False(user.IsAnonymous)
                Assert.Equal(1L, OAuthHarness.users path)
            })

    [<Fact>]
    let ``callback from a browser that never started the flow is rejected before contacting the provider`` () =
        withConfiguredGithub (fun path ->
            task {
                let server = Server(OAuthHarness.githubAccount)
                let! guessed = server.Callback(Guid.NewGuid().ToString())
                assertRejectedBeforeProvider path server guessed
                let! _, _, attackerState = server.Start()
                let! forged = server.Callback(attackerState)
                assertRejectedBeforeProvider path server forged
            })

    [<Fact>]
    let ``callback carrying another flow's state is rejected before contacting the provider`` () =
        withConfiguredGithub (fun path ->
            task {
                let server = Server(OAuthHarness.githubAccount)
                let! victimStart, _, _ = server.Start()
                let! _, _, attackerState = server.Start()
                let! mismatched = server.Callback(attackerState, cookie = victimStart.Cookie)
                assertRejectedBeforeProvider path server mismatched
                let! missing = server.Send("GET", "/auth/github/callback?code=synthetic-code", cookie = victimStart.Cookie)
                assertRejectedBeforeProvider path server missing
            })

    [<Fact>]
    let ``callback for a different provider than the flow started with is rejected`` () =
        withConfiguredGithub (fun path ->
            task {
                let server = Server(OAuthHarness.githubAccount)
                let! started, _, state = server.Start()
                let! crossed = server.Callback(state, cookie = started.Cookie, provider = "google")
                assertRejectedBeforeProvider path server crossed
            })

    [<Fact>]
    let ``replayed callback is rejected before contacting the provider`` () =
        withConfiguredGithub (fun path ->
            task {
                let server = Server(OAuthHarness.githubAccount)
                let! started, _, state = server.Start()
                let! first = server.Callback(state, cookie = started.Cookie)
                Assert.Equal("/auth/success", first.Location)
                let providerRequests = server.ProviderRequests.Length
                let! replayed = server.Callback(state, cookie = started.Cookie)
                assertFailureRedirect replayed
                Assert.Equal(providerRequests, server.ProviderRequests.Length)
                Assert.Equal(1L, OAuthHarness.users path)
            })

    [<Fact>]
    let ``expired state is rejected before contacting the provider`` () =
        withConfiguredGithub (fun path ->
            task {
                let server = Server(OAuthHarness.githubAccount)
                let! started, _, state = server.Start()
                server.Clock.Now <- server.Clock.Now.AddMinutes(11.0)
                let! expired = server.Callback(state, cookie = started.Cookie)
                assertRejectedBeforeProvider path server expired
            })

    [<Fact>]
    let ``session hand-off works once and only after a completed callback`` () =
        withConfiguredGithub (fun _ ->
            task {
                let server = Server(OAuthHarness.githubAccount)
                let! started, _, state = server.Start()
                let! early = server.Send("POST", "/auth/session", cookie = started.Cookie)
                Assert.Equal(401, early.Status)
                let! _ = server.Callback(state, cookie = started.Cookie)
                let! anonymous = server.Send("POST", "/auth/session")
                Assert.Equal(401, anonymous.Status)
                let! first = server.Send("POST", "/auth/session", cookie = started.Cookie)
                Assert.Equal(200, first.Status)
                let! second = server.Send("POST", "/auth/session", cookie = started.Cookie)
                Assert.Equal(401, second.Status)
                Assert.DoesNotContain(first.Json.GetProperty("token").GetString(), second.Body)
            })

    [<Fact>]
    let ``unreachable provider redirects with a stable code and no exception text`` () =
        withConfiguredGithub (fun path ->
            task {
                let server = Server(OAuthHarness.unreachable)
                let! started, _, state = server.Start()
                let! reply = server.Callback(state, cookie = started.Cookie)
                assertFailureRedirect reply
                Assert.DoesNotContain(path, reply.Body)
                Assert.Equal(0L, OAuthHarness.users path)
            })

    [<Fact>]
    let ``rejected account link redirects with a stable code and no database text`` () =
        withConfiguredGithub (fun path ->
            use connection = new SqliteConnection($"Data Source={path};Pooling=False")
            connection.Open()
            SyntheticDatabase.execute connection "CREATE TRIGGER synthetic_reject BEFORE INSERT ON users BEGIN SELECT RAISE(ABORT, 'synthetic-secret-detail'); END"
            connection.Close()
            task {
                let server = Server(OAuthHarness.githubAccount)
                let! started, _, state = server.Start()
                let! reply = server.Callback(state, cookie = started.Cookie)
                assertFailureRedirect reply
                Assert.DoesNotContain(path, reply.Body)
                Assert.Equal(0L, OAuthHarness.users path)
            })
