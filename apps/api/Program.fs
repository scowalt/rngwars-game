namespace RNGWars

open System.IO
open Microsoft.AspNetCore.Builder
open Microsoft.AspNetCore.Hosting
open Microsoft.AspNetCore.SignalR
open Microsoft.Extensions.DependencyInjection
open Microsoft.Extensions.FileProviders
open Microsoft.Extensions.Hosting
open Giraffe

module Program =

    let private setupMatchEvents (hubContext: IHubContext<GameHub>) =
        MatchManager.setEventHandler (fun event ->
            match event with
            | MatchAgent.PhaseChangedEvent(matchId, phase, data) ->
                match phase with
                | "revealed" ->
                    let groupName = sprintf "match:%s" matchId
                    let p1Roll = data["playerRoll"] :?> float
                    let p2Roll = data["opponentRoll"] :?> float
                    let timeRemaining = data["timeRemaining"] :?> int

                    let player1Id =
                        match MatchManager.getAgent matchId with
                        | Some agent -> agent.Player1Id
                        | None -> ""

                    hubContext.Clients.Group(groupName).SendAsync("PhaseChanged",
                        {| phase = "revealed"; timeRemaining = timeRemaining
                           player1Id = player1Id; player1Roll = p1Roll; player2Roll = p2Roll |})
                    |> ignore

                | "countdown" ->
                    let groupName = sprintf "match:%s" matchId
                    let count = data["count"] :?> int
                    let timeRemaining = data["timeRemaining"] :?> int
                    hubContext.Clients.Group(groupName).SendAsync("PhaseChanged",
                        {| phase = "countdown"; timeRemaining = timeRemaining; count = count |})
                    |> ignore

                | _ ->
                    let groupName = sprintf "match:%s" matchId
                    let timeRemaining = data["timeRemaining"] :?> int
                    hubContext.Clients.Group(groupName).SendAsync("PhaseChanged",
                        {| phase = phase; timeRemaining = timeRemaining |})
                    |> ignore

            | MatchAgent.MatchCompletedEvent(matchId, winnerId, player1Id, _player2Id, eloChanges) ->
                let groupName = sprintf "match:%s" matchId
                let p1EloChange, p1NewElo, p2EloChange, p2NewElo =
                    match eloChanges with
                    | Some(p1Before, p1After, p2Before, p2After) ->
                        (p1After - p1Before, p1After, p2After - p2Before, p2After)
                    | None -> (0, 0, 0, 0)

                hubContext.Clients.Group(groupName).SendAsync("MatchCompleted",
                    {| winnerId = winnerId
                       player1Id = player1Id
                       player1EloChange = p1EloChange
                       player1NewElo = p1NewElo
                       player2EloChange = p2EloChange
                       player2NewElo = p2NewElo |})
                |> ignore

            | MatchAgent.MatchCancelledEvent(matchId, code, message) ->
                let groupName = sprintf "match:%s" matchId
                hubContext.Clients.Group(groupName).SendAsync("MatchCancelled",
                    {| error = {| code = code; message = message |} |})
                |> ignore
        )

    let private setupMatchmaking (hubContext: IHubContext<GameHub>) =
        MatchmakingQueue.setPairedHandler (fun p1Id p1ConnId p2Id p2ConnId ->
            match MatchManager.createMultiplayerMatch p1Id p2Id with
            | Ok matchId ->
                let payload = {| matchId = matchId; opponentName = "" |}

                let p1Name =
                    match Database.getUserById p2Id with
                    | Some u -> u.Username
                    | None -> "Unknown"

                let p2Name =
                    match Database.getUserById p1Id with
                    | Some u -> u.Username
                    | None -> "Unknown"

                hubContext.Clients.Client(p1ConnId).SendAsync("MatchFound",
                    {| matchId = matchId; opponentName = p1Name |}) |> ignore
                hubContext.Clients.Client(p2ConnId).SendAsync("MatchFound",
                    {| matchId = matchId; opponentName = p2Name |}) |> ignore
            | Error _ -> ()
        )

    let private runWeb (args: string array) =
        let builder = WebApplication.CreateBuilder(args)
        Database.runMigrationsForEnvironment builder.Environment.EnvironmentName

        builder.WebHost.UseSentry(fun (o: Sentry.AspNetCore.SentryAspNetCoreOptions) ->
            o.Dsn <- System.Environment.GetEnvironmentVariable("SENTRY_DSN") |> Option.ofObj |> Option.defaultValue ""
            o.TracesSampleRate <- 0.0  
            o.DisableSentryHttpMessageHandler <- true
        ) |> ignore

        builder.Services.AddGiraffe() |> ignore
        builder.Services.AddHttpClient() |> ignore
        builder.Services.AddSingleton(System.TimeProvider.System) |> ignore

        builder.Services.AddCors(fun options ->
            options.AddDefaultPolicy(fun policy ->
                policy
                    .WithOrigins("http://localhost:5173", "http://localhost:3000", "https://play.rngwars.com")
                    .AllowAnyHeader()
                    .AllowAnyMethod()
                    .AllowCredentials()
                |> ignore))
        |> ignore

        builder.Services.AddSignalR() |> ignore

        let app = builder.Build()

        let hubContext = app.Services.GetRequiredService<IHubContext<GameHub>>()
        setupMatchEvents hubContext
        setupMatchmaking hubContext

        MatchManager.startCleanup ()

        app.UseCors() |> ignore
        app.UseRouting() |> ignore

        app.UseEndpoints(fun endpoints ->
            endpoints.MapHub<GameHub>("/hubs/game") |> ignore
        ) |> ignore

        let wwwroot = Path.Combine(Directory.GetCurrentDirectory(), "wwwroot")
        if Directory.Exists(wwwroot) then
            app.UseStaticFiles() |> ignore

        let spaFallback : HttpHandler =
            if Directory.Exists(wwwroot) then
                htmlFile (Path.Combine(wwwroot, "index.html"))
            else
                RequestErrors.NOT_FOUND "Not Found"

        app.UseGiraffe(
            choose [
                Routes.webApp
                GET >=> spaFallback
            ])

        app.Run()
        0

    [<EntryPoint>]
    let main args =
        match args with
        | [| "init-db"; path |] ->
            try
                DatabaseInitialization.initialize path
                System.Console.WriteLine("Database initialized")
                0
            with _ ->
                System.Console.Error.WriteLine("Database initialization failed; no existing database was replaced")
                1
        | values when values.Length > 0 && values[0] = "init-db" ->
            System.Console.Error.WriteLine("Usage: init-db <absolute-path>")
            64
        | _ -> runWeb args
