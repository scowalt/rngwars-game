namespace RNGWars

open System.Collections.Concurrent

module ConnectionTracker =

    let private userToConnection = ConcurrentDictionary<string, string>()
    let private connectionToUser = ConcurrentDictionary<string, string>()

    let track (userId: string) (connectionId: string) : unit =
        match userToConnection.TryGetValue(userId) with
        | true, oldConnId -> connectionToUser.TryRemove(oldConnId) |> ignore
        | _ -> ()

        userToConnection[userId] <- connectionId
        connectionToUser[connectionId] <- userId

    let untrack (connectionId: string) : string option =
        match connectionToUser.TryRemove(connectionId) with
        | true, userId ->
            match userToConnection.TryGetValue(userId) with
            | true, currentConnId when currentConnId = connectionId ->
                userToConnection.TryRemove(userId) |> ignore
            | _ -> ()

            Some userId
        | _ -> None

    let getConnectionId (userId: string) : string option =
        match userToConnection.TryGetValue(userId) with
        | true, connId -> Some connId
        | _ -> None

    let getUserId (connectionId: string) : string option =
        match connectionToUser.TryGetValue(connectionId) with
        | true, userId -> Some userId
        | _ -> None
