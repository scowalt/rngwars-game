namespace RNGWars.Api.Tests

open System
open System.IO
open System.Net
open System.Text.Json
open System.Threading.Tasks
open Giraffe
open Microsoft.AspNetCore.Builder
open Microsoft.AspNetCore.Http
open Microsoft.AspNetCore.HttpOverrides
open Microsoft.AspNetCore.WebUtilities
open Microsoft.Extensions.DependencyInjection
open Microsoft.Extensions.Logging.Abstractions
open Microsoft.Extensions.Options
open RNGWars
open Xunit

module private ProxyHarness =
    let dockerGateway = IPAddress.Parse("172.17.0.1")

    let startRedirectUri (forwardedProto: string option) = task {
        let services = ServiceCollection().AddGiraffe()
        services.AddHttpClient() |> ignore
        services.AddSingleton(TimeProvider.System) |> ignore
        use provider = services.BuildServiceProvider()
        let options = ForwardedHeadersOptions()
        ProxyHeadersConfig.configure options
        let routes =
            RequestDelegate(fun context ->
                Routes.webApp (fun handled -> Task.FromResult(Some handled)) context :> Task)
        let pipeline = ForwardedHeadersMiddleware(routes, NullLoggerFactory.Instance, Options.Create options)
        let context = DefaultHttpContext(RequestServices = provider)
        context.Connection.RemoteIpAddress <- dockerGateway
        context.Request.Method <- "POST"
        context.Request.Scheme <- "http"
        context.Request.Host <- HostString("game.example")
        context.Request.Path <- PathString("/auth/github")
        forwardedProto |> Option.iter (fun value -> context.Request.Headers["X-Forwarded-Proto"] <- value)
        use body = new MemoryStream()
        context.Response.Body <- body
        do! pipeline.Invoke(context)
        Assert.Equal(200, context.Response.StatusCode)
        let authorizeUrl = JsonDocument.Parse(body.ToArray()).RootElement.GetProperty("url").GetString()
        let query = QueryHelpers.ParseQuery(Uri(authorizeUrl).Query)
        return query["redirect_uri"].ToString()
    }

[<Collection("Database environment")>]
type ProxyHeadersRouteTests() =
    let withConfiguredGithub (action: unit -> Task<unit>) =
        SyntheticDatabase.withDatabase "Development" (fun _ ->
            Database.runMigrations ()
            let previous = Environment.GetEnvironmentVariable("GITHUB_CLIENT_ID")
            Environment.SetEnvironmentVariable("GITHUB_CLIENT_ID", "synthetic-client")
            try
                (action ()).GetAwaiter().GetResult()
            finally
                Environment.SetEnvironmentVariable("GITHUB_CLIENT_ID", previous))

    [<Fact>]
    let ``start sends an https redirect_uri when the TLS proxy forwards an https request over http`` () =
        withConfiguredGithub (fun () ->
            task {
                let! redirectUri = ProxyHarness.startRedirectUri (Some "https")
                Assert.Equal("https://game.example/auth/github/callback", redirectUri)
            })

    [<Fact>]
    let ``start keeps the connection scheme when no proxy forwards one`` () =
        withConfiguredGithub (fun () ->
            task {
                let! redirectUri = ProxyHarness.startRedirectUri None
                Assert.Equal("http://game.example/auth/github/callback", redirectUri)
            })
