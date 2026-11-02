namespace RNGWars

open System
open System.Threading

module MatchAgent =

    type MatchPhase =
        | Created
        | Connecting
        | Countdown of count: int
        | Rolling
        | Revealed
        | Completed
        | Forfeited
        | Abandoned
        | Cancelled

    type MatchState =
        { MatchId: string
          Player1Id: string
          Player2Id: string option
          Player1Connected: bool
          Player2Connected: bool
          Phase: MatchPhase
          Player1Roll: float option
          Player2Roll: float option
          WinnerId: string option
          IsPractice: bool
          AiName: string option
          StartedAt: DateTime }

    type MatchMessage =
        | PlayerJoined of playerId: string * AsyncReplyChannel<MatchState>
        | GetState of AsyncReplyChannel<MatchState>
        | PhaseTimeout
        | Shutdown

    type MatchEvent =
        | PhaseChangedEvent of matchId: string * phase: string * data: Map<string, obj>
        | MatchCompletedEvent of matchId: string * winnerId: string * player1Id: string * player2Id: string * eloChanges: (int * int * int * int) option
        | MatchCancelledEvent of matchId: string * code: string * message: string

    let private aiNames =
        [| "RoboRNG"; "DiceBot 3000"; "LuckMachine"; "ChaosEngine"
           "FortuneAI"; "RandomRex"; "BitFlipper"; "EntropyMax"
           "QuantumDice"; "NoiseMaker"; "FateComputer"; "ChanceBot" |]

    let randomAiName () =
        aiNames[Random.Shared.Next(aiNames.Length)]

    let private generateRoll () =
        Math.Round(Random.Shared.NextDouble() * 100.0, 3)

    let private determineWinner (state: MatchState) : string option =
        match state.Player1Roll, state.Player2Roll with
        | Some r1, Some r2 when r1 > r2 -> Some state.Player1Id
        | Some r1, Some r2 when r2 > r1 ->
            match state.Player2Id with
            | Some p2Id -> Some p2Id
            | None -> Some ""
        | Some _, Some _ ->
            let p1 = Database.getUserById state.Player1Id
            let p2 = state.Player2Id |> Option.bind Database.getUserById
            match p1, p2 with
            | Some u1, Some u2 ->
                if u1.RngScore <= u2.RngScore then Some state.Player1Id
                else Some u2.Id
            | _ -> Some state.Player1Id
        | _ -> None

    let private completeMatchInDb (state: MatchState) (winnerId: string) (kFactor: int) : (int * int * int * int) option =
        let player1 = Database.getUserById state.Player1Id
        let player2 = state.Player2Id |> Option.bind Database.getUserById

        match player1, player2 with
        | Some p1, Some p2 when kFactor > 0 ->
            let p1Won = winnerId = state.Player1Id
            let p1NewElo = Elo.calculate p1.RngScore p2.RngScore p1Won kFactor
            let p2NewElo = Elo.calculate p2.RngScore p1.RngScore (not p1Won) kFactor

            Database.completeMatchWithElo
                state.MatchId winnerId
                (state.Player1Roll |> Option.defaultValue 0.0)
                (state.Player2Roll |> Option.defaultValue 0.0)
                state.Player1Id p2.Id
                p1.RngScore p1NewElo p2.RngScore p2NewElo

            Some(p1.RngScore, p1NewElo, p2.RngScore, p2NewElo)
        | Some p1, None when state.IsPractice ->
            Database.completePracticeMatch
                state.MatchId winnerId
                (state.Player1Roll |> Option.defaultValue 0.0)
                (state.Player2Roll |> Option.defaultValue 0.0)
                state.Player1Id p1.RngScore

            Some(p1.RngScore, p1.RngScore, 0, 0)
        | _ -> None

    type Agent(matchId: string, player1Id: string, player2Id: string option, isPractice: bool, aiName: string option, onEvent: MatchEvent -> unit) =
        let mutable timerCts: CancellationTokenSource option = None

        let cancelTimer () =
            match timerCts with
            | Some cts ->
                cts.Cancel()
                cts.Dispose()
                timerCts <- None
            | None -> ()

        let scheduleTimeout (agent: MailboxProcessor<MatchMessage>) (delayMs: int) =
            cancelTimer ()
            let cts = new CancellationTokenSource()
            timerCts <- Some cts
            async {
                do! Async.Sleep delayMs
                if not cts.Token.IsCancellationRequested then
                    agent.Post PhaseTimeout
            }
            |> fun a -> Async.Start(a, cts.Token)

        let initialState =
            { MatchId = matchId
              Player1Id = player1Id
              Player2Id = player2Id
              Player1Connected = false
              Player2Connected = isPractice
              Phase = Created
              Player1Roll = None
              Player2Roll = None
              WinnerId = None
              IsPractice = isPractice
              AiName = aiName
              StartedAt = DateTime.UtcNow }

        let agent =
            MailboxProcessor.Start(fun inbox ->
                let rec loop (state: MatchState) =
                    async {
                        let! msg = inbox.Receive()

                        match msg with
                        | Shutdown ->
                            cancelTimer ()
                            return ()

                        | GetState reply ->
                            reply.Reply state
                            return! loop state

                        | PlayerJoined(playerId, reply) ->
                            let newState =
                                if playerId = state.Player1Id then
                                    { state with Player1Connected = true }
                                elif state.Player2Id = Some playerId then
                                    { state with Player2Connected = true }
                                else
                                    state

                            let newState =
                                if newState.Player1Connected && newState.Player2Connected && newState.Phase = Created then
                                    let s = { newState with Phase = Countdown 3 }
                                    onEvent(PhaseChangedEvent(matchId, "countdown", Map.ofList [ "timeRemaining", box 3000; "count", box 3 ]))
                                    scheduleTimeout inbox 1000
                                    s
                                elif newState.Phase = Created && isPractice && newState.Player1Connected then
                                    let s = { newState with Phase = Countdown 3 }
                                    onEvent(PhaseChangedEvent(matchId, "countdown", Map.ofList [ "timeRemaining", box 3000; "count", box 3 ]))
                                    scheduleTimeout inbox 1000
                                    s
                                elif newState.Phase = Created && newState.Player1Connected <> state.Player1Connected then
                                    let s = { newState with Phase = Connecting }
                                    scheduleTimeout inbox 10000
                                    s
                                elif newState.Phase = Created && newState.Player2Connected <> state.Player2Connected then
                                    let s = { newState with Phase = Connecting }
                                    scheduleTimeout inbox 10000
                                    s
                                else
                                    newState

                            reply.Reply newState
                            return! loop newState

                        | PhaseTimeout ->
                            match state.Phase with
                            | Connecting ->
                                if not state.Player1Connected && not state.Player2Connected then
                                    Database.abandonMatch state.MatchId
                                    onEvent(MatchCancelledEvent(matchId, "MATCH_ABANDONED", "Both players failed to connect"))
                                    cancelTimer ()
                                    return ()
                                elif not state.Player1Connected then
                                    match state.Player2Id with
                                    | Some p2Id ->
                                        Database.forfeitMatch state.MatchId p2Id
                                        onEvent(MatchCompletedEvent(matchId, p2Id, state.Player1Id, p2Id, None))
                                    | None -> ()
                                    cancelTimer ()
                                    return ()
                                elif state.Player2Id.IsSome && not state.Player2Connected then
                                    Database.forfeitMatch state.MatchId state.Player1Id
                                    onEvent(MatchCompletedEvent(matchId, state.Player1Id, state.Player1Id, state.Player2Id.Value, None))
                                    cancelTimer ()
                                    return ()
                                else
                                    return! loop state

                            | Countdown count when count > 1 ->
                                let newCount = count - 1
                                let newState = { state with Phase = Countdown newCount }
                                onEvent(PhaseChangedEvent(matchId, "countdown", Map.ofList [ "timeRemaining", box (newCount * 1000); "count", box newCount ]))
                                scheduleTimeout inbox 1000
                                return! loop newState

                            | Countdown _ ->
                                let roll1 = generateRoll ()
                                let roll2 = generateRoll ()
                                let newState =
                                    { state with
                                        Phase = Rolling
                                        Player1Roll = Some roll1
                                        Player2Roll = Some roll2 }
                                onEvent(PhaseChangedEvent(matchId, "rolling", Map.ofList [ "timeRemaining", box 2500 ]))
                                scheduleTimeout inbox 2500
                                return! loop newState

                            | Rolling ->
                                let newState = { state with Phase = Revealed }
                                onEvent(PhaseChangedEvent(matchId, "revealed",
                                    Map.ofList [
                                        "timeRemaining", box 2000
                                        "playerRoll", box (state.Player1Roll |> Option.defaultValue 0.0)
                                        "opponentRoll", box (state.Player2Roll |> Option.defaultValue 0.0)
                                    ]))
                                scheduleTimeout inbox 2000
                                return! loop newState

                            | Revealed ->
                                let winnerId = determineWinner state
                                match winnerId with
                                | Some wId ->
                                    let kFactor = if state.IsPractice then 0 else 32
                                    let eloChanges = completeMatchInDb { state with WinnerId = Some wId } wId kFactor
                                    onEvent(MatchCompletedEvent(matchId, wId, state.Player1Id, state.Player2Id |> Option.defaultValue "", eloChanges))
                                    cancelTimer ()
                                    return ()
                                | None ->
                                    cancelTimer ()
                                    return ()

                            | _ ->
                                return! loop state
                    }

                loop initialState)

        member _.PostPlayerJoined(playerId: string) =
            agent.PostAndAsyncReply(fun reply -> PlayerJoined(playerId, reply))

        member _.GetState() =
            agent.PostAndAsyncReply(fun reply -> GetState reply)

        member _.Shutdown() =
            agent.Post Shutdown
            cancelTimer ()

        member _.MatchId = matchId
        member _.Player1Id = player1Id
        member _.Player2Id = player2Id
        member _.IsPractice = isPractice
