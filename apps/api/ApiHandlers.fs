namespace RNGWars

open Microsoft.AspNetCore.Http
open Giraffe

module ApiHandlers =

    let healthCheck: HttpHandler =
        fun next ctx -> task { return! json { Status = "ok" } next ctx }

    let createAnonymousUser: HttpHandler =
        fun next ctx ->
            task {
                let user = Database.createAnonymousUser ()
                ctx.SetStatusCode 201

                return!
                    json
                        { Token = user.AnonymousId
                          User = toUserResponse user }
                        next
                        ctx
            }

    let getMe: HttpHandler =
        fun next ctx ->
            task {
                let user = Auth.getCurrentUser ctx
                return! json (toUserResponse user) next ctx
            }

    let updateMe: HttpHandler =
        fun next ctx ->
            task {
                let! body = ctx.BindJsonAsync<UpdateUsernameRequest>()
                let user = Auth.getCurrentUser ctx

                match validateUsername body.Username with
                | Error msg ->
                    ctx.SetStatusCode 400

                    return!
                        json
                            { Error =
                                { Code = "USERNAME_INVALID"
                                  Message = msg } }
                            next
                            ctx
                | Ok validUsername ->
                    match Database.updateUsername user.Id validUsername with
                    | Some updated -> return! json (toUserResponse updated) next ctx
                    | None ->
                        ctx.SetStatusCode 500

                        return!
                            json
                                { Error =
                                    { Code = "INTERNAL_ERROR"
                                      Message = "Failed to update username" } }
                                next
                                ctx
            }

    let getMyMatches: HttpHandler =
        fun next ctx ->
            task {
                let user = Auth.getCurrentUser ctx

                let offset =
                    ctx.TryGetQueryStringValue "offset"
                    |> Option.bind (fun s ->
                        match System.Int32.TryParse(s) with
                        | true, v when v >= 0 -> Some v
                        | _ -> None)
                    |> Option.defaultValue 0

                let limit =
                    ctx.TryGetQueryStringValue "limit"
                    |> Option.bind (fun s ->
                        match System.Int32.TryParse(s) with
                        | true, v when v >= 1 && v <= 50 -> Some v
                        | _ -> None)
                    |> Option.defaultValue 20

                let matches = Database.getPlayerMatches user.Id offset (limit + 1)
                let hasMore = matches.Length > limit
                let results = if hasMore then matches |> List.take limit else matches

                let toMatchResponse (m: Match) =
                    let isPlayer1 = m.Player1Id = user.Id

                    { Id = m.Id
                      OpponentName =
                        if m.IsPractice then
                            m.AiName |> Option.defaultValue "AI"
                        else
                            let oppId =
                                if isPlayer1 then m.Player2Id else Some m.Player1Id

                            match oppId |> Option.bind Database.getUserById with
                            | Some u -> u.Username
                            | None -> "Unknown"
                      OpponentElo =
                        if isPlayer1 then m.Player2EloBefore else m.Player1EloBefore
                      PlayerRoll =
                        if isPlayer1 then m.Player1Roll else m.Player2Roll
                      OpponentRoll =
                        if isPlayer1 then m.Player2Roll else m.Player1Roll
                      PlayerEloBefore =
                        if isPlayer1 then m.Player1EloBefore else m.Player2EloBefore
                      PlayerEloAfter =
                        if isPlayer1 then m.Player1EloAfter else m.Player2EloAfter
                      Won =
                        m.WinnerId |> Option.map (fun wId -> wId = user.Id)
                      IsPractice = m.IsPractice
                      Status = m.Status
                      CompletedAt = m.CompletedAt }

                return!
                    json
                        { Matches = results |> List.map toMatchResponse
                          HasMore = hasMore }
                        next
                        ctx
            }

    let getLeaderboard: HttpHandler =
        fun next ctx ->
            task {
                let offset =
                    ctx.TryGetQueryStringValue "offset"
                    |> Option.bind (fun s ->
                        match System.Int32.TryParse(s) with
                        | true, v when v >= 0 -> Some v
                        | _ -> None)
                    |> Option.defaultValue 0

                let limit =
                    ctx.TryGetQueryStringValue "limit"
                    |> Option.bind (fun s ->
                        match System.Int32.TryParse(s) with
                        | true, v when v >= 1 && v <= 50 -> Some v
                        | _ -> None)
                    |> Option.defaultValue 20

                let users = Database.getLeaderboard offset (limit + 1)
                let hasMore = users.Length > limit
                let results = if hasMore then users |> List.take limit else users

                let entries =
                    results
                    |> List.mapi (fun i u ->
                        { Rank = offset + i + 1
                          UserId = u.Id
                          Username = u.Username
                          RngScore = u.RngScore
                          TotalWins = u.TotalWins
                          TotalLosses = u.TotalLosses
                          TotalMatches = u.TotalMatches })

                return!
                    json
                        { Entries = entries
                          HasMore = hasMore }
                        next
                        ctx
            }

    let startPractice: HttpHandler =
        fun next ctx ->
            task {
                let user = Auth.getCurrentUser ctx

                match MatchManager.createPracticeMatch user.Id with
                | Ok(matchId, opponentName) ->
                    ctx.SetStatusCode 201

                    return!
                        json
                            { MatchId = matchId
                              OpponentName = opponentName }
                            next
                            ctx
                | Error msg ->
                    ctx.SetStatusCode 503

                    return!
                        json
                            { Error =
                                { Code = "SERVER_CAPACITY"
                                  Message = msg } }
                            next
                            ctx
            }

    let getMatch (matchId: string) : HttpHandler =
        fun next ctx ->
            task {
                let user = Auth.getCurrentUser ctx

                match Database.getMatchById matchId with
                | None ->
                    ctx.SetStatusCode 404

                    return!
                        json
                            { Error =
                                { Code = "NOT_FOUND"
                                  Message = "Match not found" } }
                            next
                            ctx
                | Some m ->
                    let isParticipant =
                        m.Player1Id = user.Id
                        || m.Player2Id = Some user.Id

                    if not isParticipant then
                        ctx.SetStatusCode 403

                        return!
                            json
                                { Error =
                                    { Code = "FORBIDDEN"
                                      Message = "You are not a participant in this match" } }
                                next
                                ctx
                    else
                        let isPlayer1 = m.Player1Id = user.Id

                        let response =
                            { Id = m.Id
                              OpponentName =
                                if m.IsPractice then
                                    m.AiName |> Option.defaultValue "AI"
                                else
                                    let oppId =
                                        if isPlayer1 then m.Player2Id else Some m.Player1Id

                                    match oppId |> Option.bind Database.getUserById with
                                    | Some u -> u.Username
                                    | None -> "Unknown"
                              OpponentElo =
                                if isPlayer1 then m.Player2EloBefore else m.Player1EloBefore
                              PlayerRoll =
                                if isPlayer1 then m.Player1Roll else m.Player2Roll
                              OpponentRoll =
                                if isPlayer1 then m.Player2Roll else m.Player1Roll
                              PlayerEloBefore =
                                if isPlayer1 then m.Player1EloBefore else m.Player2EloBefore
                              PlayerEloAfter =
                                if isPlayer1 then m.Player1EloAfter else m.Player2EloAfter
                              Won =
                                m.WinnerId |> Option.map (fun wId -> wId = user.Id)
                              IsPractice = m.IsPractice
                              Status = m.Status
                              CompletedAt = m.CompletedAt }

                        return! json response next ctx
            }
