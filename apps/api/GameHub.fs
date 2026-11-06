namespace RNGWars

open System
open System.Threading.Tasks
open Microsoft.AspNetCore.SignalR

type GameHub() =
    inherit Hub()

    let getUserFromToken (context: HubCallerContext) : User option =
        let httpContext = context.GetHttpContext()
        let token = httpContext.Request.Query["access_token"].ToString()

        match Guid.TryParse(token) with
        | true, _ -> Database.getUserByToken token
        | false, _ -> None

    override this.OnConnectedAsync() =
        task {
            match getUserFromToken this.Context with
            | Some user ->
                ConnectionTracker.track user.Id this.Context.ConnectionId

                match MatchManager.getActiveMatchForPlayer user.Id with
                | Some agent ->
                    do! this.Groups.AddToGroupAsync(this.Context.ConnectionId, sprintf "match:%s" agent.MatchId)
                    let! state = agent.GetState() |> Async.StartAsTask
                    match state.Phase with
                    | MatchAgent.Countdown count ->
                        do! this.Clients.Caller.SendAsync("PhaseChanged",
                            {| phase = "countdown"; timeRemaining = count * 1000; count = count |})
                    | MatchAgent.Rolling ->
                        do! this.Clients.Caller.SendAsync("PhaseChanged",
                            {| phase = "rolling"; timeRemaining = 0 |})
                    | MatchAgent.Revealed ->
                        do! this.Clients.Caller.SendAsync("PhaseChanged",
                            {| phase = "revealed"; timeRemaining = 0
                               player1Id = state.Player1Id
                               player1Roll = state.Player1Roll |> Option.defaultValue 0.0
                               player2Roll = state.Player2Roll |> Option.defaultValue 0.0 |})
                    | _ -> ()
                | None -> ()
            | None ->
                this.Context.Abort()
        }
        :> Task

    override this.OnDisconnectedAsync(_exception) =
        task {
            MatchmakingQueue.removeConnection this.Context.ConnectionId

            match ConnectionTracker.untrack this.Context.ConnectionId with
            | Some _userId -> ()
            | None -> ()
        }
        :> Task

    member this.JoinQueue() : Task =
        task {
            match getUserFromToken this.Context with
            | Some user ->
                MatchmakingQueue.enqueue user.Id this.Context.ConnectionId
            | None -> ()
        }
        :> Task

    member this.LeaveQueue() : Task =
        task {
            match getUserFromToken this.Context with
            | Some user ->
                MatchmakingQueue.dequeue user.Id
            | None -> ()
        }
        :> Task

    member this.JoinMatch(matchId: string) : Task =
        task {
            match getUserFromToken this.Context with
            | Some user ->
                match MatchManager.getAgent matchId with
                | Some agent ->
                    do! this.Groups.AddToGroupAsync(this.Context.ConnectionId, sprintf "match:%s" matchId)
                    let! _ = agent.PostPlayerJoined(user.Id) |> Async.StartAsTask
                    ()
                | None ->
                    do! this.Clients.Caller.SendAsync("MatchCancelled",
                        {| error = {| code = "MATCH_NOT_FOUND"; message = "Match not found or already completed" |} |})
            | None -> ()
        }
        :> Task
