namespace RNGWars

open System
open System.Collections.Concurrent
open System.Threading

module MatchManager =

    let private activeMatches = ConcurrentDictionary<string, MatchAgent.Agent>()
    let mutable private onMatchEvent: (MatchAgent.MatchEvent -> unit) option = None
    let private maxMatches = 500
    let mutable private cleanupTimer: Timer option = None

    let setEventHandler (handler: MatchAgent.MatchEvent -> unit) =
        onMatchEvent <- Some handler

    let private handleEvent (event: MatchAgent.MatchEvent) =
        match onMatchEvent with
        | Some handler -> handler event
        | None -> ()

        match event with
        | MatchAgent.MatchCompletedEvent(matchId, _, _, _, _)
        | MatchAgent.MatchCancelledEvent(matchId, _, _) ->
            match activeMatches.TryRemove(matchId) with
            | true, agent -> agent.Shutdown()
            | _ -> ()
        | _ -> ()

    let createPracticeMatch (playerId: string) : Result<string * string, string> =
        if activeMatches.Count >= maxMatches then
            Error "Server is at capacity. Please try again later."
        else
            let matchId = Guid.NewGuid().ToString()
            let aiName = MatchAgent.randomAiName ()

            Database.createPracticeMatch matchId playerId aiName

            let agent = MatchAgent.Agent(matchId, playerId, None, true, Some aiName, handleEvent)
            activeMatches[matchId] <- agent
            Ok(matchId, aiName)

    let createMultiplayerMatch (player1Id: string) (player2Id: string) : Result<string, string> =
        if activeMatches.Count >= maxMatches then
            Error "Server is at capacity. Please try again later."
        else
            let matchId = Guid.NewGuid().ToString()

            Database.createMultiplayerMatch matchId player1Id player2Id

            let agent = MatchAgent.Agent(matchId, player1Id, Some player2Id, false, None, handleEvent)
            activeMatches[matchId] <- agent
            Ok matchId

    let getAgent (matchId: string) : MatchAgent.Agent option =
        match activeMatches.TryGetValue(matchId) with
        | true, agent -> Some agent
        | _ -> None

    let getActiveMatchForPlayer (playerId: string) : MatchAgent.Agent option =
        activeMatches.Values
        |> Seq.tryFind (fun a ->
            a.Player1Id = playerId || a.Player2Id = Some playerId)

    let startCleanup () =
        let callback _ =
            let now = DateTime.UtcNow
            for kvp in activeMatches do
                let agent = kvp.Value
                let state = agent.GetState() |> Async.RunSynchronously
                let age = (now - state.StartedAt).TotalMinutes
                if age > 5.0 then
                    printfn "Cleaning up stale match %s (age: %.1f min)" kvp.Key age
                    agent.Shutdown()
                    activeMatches.TryRemove(kvp.Key) |> ignore

        let timer = new Timer(callback, null, TimeSpan.FromSeconds(60.0), TimeSpan.FromSeconds(60.0))
        cleanupTimer <- Some timer
