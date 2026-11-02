namespace RNGWars

open System.Collections.Concurrent

module MatchmakingQueue =

    type QueueEntry =
        { UserId: string
          ConnectionId: string }

    let private queue = ConcurrentQueue<QueueEntry>()
    let private inQueue = ConcurrentDictionary<string, bool>()
    let mutable private onPaired: (string -> string -> string -> string -> unit) option = None

    let setPairedHandler (handler: string -> string -> string -> string -> unit) =
        onPaired <- Some handler

    let private tryPair () =
        let mutable player1 = None
        let mutable player2 = None

        let mutable searching = true
        while searching && not queue.IsEmpty do
            match queue.TryDequeue() with
            | true, entry ->
                if inQueue.ContainsKey(entry.UserId) then
                    match player1 with
                    | None -> player1 <- Some entry
                    | Some _ ->
                        player2 <- Some entry
                        searching <- false
            | _ -> searching <- false

        match player1, player2 with
        | Some p1, Some p2 ->
            inQueue.TryRemove(p1.UserId) |> ignore
            inQueue.TryRemove(p2.UserId) |> ignore
            match onPaired with
            | Some handler -> handler p1.UserId p1.ConnectionId p2.UserId p2.ConnectionId
            | None -> ()
        | Some p1, None ->
            queue.Enqueue(p1)
        | _ -> ()

    let enqueue (userId: string) (connectionId: string) : unit =
        if inQueue.TryAdd(userId, true) then
            queue.Enqueue({ UserId = userId; ConnectionId = connectionId })
            tryPair ()

    let dequeue (userId: string) : unit =
        inQueue.TryRemove(userId) |> ignore
