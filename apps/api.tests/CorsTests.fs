namespace RNGWars.Api.Tests

open Microsoft.AspNetCore.Cors.Infrastructure
open Microsoft.AspNetCore.Http
open Microsoft.Extensions.DependencyInjection
open RNGWars
open Xunit

module private CorsHarness =
    let allowOrigin (isDevelopment: bool) (preflight: bool) (origin: string) = task {
        let services = ServiceCollection().AddLogging().AddCors(CorsConfig.configure isDevelopment)
        use provider = services.BuildServiceProvider()
        let context = DefaultHttpContext(RequestServices = provider)
        context.Request.Method <- if preflight then "OPTIONS" else "GET"
        context.Request.Headers["Origin"] <- origin
        if preflight then
            context.Request.Headers["Access-Control-Request-Method"] <- "POST"
        let policies = provider.GetRequiredService<ICorsPolicyProvider>()
        let service = provider.GetRequiredService<ICorsService>()
        let! policy = policies.GetPolicyAsync(context, null)
        service.ApplyResult(service.EvaluatePolicy(context, policy), context.Response)
        return
            match context.Response.Headers.TryGetValue "Access-Control-Allow-Origin" with
            | true, value -> Some(value.ToString())
            | _ -> None
    }

type CorsTests() =
    static member LocalhostOrigins : obj[] seq =
        seq {
            for origin in [ "http://localhost:5173"; "http://localhost:3000" ] do
                for preflight in [ false; true ] do
                    yield [| origin; preflight |]
        }

    [<Theory>]
    [<MemberData(nameof CorsTests.LocalhostOrigins)>]
    member _.``production sends no allow-origin header to a localhost origin`` (origin: string, preflight: bool) = task {
        let! header = CorsHarness.allowOrigin false preflight origin
        Assert.Equal(None, header)
    }

    [<Theory>]
    [<InlineData(false)>]
    [<InlineData(true)>]
    member _.``production origin is allowed with credentials, including on preflight`` (preflight: bool) = task {
        let! header = CorsHarness.allowOrigin false preflight "https://play.rngwars.com"
        Assert.Equal(Some "https://play.rngwars.com", header)
    }

    [<Theory>]
    [<MemberData(nameof CorsTests.LocalhostOrigins)>]
    member _.``development still allows localhost origins`` (origin: string, preflight: bool) = task {
        let! header = CorsHarness.allowOrigin true preflight origin
        Assert.Equal(Some origin, header)
    }
