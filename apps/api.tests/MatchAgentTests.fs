module RNGWars.Tests.MatchAgentTests

open System.Collections.Concurrent
open Xunit
open RNGWars

let private phaseEvents (events: ConcurrentQueue<MatchAgent.MatchEvent>) =
    events
    |> Seq.choose (function
        | MatchAgent.PhaseChangedEvent(_, phase, _) -> Some phase
        | _ -> None)
    |> List.ofSeq

[<Theory>]
[<InlineData("player-1", "player-2")>]
[<InlineData("player-2", "player-1")>]
let ``Multiplayer match starts countdown once both players join`` (firstJoiner: string) (secondJoiner: string) =
    let events = ConcurrentQueue<MatchAgent.MatchEvent>()
    let agent = MatchAgent.Agent("match-1", "player-1", Some "player-2", false, None, events.Enqueue)

    try
        let afterFirst = agent.PostPlayerJoined(firstJoiner) |> Async.RunSynchronously
        Assert.Equal(MatchAgent.Connecting, afterFirst.Phase)
        Assert.Empty(phaseEvents events)

        let afterSecond = agent.PostPlayerJoined(secondJoiner) |> Async.RunSynchronously
        Assert.Equal(MatchAgent.Countdown 3, afterSecond.Phase)
        Assert.Equal<string list>([ "countdown" ], phaseEvents events)
    finally
        agent.Shutdown()

[<Fact>]
let ``Practice match starts countdown when the player joins`` () =
    let events = ConcurrentQueue<MatchAgent.MatchEvent>()
    let agent = MatchAgent.Agent("match-2", "player-1", None, true, Some "RoboRNG", events.Enqueue)

    try
        let state = agent.PostPlayerJoined("player-1") |> Async.RunSynchronously
        Assert.Equal(MatchAgent.Countdown 3, state.Phase)
        Assert.Equal<string list>([ "countdown" ], phaseEvents events)
    finally
        agent.Shutdown()
